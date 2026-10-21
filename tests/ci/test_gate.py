# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Exercise partial/stale evidence rejection, independently of workflow execution."""

import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ci_contract as contract
from build_support import ROOT, read

IDENTITY = {"repository": contract.REPOSITORY, "commit": "a" * 40, "run_id": "100",
            "run_attempt": "2", "hosted": True, "dirty": False}
DEFINITIONS = {"scripts/ci.py": "b" * 64}
CHECKS = {name: {"result": "success"} for name in ("build", "quality", "codeql")}


def records(tier="pr"):
    policy = read(ROOT / "cmake/ci-matrix.json")
    pinned = contract.lock()
    return [{"schema": 1, "tier": tier, "status": "success", "identity": copy.deepcopy(IDENTITY),
             "definitions": dict(DEFINITIONS), "configuration": item, "require_release": False,
             "runtime": {"system": item["system"], "python": item["python"] + ".1"},
             "compiler": {"COMPILER_ID": "Clang", "COMPILER_VERSION": "18.0",
                          "SYSTEM": item["system"], "SIZEOF_DATA_PTR": "8", "CROSS_COMPILING": "FALSE"},
             "core": {key: pinned[key] for key in ("repository", "commit", "version")}
             | {"mode": "pinned-git", "verified": False, "dirty": False},
             "smoke": True, "wheels": {"opentlv": "c" * 64, "opentlv-core": "d" * 64},
             "tests": {"tests": policy["pytest_cases"], "failures": 0, "errors": 0, "skipped": 0},
             "examples": policy["examples"],
             "query": {"fixtures": policy["query_fixtures"], "checks": policy["query_checks"]},
             "packaging": "sdist-wheel" if tier == "full" else "wheel"}
            for item in contract.matrix(tier)]


@pytest.mark.parametrize("tier", contract.TIERS)
def test_complete_gate(tier):
    checks = copy.deepcopy(CHECKS)
    if tier == "main":
        checks["quality"]["result"] = checks["codeql"]["result"] = "skipped"
    report = contract.validate_records(records(tier), tier, IDENTITY, DEFINITIONS, checks)
    assert report["status"] == "success"
    assert len(report["configurations"]) == (15 if tier == "full" else 1)


@pytest.mark.parametrize("path,value", [
    (("schema",), 2), (("tier",), "full"), (("status",), "failed"),
    (("identity", "run_attempt"), "1"), (("identity", "run_id"), "99"),
    (("identity", "commit"), "e" * 40), (("identity", "repository"), "other/repository"),
    (("identity", "hosted"), False), (("identity", "dirty"), True),
    (("definitions", "scripts/ci.py"), "e" * 64),
    (("configuration", "python"), "3.12"), (("configuration", "id"), "unknown"),
    (("runtime", "system"), "Windows"), (("runtime", "python"), "3.12.1"),
    (("core", "commit"), "f" * 40), (("core", "dirty"), True),
    (("core", "mode"), "local-source"), (("core", "verified"), True),
    (("tests", "tests"), 1), (("tests", "skipped"), 1), (("tests", "errors"), 1),
    (("tests", "failures"), 1), (("examples",), 7), (("query", "checks"), 663),
    (("query", "fixtures"), 170), (("packaging",), "none"), (("smoke",), False),
    (("wheels", "opentlv-core"), "bad"), (("require_release",), True),
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
    if kind == "missing":
        data.pop()
    elif kind == "duplicate":
        data.append(copy.deepcopy(data[0]))
    else:
        data[-1] = copy.deepcopy(data[0])
    with pytest.raises(ValueError):
        contract.validate_records(data, "full", IDENTITY, DEFINITIONS, CHECKS)


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", None])
@pytest.mark.parametrize("job", ["build", "quality", "codeql"])
def test_rejects_unsuccessful_prerequisites(job, result):
    checks = copy.deepcopy(CHECKS)
    checks[job]["result"] = result
    with pytest.raises(ValueError):
        contract.validate_records(records(), "pr", IDENTITY, DEFINITIONS, checks)


def test_rejects_missing_prerequisite():
    with pytest.raises(ValueError):
        contract.validate_records(records(), "pr", IDENTITY, DEFINITIONS, {"build": CHECKS["build"]})


def test_release_fails_with_current_null_lock():
    data = records("full")
    for record in data:
        record["require_release"] = True
    with pytest.raises(ValueError, match="published Core"):
        contract.validate_records(data, "full", IDENTITY, DEFINITIONS, CHECKS, True)


def test_release_requires_attestation_even_after_lock_update(monkeypatch):
    pinned = contract.lock()
    monkeypatch.setattr(contract, "lock", lambda _=False: {**pinned, "release_tag": "v" + pinned["version"]})
    with pytest.raises(ValueError, match="attestation"):
        contract.validate_dependency(records()[0]["core"], True)


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


def test_failed_build_invalidates_stale_success(tmp_path):
    import argparse
    import ci
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
