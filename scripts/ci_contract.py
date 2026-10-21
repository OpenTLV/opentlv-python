# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Shared matrix and fail-closed evidence checks for Python's CI entry points."""

import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from build_support import ROOT, digest, read, require, run
from verified_core import lock

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
        "CMakeLists.txt", "pyproject.toml", "requirements-dev.txt", ".clang-format", ".clang-tidy")]
    for directory in ("scripts", "cmake", "bindings", "tests", ".github/workflows"):
        paths.extend(path for path in (ROOT / directory).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts
                     and (path.suffix in (".py", ".c", ".h", ".json", ".cmake", ".toml", ".yml")
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


def validate_records(records, tier, expected_identity, definitions, checks, require_release=False):
    require(tier in TIERS, "Unknown CI tier")
    require(not require_release or tier == "full", "Release requires Full CI")
    required = {"build", "quality", "codeql"}
    require(set(checks) == required, "Missing or unexpected prerequisite job")
    for name in required:
        expected = "skipped" if tier == "main" and name != "build" else "success"
        require(checks[name].get("result") == expected, f"Unsuccessful prerequisite: {name}")
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
        require(record.get("runtime", {}).get("system") == expected[name]["system"]
                and record["runtime"].get("python", "").startswith(expected[name]["python"] + "."),
                "Runtime differs from matrix")
        compiler = record.get("compiler", {})
        require(compiler.get("COMPILER_ID") and compiler.get("COMPILER_VERSION")
                and compiler.get("SYSTEM") == expected[name]["system"]
                and compiler.get("SIZEOF_DATA_PTR") == "8"
                and compiler.get("CROSS_COMPILING") == "FALSE",
                "Missing or incompatible compiler evidence")
        validate_dependency(record["core"], require_release)
        require(record.get("smoke") is True, "Missing installed-package smoke")
        require(set(record.get("wheels", {})) == {"opentlv", "opentlv-core"}
                and all(re.fullmatch(r"[0-9a-f]{64}", value)
                        for value in record["wheels"].values()), "Missing wheel digests")
        if tier != "main":
            tests = record.get("tests", {})
            require(tests.get("tests") == policy["pytest_cases"]
                    and all(tests.get(key) == 0 for key in ("failures", "errors", "skipped")),
                    "Incomplete Python test suite")
            require(record.get("examples") == policy["examples"], "Incomplete examples")
            require(record.get("query") == {"fixtures": policy["query_fixtures"],
                                           "checks": policy["query_checks"]},
                    "Incomplete Query facade run")
        require(record.get("packaging") == ("sdist-wheel" if tier == "full" else "wheel"),
                "Packaging validation differs")
    return {"schema": 1, "tier": tier, "identity": expected_identity,
            "definitions": definitions, "require_release": require_release,
            "checks": checks, "configurations": sorted(seen), "status": "success"}
