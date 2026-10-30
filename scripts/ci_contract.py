# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Shared matrix and fail-closed evidence checks for Python's CI entry points."""

import os
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from build_support import ROOT, digest, read, require, run
from verified_core import lock
from package_contract import DISTRIBUTION, policy as package_policy, validate_artifact_record, wheel_name

REPOSITORY = "OpenTLV/opentlv-python"
TIERS = ("pr", "main", "full")


def matrix(tier):
    require(tier in TIERS, "Unknown CI tier")
    policy = read(ROOT / "cmake/ci-matrix.json")
    platforms = policy["platforms"] if tier == "full" else policy["platforms"][:1]
    versions = policy["python"] if tier == "full" else policy["python"][:1]
    return [{"id": f'{platform["id"]}-{version}', "os": platform["os"],
             "system": platform["system"], "python": version}
            for platform in platforms for version in versions]


def definition_hashes():
    paths = [ROOT / name for name in (
        "CMakeLists.txt", "pyproject.toml", "requirements-dev.txt", ".clang-format", ".clang-tidy",
        "CHANGELOG.md", "docs/release-notes.md")]
    for directory in ("scripts", "cmake", "src", "native", "examples", "tests", ".github/workflows"):
        paths.extend(path for path in (ROOT / directory).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts
                     and (path.suffix in (".py", ".c", ".h", ".in", ".json", ".cmake", ".toml", ".yml")
                          or path.name == "CMakeLists.txt"))
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(set(paths))}


def identity():
    hosted = os.environ.get("GITHUB_ACTIONS") == "true"
    commit = run("git", "rev-parse", "HEAD", capture=True)
    dirty = bool(run("git", "status", "--porcelain", "--untracked-files=all", capture=True))
    if hosted:
        require(commit == os.environ["GITHUB_SHA"] and not dirty, "CI checkout identity changed")
    return {"repository": os.environ.get("GITHUB_REPOSITORY", REPOSITORY),
            "commit": commit, "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
            "hosted": hosted, "dirty": dirty}


def validate_dependency(selected, require_release=False):
    pinned = lock(require_release)
    require(all(selected.get(key) == pinned[key] for key in ("repository", "commit", "version")),
            "Core selection differs from the dependency lock")
    mode = selected.get("mode")
    if pinned["release_tag"] is None:
        require(mode == "pinned-git" and selected.get("verified") is False
                and selected.get("dirty") is False, "Expected a clean pinned Core checkout")
    else:
        require(mode in ("verified-source", "verified-binary") and selected.get("verified") is True,
                "Core release attestation is required")
        require(selected.get("release_tag") == pinned["release_tag"]
                and selected.get("release_id")
                and re.fullmatch(r"[0-9a-f]{64}", selected.get("manifest_sha256", "")),
                "Core release identity is incomplete")


def junit_counts(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    require(suites, "Missing pytest result suites")
    result = {key: sum(int(suite.get(key, "0")) for suite in suites)
              for key in ("tests", "failures", "errors", "skipped")}
    require(result["tests"] > 0 and all(result[key] == 0 for key in ("failures", "errors", "skipped")),
            "Incomplete or unsuccessful pytest run")
    require(len(list(root.iter("testcase"))) == result["tests"], "Contradictory pytest counts")
    require(not any(list(root.iter(tag)) for tag in ("failure", "error", "skipped")),
            "JUnit testcase contradicts success counters")
    return result


def select_distributions(records):
    """Choose the unique upload set: one wheel per platform and one sdist.

    Builds are not bit-for-bit reproducible, so every Full configuration produces its own bytes under
    the same filename. Each platform's build on the stable-ABI floor supplies its wheel, and the first
    platform's floor build supplies the sdist; all of them are the exact bytes that build tested.
    """
    configurations = matrix("full")
    floor = configurations[0]["python"]
    selected = {}
    for record in records:
        configuration = record["configuration"]
        if configuration["python"] != floor:
            continue
        for relative, sha in record["artifacts"].items():
            if relative.startswith("wheels/") or configuration["id"] == configurations[0]["id"]:
                name = relative.split("/")[1]
                require(name not in selected, "Duplicate distribution filename in the upload set")
                selected[name] = {"source": configuration["id"] + "/" + relative, "sha256": sha}
    platforms = {item["system"] for item in configurations}
    require(sum(name.endswith(".whl") for name in selected) == len(platforms)
            and sum(name.endswith(".tar.gz") for name in selected) == 1, "Incomplete distribution upload set")
    return selected


def validate_runtime(record, expected):
    require(record.get("runtime", {}).get("system") == expected["system"]
            and record["runtime"].get("python", "").startswith(expected["python"] + "."),
            "Runtime differs from matrix")


def validate_suite(record, policy):
    """Require the complete existing tests, examples and Query adapter run."""
    tests = record.get("tests", {})
    require(tests.get("tests") == policy["pytest_cases"]
            and all(tests.get(key) == 0 for key in ("failures", "errors", "skipped")),
            "Incomplete Python test suite")
    require(record.get("examples") == policy["examples"], "Incomplete examples")
    require(record.get("query") == {"fixtures": policy["query_fixtures"],
                                   "checks": policy["query_checks"]},
            "Incomplete Query facade run")


def validate_verifications(verifications, records, upload, expected_identity, definitions, require_release):
    """Every Full configuration must install its platform's selected wheel by name and pass the suite."""
    expected = {item["id"]: item for item in matrix("full")}
    require(len(verifications) == len(expected), "Missing or duplicate upload set verification")
    builds = {record["configuration"]["id"]: record for record in records}
    package = package_policy()
    policy = read(ROOT / "cmake/ci-matrix.json")
    digests = {name: item["sha256"] for name, item in upload.items()}
    seen = set()
    for record in verifications:
        name = record.get("configuration", {}).get("id")
        require(name in expected and name not in seen, "Unexpected or duplicate upload set verification")
        seen.add(name)
        require(record.get("schema") == 1 and record.get("kind") == "upload-verification"
                and record.get("tier") == "full" and record.get("status") == "success",
                "Unsuccessful upload set verification")
        require(record.get("identity") == expected_identity, "Wrong repository/commit/run/attempt")
        require(record.get("definitions") == definitions, "CI definitions differ")
        require(record.get("configuration") == expected[name], "Configuration differs")
        require(record.get("require_release") is require_release, "Release policy differs")
        validate_runtime(record, expected[name])
        require(record.get("upload") == digests, "Verified bytes differ from the selected upload set")
        wheel = wheel_name(package, expected[name]["system"])
        require(record.get("installed") == {wheel: digests[wheel]},
                "Configuration did not install its platform's selected wheel")
        source = upload[wheel]["source"].split("/")[0]
        require(record.get("core") == builds[source]["core"], "Verified Core identity differs from the build")
        require(record.get("smoke") is True
                and record.get("package_versions") == {DISTRIBUTION: package["version"]},
                "Missing installed-package smoke")
        validate_suite(record, policy)
    return {record["configuration"]["id"]: hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
            for record in verifications}


def validate_records(records, tier, expected_identity, definitions, checks, require_release=False,
                     verifications=()):
    require(tier in TIERS, "Unknown CI tier")
    require(not require_release or tier == "full", "Release requires Full CI")
    required = {"build", "select", "verify", "quality", "codeql"}
    require(set(checks) == required, "Missing or unexpected prerequisite job")
    for name in required:
        # Only Full verifies an upload set; Main also skips source analysis.
        skipped = ((name in ("select", "verify") and tier != "full")
                   or (name in ("quality", "codeql") and tier == "main"))
        require(checks[name].get("result") == ("skipped" if skipped else "success"),
                f"Unsuccessful prerequisite: {name}")
    expected = {item["id"]: item for item in matrix(tier)}
    require(len(records) == len(expected), "Missing or duplicate configuration evidence")
    seen = set()
    policy = read(ROOT / "cmake/ci-matrix.json")
    for record in records:
        name = record.get("configuration", {}).get("id")
        require(name in expected and name not in seen, "Unexpected or duplicate configuration")
        seen.add(name)
        require(record.get("schema") == 1 and record.get("tier") == tier
                and record.get("status") == "success", "Unsuccessful build evidence")
        require(record.get("identity") == expected_identity, "Wrong repository/commit/run/attempt")
        require(record.get("definitions") == definitions, "CI definitions differ")
        require(record.get("configuration") == expected[name], "Configuration differs")
        require(record.get("require_release") is require_release, "Release policy differs")
        validate_runtime(record, expected[name])
        compiler = record.get("compiler", {})
        require(compiler.get("COMPILER_ID") and compiler.get("COMPILER_VERSION")
                and compiler.get("SYSTEM") == expected[name]["system"]
                and compiler.get("SIZEOF_DATA_PTR") == "8"
                and compiler.get("CROSS_COMPILING") == "FALSE",
                "Missing or incompatible compiler evidence")
        validate_dependency(record["core"], require_release)
        require(record.get("smoke") is True, "Missing installed-package smoke")
        require(set(record.get("wheels", {})) == {DISTRIBUTION}
                and re.fullmatch(r"[0-9a-f]{64}", record["wheels"][DISTRIBUTION]), "Missing wheel digest")
        validate_artifact_record(record, package_policy())
        if tier != "main":
            validate_suite(record, policy)
        require(record.get("packaging") == ("sdist-wheel" if tier == "full" else "wheel"),
                "Packaging validation differs")
    upload, verified = {}, {}
    if tier == "full":
        upload = select_distributions(records)
        verified = validate_verifications(verifications, records, upload, expected_identity, definitions,
                                          require_release)
    else:
        require(not verifications, "Only Full CI verifies an upload set")
    return {"schema": 1, "tier": tier, "identity": expected_identity,
            "definitions": definitions, "require_release": require_release,
            "records": {record["configuration"]["id"]:
                        hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
                        for record in records},
            "upload": upload, "verifications": verified,
            "checks": checks, "configurations": sorted(seen), "status": "success"}
