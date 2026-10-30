# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Exercise partial/stale evidence rejection, independently of workflow execution."""

import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ci_contract as contract
import verified_core
from build_support import ROOT, read
from package_contract import DISTRIBUTION, artifact_names, policy as package_policy, wheel_name

IDENTITY = {"repository": contract.REPOSITORY, "commit": "a" * 40, "run_id": "100",
            "run_attempt": "2", "hosted": True, "dirty": False}
DEFINITIONS = {"scripts/ci.py": "b" * 64}
JOBS = ("build", "select", "verify", "quality", "codeql")


def checks(tier="pr"):
    """Job results of a successful run: only Full verifies an upload set, Main has no source analysis."""
    skipped = ({"select", "verify"} if tier != "full" else set()) | (
        {"quality", "codeql"} if tier == "main" else set())
    return {name: {"result": "skipped" if name in skipped else "success"} for name in JOBS}


CHECKS = checks()


def null_lock(monkeypatch):
    """Select the committed Core commit without a release tag, as before Core v0.8.0."""
    pinned = verified_core.lock()
    monkeypatch.setattr(verified_core, "read", lambda _: {**pinned, "release_tag": None})


def records(tier="pr"):
    policy = read(ROOT / "cmake/ci-matrix.json")
    pinned = contract.lock()
    package = package_policy()
    version = package["version"]
    return [{"schema": 1, "tier": tier, "status": "success", "identity": copy.deepcopy(IDENTITY),
             "definitions": dict(DEFINITIONS), "configuration": item, "require_release": False,
             "runtime": {"system": item["system"], "python": item["python"] + ".1"},
             "compiler": {"COMPILER_ID": "Clang", "COMPILER_VERSION": "18.0",
                          "SYSTEM": item["system"], "SIZEOF_DATA_PTR": "8", "CROSS_COMPILING": "FALSE"},
             "core": {key: pinned[key] for key in ("repository", "commit", "version", "release_tag")}
             | {"mode": "verified-source", "verified": True, "release_id": 1, "manifest_sha256": "f" * 64},
             "smoke": True, "wheels": {DISTRIBUTION: "c" * 64},
             "package_version": version, "package_versions": {DISTRIBUTION: version},
             "artifacts": {directory + "/" + name: ("c" if directory == "wheels" else "e") * 64
                           for directory, name in artifact_names(tier, package, item["system"]).items()},
             "tests": {"tests": policy["pytest_cases"], "failures": 0, "errors": 0, "skipped": 0},
             "examples": policy["examples"],
             "query": {"fixtures": policy["query_fixtures"], "checks": policy["query_checks"]},
             "packaging": "sdist-wheel" if tier == "full" else "wheel"}
            for item in contract.matrix(tier)]


def verifications(data):
    """What each Full configuration records after installing its platform's selected wheel."""
    package = package_policy()
    upload = contract.select_distributions(data)
    builds = {record["configuration"]["id"]: record for record in data}
    result = []
    for record in data:
        wheel = wheel_name(package, record["configuration"]["system"])
        source = builds[upload[wheel]["source"].split("/")[0]]
        result.append(copy.deepcopy({key: record[key] for key in (
            "schema", "tier", "status", "identity", "definitions", "configuration", "require_release",
            "runtime", "smoke", "package_versions", "tests", "examples", "query")}) | {
            "kind": "upload-verification", "core": copy.deepcopy(source["core"]),
            "upload": {name: item["sha256"] for name, item in upload.items()},
            "installed": {wheel: upload[wheel]["sha256"]}})
    return result


@pytest.mark.parametrize("tier", contract.TIERS)
def test_complete_gate(tier):
    data = records(tier)
    report = contract.validate_records(data, tier, IDENTITY, DEFINITIONS, checks(tier), False,
                                       verifications(data) if tier == "full" else ())
    assert report["status"] == "success"
    assert len(report["configurations"]) == (15 if tier == "full" else 1)
    assert len(report["upload"]) == (4 if tier == "full" else 0)
    assert len(report["verifications"]) == (15 if tier == "full" else 0)


@pytest.mark.parametrize("path,value", [
    (("schema",), 2), (("tier",), "full"), (("status",), "failed"),
    (("identity", "run_attempt"), "1"), (("identity", "run_id"), "99"),
    (("identity", "commit"), "e" * 40), (("identity", "repository"), "other/repository"),
    (("identity", "hosted"), False), (("identity", "dirty"), True),
    (("definitions", "scripts/ci.py"), "e" * 64),
    (("configuration", "python"), "3.12"), (("configuration", "id"), "unknown"),
    (("runtime", "system"), "Windows"), (("runtime", "python"), "3.12.1"),
    (("core", "commit"), "f" * 40), (("core", "release_tag"), "v0.7.1"),
    (("core", "release_id"), None), (("core", "manifest_sha256"), "bad"),
    (("core", "mode"), "pinned-git"), (("core", "mode"), "local-source"), (("core", "verified"), False),
    (("tests", "tests"), 1), (("tests", "skipped"), 1), (("tests", "errors"), 1),
    (("tests", "failures"), 1), (("examples",), 7), (("query", "checks"), 663),
    (("query", "fixtures"), 170), (("packaging",), "none"), (("smoke",), False),
    (("wheels", "opentlv"), "bad"), (("wheels", "opentlv-core"), "d" * 64), (("require_release",), True),
    (("package_version",), "0.7.1"), (("package_versions", "opentlv"), "0.2.0"),
    (("package_versions", "opentlv-core"), "0.1.0"), (("artifacts",), {}),
    (("artifacts", "wheels/opentlv-0.1.0-cp311-abi3-linux_x86_64.whl"), "c" * 64),
    (("compiler", "SYSTEM"), "Windows"), (("compiler", "COMPILER_ID"), ""),
    (("compiler", "CROSS_COMPILING"), "TRUE"),
])
def test_rejects_incomplete_or_foreign_record(path, value):
    data = records()
    target = data[0]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        contract.validate_records(data, "pr", IDENTITY, DEFINITIONS, CHECKS)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "substitution"])
def test_rejects_partial_full_matrix(kind):
    data = records("full")
    verified = verifications(data)
    if kind == "missing":
        data.pop()
    elif kind == "duplicate":
        data.append(copy.deepcopy(data[0]))
    else:
        data[-1] = copy.deepcopy(data[0])
    with pytest.raises(ValueError, match="configuration"):
        contract.validate_records(data, "full", IDENTITY, DEFINITIONS, checks("full"), False, verified)


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", None])
@pytest.mark.parametrize("job", JOBS)
def test_rejects_unsuccessful_prerequisites(job, result):
    data = records("full")
    results = checks("full")
    results[job]["result"] = result
    with pytest.raises(ValueError, match="prerequisite: " + job):
        contract.validate_records(data, "full", IDENTITY, DEFINITIONS, results, False, verifications(data))


@pytest.mark.parametrize("tier", ["pr", "main"])
@pytest.mark.parametrize("job", ["select", "verify"])
def test_only_full_verifies_an_upload_set(tier, job):
    results = checks(tier)
    results[job]["result"] = "success"
    with pytest.raises(ValueError, match="prerequisite: " + job):
        contract.validate_records(records(tier), tier, IDENTITY, DEFINITIONS, results)
    with pytest.raises(ValueError, match="Only Full"):
        contract.validate_records(records(tier), tier, IDENTITY, DEFINITIONS, checks(tier), False,
                                  verifications(records("full"))[:1])


def test_rejects_missing_prerequisite():
    with pytest.raises(ValueError):
        contract.validate_records(records(), "pr", IDENTITY, DEFINITIONS, {"build": CHECKS["build"]})


def test_committed_lock_selects_attested_core_080():
    pinned = contract.lock(True)
    assert pinned["release_tag"] == "v0.8.0"
    assert pinned["commit"] == "345c77acb29266036df5f27d04ce315bb61853cc"


def test_null_lock_requires_clean_pinned_git(monkeypatch):
    null_lock(monkeypatch)
    data = records()
    data[0]["core"] = {key: data[0]["core"][key] for key in ("repository", "commit", "version")}
    data[0]["core"].update(mode="pinned-git", verified=False, dirty=False)
    assert contract.validate_records(data, "pr", IDENTITY, DEFINITIONS, CHECKS)["status"] == "success"
    data[0]["core"]["dirty"] = True
    with pytest.raises(ValueError, match="clean pinned"):
        contract.validate_records(data, "pr", IDENTITY, DEFINITIONS, CHECKS)


def test_release_fails_with_null_lock(monkeypatch):
    null_lock(monkeypatch)
    data = records("full")
    for record in data:
        record["require_release"] = True
    with pytest.raises(ValueError, match="published Core"):
        contract.validate_records(data, "full", IDENTITY, DEFINITIONS, checks("full"), True, verifications(data))


def test_release_requires_attestation():
    core = records()[0]["core"]
    contract.validate_dependency(core, True)
    with pytest.raises(ValueError, match="attestation"):
        contract.validate_dependency({**core, "mode": "pinned-git", "verified": False}, True)


@pytest.mark.parametrize("extra", ["skipped", "failure", "error"])
def test_junit_rejects_bad_result(tmp_path, extra):
    field = {"skipped": "skipped", "failure": "failures", "error": "errors"}[extra]
    path = tmp_path / "results.xml"
    path.write_text(f'<testsuites><testsuite tests="1" {field}="1">'
                    f'<testcase><{extra}/></testcase></testsuite></testsuites>')
    with pytest.raises(ValueError):
        contract.junit_counts(path)


def test_junit_rejects_contradictory_count(tmp_path):
    path = tmp_path / "results.xml"
    path.write_text('<testsuites><testsuite tests="2"><testcase/></testsuite></testsuites>')
    with pytest.raises(ValueError, match="Contradictory"):
        contract.junit_counts(path)


def test_junit_success(tmp_path):
    path = tmp_path / "results.xml"
    path.write_text('<testsuites><testsuite tests="1"><testcase/></testsuite></testsuites>')
    assert contract.junit_counts(path) == {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}


def test_junit_rejects_failure_hidden_by_success_counters(tmp_path):
    path = tmp_path / "results.xml"
    path.write_text('<testsuites><testsuite tests="1"><testcase><failure/></testcase></testsuite></testsuites>')
    with pytest.raises(ValueError, match="contradicts"):
        contract.junit_counts(path)


def test_failed_build_invalidates_stale_success(tmp_path, monkeypatch):
    import argparse
    import ci
    null_lock(monkeypatch)
    output = tmp_path / "record.json"
    output.write_text('{"status": "success"}')
    args = argparse.Namespace(output=output, require_release=True, tier="full")
    with pytest.raises(ValueError, match="published Core"):
        ci.build(args)
    assert not output.exists()


def test_static_baseline_requires_exact_sources(monkeypatch):
    import check_static
    assert check_static.baseline()
    monkeypatch.setattr(check_static, "digest", lambda _: "0" * 64)
    with pytest.raises(ValueError, match="Reassess"):
        check_static.baseline()
