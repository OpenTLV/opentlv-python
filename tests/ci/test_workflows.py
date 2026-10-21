# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Protect trigger, ownership and required-check contracts during CI maintenance."""

from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from build_support import ROOT, read
from ci_contract import matrix


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def test_entry_points_do_not_duplicate_full_ci():
    pr = workflow("python-pr.yml")
    main = workflow("python-main.yml")
    full = workflow("python-full.yml")
    assert pr["on"] == {"pull_request": {"branches": ["main"]}}
    assert main["on"] == {"push": {"branches": ["main"]}}
    assert set(full["on"]) == {"workflow_dispatch", "workflow_call"}
    assert full["concurrency"]["cancel-in-progress"] == "false"
    assert full["jobs"]["checks"]["with"]["tier"] == "full"


def test_matrix_preserves_platforms_and_declared_cpython_floor():
    import tomllib
    for path in ("pyproject.toml", "src/pyproject.toml"):
        assert tomllib.loads((ROOT / path).read_text())["project"]["requires-python"] == ">=3.11"
    configurations = matrix("full")
    assert len({item["id"] for item in configurations}) == 15
    assert {item["python"] for item in configurations} == {"3.11", "3.12", "3.13", "3.14", "3.15"}
    assert {item["system"] for item in configurations} == {"Linux", "Windows", "Darwin"}
    assert matrix("pr") == matrix("main") == configurations[:1]


def test_always_running_gate_and_attempt_scoped_artifacts():
    checks = workflow("python-checks.yml")
    gate = checks["jobs"]["gate"]
    assert gate["name"] == "Python quality gate"
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == {"build", "quality", "codeql"}
    for job in checks["jobs"].values():
        for step in job.get("steps", []):
            if step.get("uses", "").startswith("actions/upload-artifact@"):
                assert "github.run_attempt" in step["with"]["name"]
                assert step["with"]["if-no-files-found"] == "error"


def test_core_native_tests_stay_disabled():
    cmake = (ROOT / "cmake/Core.cmake").read_text()
    assert "foreach(_option CXX LUA PYTHON WASM TESTS EXAMPLES DOCS BENCHMARKS FUZZING SHARED_LIBS)" in cmake
    assert 'set(OPENTLV_BUILD_${_option} OFF CACHE INTERNAL' in cmake
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        text = path.read_text()
        assert "gh workflow run" not in text
        assert "OPENTLV_BUILD_TESTS=ON" not in text
        assert "ctest" not in text
    assert not (ROOT / "tests/query/corpus.json").exists()


def test_release_prepares_attested_artifacts_and_only_opts_into_github_publication():
    release = workflow("python-release.yml")
    assert set(release["on"]) == {"workflow_dispatch"}
    assert release["permissions"] == {"contents": "read"}
    assert release["jobs"]["full"]["with"]["require_verified_core"] == "true"
    assert release["jobs"]["full"]["needs"] == "preflight"
    assert set(release["jobs"]["assemble"]["needs"]) == {"preflight", "full"}
    assert any(step.get("uses", "").startswith("actions/attest-build-provenance@")
               for step in release["jobs"]["assemble"]["steps"])
    assert release["on"]["workflow_dispatch"]["inputs"]["publish_release"]["default"] == "false"
    assert release["jobs"]["publish"]["if"] == "inputs.publish_release"
    assert set(release["jobs"]["publish"]["needs"]) == {"full", "assemble"}
    assert release["jobs"]["publish"]["permissions"]["contents"] == "write"
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        text = path.read_text()
        assert "pypa/gh-action-pypi-publish" not in text
        assert "twine upload" not in text
        assert "gh release create" not in text
        if path.name != "python-release.yml":
            assert "contents: write" not in text


def test_frozen_migration_inventory_and_existing_suite_are_unchanged():
    import hashlib
    inventory = read(ROOT / "docs/migration/source-inventory.json")
    for entry in inventory["files"]:
        path = entry["destination"]
        if path.startswith(("bindings/python/opentlv/tests/", "bindings/python/opentlv/examples/")):
            path = path.replace("bindings/python/opentlv/tests/", "tests/python/").replace(
                "bindings/python/opentlv/examples/", "examples/")
            assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == entry["sha256"]


def test_ci_evidence_covers_relocated_inputs():
    from ci_contract import definition_hashes
    definitions = definition_hashes()
    assert not any(path.startswith("bindings/") for path in definitions)
    for directory, pattern in (("src", "*.py"), ("native", "*.c"), ("native", "*.h"),
                               ("tests/python", "*.py"), ("examples", "*.py")):
        paths = list((ROOT / directory).rglob(pattern))
        assert paths
        assert all(path.relative_to(ROOT).as_posix() in definitions for path in paths)
    assert "src/pyproject.toml" in definitions
    assert "native/CMakeLists.txt" in definitions
