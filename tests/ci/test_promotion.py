# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""PyPI receives only the attested bytes that an earlier run staged and installed from TestPyPI."""

import argparse
import copy
from pathlib import Path
import platform
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from build_support import read, write
import ci
import ci_contract as contract
import package_contract as packages
from package_contract import DISTRIBUTION
import publish_release
import release
from test_gate import IDENTITY
from test_packages import PREFIX, metadata, release_fixture, write_sdist

STAGING_RUN = IDENTITY["run_id"]
CURRENT = {**IDENTITY, "run_id": "200", "run_attempt": "1"}
SDIST = PREFIX + ".tar.gz"


def suite():
    policy = read(ci.ROOT / "cmake/ci-matrix.json")
    return {"smoke": True, "package_versions": {DISTRIBUTION: packages.policy()["version"]},
            "tests": {"tests": policy["pytest_cases"], "failures": 0, "errors": 0, "skipped": 0},
            "examples": policy["examples"],
            "query": {"fixtures": policy["query_fixtures"], "checks": policy["query_checks"]}}


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """A successful staging run's downloaded artifacts, and the promotion run's view of them."""
    evidence, verification, quality, assembled = release_fixture(tmp_path, monkeypatch)
    release.assemble(evidence, verification, quality, assembled, "v0.1.0")
    root = tmp_path / "candidates"
    root.mkdir()
    shutil.move(assembled, root / ("python-release-candidate-" + IDENTITY["run_attempt"]))
    directory = root / ("python-release-candidate-" + IDENTITY["run_attempt"])
    manifest = read(directory / "manifest.json")
    files = {name: item["sha256"] for name, item in manifest["distributions"].items()}
    write(root / "python-package-index-testpypi-2/receipt.json", {
        "schema": 1, "kind": "python-package-index-release", "index": "testpypi",
        "repository": publish_release.REPOSITORY, "project": "https://test.pypi.org/project/opentlv/0.1.0/",
        "tag": "v0.1.0", "version": "0.1.0", "commit": IDENTITY["commit"], "run_id": int(STAGING_RUN),
        "run_attempt": int(IDENTITY["run_attempt"]), "files": files})
    core = read(evidence / "linux-3.11/record.json")["core"]
    for item in contract.matrix("full"):
        wheel = packages.wheel_name(packages.policy(), item["system"])
        write(root / f'python-index-install-testpypi-{item["id"]}-2/indexed.json', {
            "schema": 1, "kind": "index-installation", "index": "testpypi", "tier": "full", "status": "success",
            "identity": copy.deepcopy(IDENTITY), "definitions": manifest["definitions"], "configuration": item,
            "require_release": True, "runtime": {"system": item["system"], "python": item["python"] + ".1"},
            "files": files, "installed": {wheel: files[wheel]}, "core": core, **suite()})
    producer = {"status": "completed", "conclusion": "success", "event": "workflow_dispatch", "head_branch": "main",
                "head_sha": IDENTITY["commit"], "path": publish_release.WORKFLOW, "run_attempt": 2,
                "head_repository": {"full_name": publish_release.REPOSITORY}}
    monkeypatch.setattr(release, "api", lambda path: producer)
    monkeypatch.setattr(publish_release, "definition_hashes", lambda: manifest["definitions"])
    commands = []
    monkeypatch.setattr(publish_release, "run", lambda *args, **kwargs: commands.append(args))
    listed = dict(files)
    monkeypatch.setattr(publish_release, "index_files", lambda index, version: dict(listed))
    monkeypatch.setenv("CANDIDATE_RUN", STAGING_RUN)
    return root, directory, manifest, producer, commands, listed


def promote(root, manifest):
    return publish_release.staged_candidate(root, "v0.1.0", CURRENT, packages.policy(), manifest["core_lock"])


def test_promotion_returns_the_staged_candidate_of_the_earlier_run(staged):
    root, directory, manifest, _, commands, _ = staged
    assert promote(root, manifest) == (directory, manifest, IDENTITY)
    # All three candidate files are authenticated against the signer and the same commit.
    assert sum(command[:3] == ("gh", "attestation", "verify") for command in commands) == 3
    assert all(command[-1] == IDENTITY["commit"] for command in commands)


def test_github_publication_of_a_promotion_needs_no_build_in_this_run(staged, monkeypatch):
    root, directory, manifest, _, _, _ = staged
    package = packages.policy()
    monkeypatch.setattr(publish_release, "preflight", lambda tag: (CURRENT, package, manifest["core_lock"]))
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", f"{publish_release.REPOSITORY}/{publish_release.WORKFLOW}@refs/heads/main")
    monkeypatch.setenv("PUBLISH_RELEASE", "true")
    monkeypatch.setenv("FULL_RESULT", "skipped")
    monkeypatch.setenv("ASSEMBLE_RESULT", "skipped")
    assert publish_release.verify(root, "v0.1.0") == (CURRENT, package, directory)
    monkeypatch.setenv("PUBLISH_RELEASE", "false")
    with pytest.raises(ValueError, match="opt-in"):
        publish_release.verify(root, "v0.1.0")


def receipt_path(root):
    return root / "python-package-index-testpypi-2/receipt.json"


@pytest.mark.parametrize("field,value", [
    ("index", "pypi"), ("tag", "v0.2.0"), ("version", "0.2.0"), ("commit", "b" * 40), ("run_id", 99),
    ("repository", "fork/opentlv-python"), ("kind", "other"), ("schema", 2)])
def test_promotion_rejects_a_receipt_of_something_else(staged, field, value):
    root, _, manifest, _, _, _ = staged
    receipt = read(receipt_path(root))
    receipt[field] = value
    write(receipt_path(root), receipt)
    with pytest.raises(ValueError, match="receipt differs from this promotion"):
        promote(root, manifest)


def test_promotion_rejects_missing_contradictory_or_other_receipts(staged):
    root, _, manifest, _, _, _ = staged
    receipt = read(receipt_path(root))
    # A re-run of the upload job records the same candidate again.
    write(root / "python-package-index-testpypi-3/receipt.json", receipt)
    assert promote(root, manifest)[0].name == "python-release-candidate-2"
    write(root / "python-package-index-testpypi-3/receipt.json", {**receipt, "run_attempt": 1})
    with pytest.raises(ValueError, match="contradictory"):
        promote(root, manifest)
    shutil.rmtree(root / "python-package-index-testpypi-3")
    write(receipt_path(root), {**receipt, "files": {**receipt["files"], SDIST: "0" * 64}})
    with pytest.raises(ValueError, match="differs from the staged candidate"):
        promote(root, manifest)
    write(receipt_path(root), {**receipt, "run_attempt": 1})
    with pytest.raises(ValueError, match="Missing staged release candidate"):
        promote(root, manifest)
    shutil.rmtree(receipt_path(root).parent)
    with pytest.raises(ValueError, match="Missing or contradictory"):
        promote(root, manifest)


def test_promotion_requires_an_earlier_run(staged, monkeypatch):
    root, _, manifest, _, _, _ = staged
    monkeypatch.setenv("CANDIDATE_RUN", CURRENT["run_id"])
    with pytest.raises(ValueError, match="earlier staging run"):
        promote(root, manifest)
    monkeypatch.delenv("CANDIDATE_RUN")
    with pytest.raises(ValueError, match="earlier staging run"):
        promote(root, manifest)


@pytest.mark.parametrize("change", [
    {"conclusion": "failure"}, {"conclusion": None, "status": "in_progress"}, {"head_sha": "b" * 40},
    {"event": "push"}, {"head_branch": "feature"}, {"path": ".github/workflows/other.yml"},
    {"head_repository": {"full_name": "fork/opentlv-python"}}])
def test_promotion_requires_a_successful_run_of_this_commit_and_workflow(staged, change):
    root, _, manifest, producer, _, _ = staged
    producer.update(change)
    with pytest.raises(ValueError, match="not a successful release run"):
        promote(root, manifest)


def test_promotion_authenticates_the_candidate(staged, monkeypatch):
    root, directory, manifest, _, _, _ = staged

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(publish_release, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        promote(root, manifest)
    monkeypatch.setattr(publish_release, "run", lambda *args, **kwargs: None)
    # Another commit's candidate, or changed definitions, differ from this dispatch.
    with pytest.raises(ValueError, match="receipt differs"):
        publish_release.staged_candidate(root, "v0.1.0", {**CURRENT, "commit": "b" * 40}, packages.policy(),
                                         manifest["core_lock"])
    monkeypatch.setattr(publish_release, "definition_hashes", lambda: {"changed": "0" * 64})
    with pytest.raises(ValueError, match="Candidate identity"):
        promote(root, manifest)
    monkeypatch.setattr(publish_release, "definition_hashes", lambda: manifest["definitions"])
    (directory / f'opentlv-python-{packages.policy()["version"]}.zip').write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksums"):
        promote(root, manifest)


@pytest.mark.parametrize("path,value,message", [
    (("status",), "failed", "Unsuccessful"), (("kind",), "upload-verification", "Unsuccessful"),
    (("index",), "pypi", "Unsuccessful"), (("identity", "commit"), "b" * 40, "commit"),
    (("identity", "run_id"), "99", "run"), (("identity", "dirty"), True, "repository"),
    (("definitions",), {"x": "0" * 64}, "definitions"), (("runtime", "python"), "3.9.1", "Runtime"),
    (("require_release",), False, "Release policy"), (("files", SDIST), "0" * 64, "staged set"),
    (("installed",), {SDIST: "0" * 64}, "staged wheel"), (("core", "commit"), "f" * 40, "Core"),
    (("smoke",), False, "smoke"), (("package_versions", "opentlv-core"), "0.1.0", "smoke"),
    (("tests", "tests"), 1, "test suite"), (("examples",), 1, "examples"), (("query", "checks"), 1, "Query")])
def test_promotion_rejects_incomplete_or_foreign_installations(staged, path, value, message):
    root, _, manifest, _, _, _ = staged
    record_path = root / "python-index-install-testpypi-macos-3.13-2/indexed.json"
    record = read(record_path)
    target = record
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    write(record_path, record)
    with pytest.raises(ValueError, match=message):
        promote(root, manifest)


def test_promotion_requires_every_configuration_and_accepts_a_rerun(staged):
    root, _, manifest, _, _, _ = staged
    directory = root / "python-index-install-testpypi-windows-3.15-2"
    record = read(directory / "indexed.json")
    shutil.rmtree(directory)
    with pytest.raises(ValueError, match="Missing package index installation"):
        promote(root, manifest)
    # A failed job re-run in a later attempt of the same run.
    record["identity"]["run_attempt"] = "3"
    write(root / "python-index-install-testpypi-windows-3.15-3/indexed.json", record)
    assert promote(root, manifest)[1] == manifest


def test_promotion_rejects_files_no_longer_on_testpypi(staged):
    root, _, manifest, _, _, listed = staged
    del listed[SDIST]
    with pytest.raises(ValueError, match="no longer lists"):
        promote(root, manifest)


def current_configuration():
    system = {"Linux": "linux", "Windows": "windows", "Darwin": "macos"}[platform.system()]
    name = f"{system}-{sys.version_info.major}.{sys.version_info.minor}"
    configurations = {item["id"]: item for item in contract.matrix("full")}
    if name not in configurations:
        pytest.skip("This interpreter is outside the Full matrix")
    return configurations[name]


@pytest.fixture
def index(tmp_path, monkeypatch):
    """A confirmed upload's receipt and an index that serves its files, with pip and the suite stubbed."""
    configuration = current_configuration()
    value = packages.policy()
    wheel = packages.wheel_name(value, configuration["system"])
    sdist = tmp_path / SDIST
    write_sdist(sdist, {PREFIX + "/PKG-INFO": metadata(value),
                        **{PREFIX + "/" + path: (ci.ROOT / path).read_bytes() for path in packages.sdist_inputs()}})
    files = {name: "c" * 64 for name in packages.upload_names(value)}
    files[SDIST] = ci.digest(sdist)
    pinned = contract.lock(True)
    core = {key: pinned[key] for key in ("repository", "commit", "version", "release_tag")} | {
        "mode": "verified-source", "verified": True, "release_id": 1, "manifest_sha256": "f" * 64}
    write(tmp_path / "receipts/python-package-index-testpypi-2/receipt.json", {
        "schema": 1, "kind": "python-package-index-release", "index": "testpypi", "repository": IDENTITY["repository"],
        "tag": "v0.1.0", "version": value["version"], "commit": IDENTITY["commit"], "run_id": 100, "run_attempt": 2,
        "files": files})
    monkeypatch.setattr(ci, "identity", lambda: copy.deepcopy(IDENTITY))
    monkeypatch.setattr(ci, "definition_hashes", lambda: {"scripts/ci.py": "b" * 64})
    monkeypatch.setattr(ci, "core_corpus", lambda work, selected: tmp_path / "corpus")
    monkeypatch.setattr(ci, "index_release", lambda name, version: {"urls": [
        {"filename": SDIST, "url": "https://test-files.pythonhosted.org/" + SDIST}]})
    monkeypatch.setattr(ci, "download", lambda url, path: shutil.copyfile(sdist, path))
    host = {"value": "test-files.pythonhosted.org", "sha": files[wheel], "failures": 0}
    commands = []

    def run(*args, **kwargs):
        command = [str(item) for item in args]
        commands.append(command)
        if "--report" in command:
            if host["failures"]:
                host["failures"] -= 1
                raise subprocess.CalledProcessError(1, command)
            write(Path(command[command.index("--report") + 1]), {"install": [{
                "metadata": {"name": DISTRIBUTION},
                "download_info": {"url": f'https://{host["value"]}/packages/{wheel}',
                                  "archive_info": {"hashes": {"sha256": host["sha"]}}}}]})
            environment = Path(command[command.index("--python") + 1]).parents[1]
            write(environment / "Lib/site-packages/_opentlv_core_dependency.json", core)
        elif any(item.endswith("check_python.py") for item in command):
            policy = read(ci.ROOT / "cmake/ci-matrix.json")
            Path(command[command.index("--junit") + 1]).write_text('<testsuite tests="%d">%s</testsuite>' % (
                policy["pytest_cases"], "<testcase/>" * policy["pytest_cases"]))
            write(Path(command[command.index("--output") + 1]), suite())
    monkeypatch.setattr(ci, "run", run)
    monkeypatch.setattr(ci, "INDEX_DELAY", 0)
    args = argparse.Namespace(index="testpypi", configuration=configuration["id"], receipts=tmp_path / "receipts",
                              work=tmp_path / "index", output=tmp_path / "indexed.json")
    return args, files, wheel, host, commands, core


def test_index_install_uses_the_index_alone_and_the_published_hash(tmp_path, index):
    args, files, wheel, _, commands, core = index
    ci.index_install(args)
    install = next(command for command in commands if "--report" in command)
    assert install[install.index("--index-url") + 1] == "https://test.pypi.org/simple/"
    assert install[install.index("--only-binary") + 1] == ":all:"
    assert {"--require-hashes", "--no-cache-dir"} <= set(install)
    assert not {"--extra-index-url", "--find-links", "--no-index"} & set(install)
    assert (args.work / "requirements.txt").read_text() == (
        f'{DISTRIBUTION}=={packages.policy()["version"]} --hash=sha256:{files[wheel]}\n')
    checker = next(command for command in commands if any(item.endswith("check_python.py") for item in command))
    assert checker[checker.index("--corpus") + 1] == str(tmp_path / "corpus") and "--smoke" not in checker
    record = read(args.output)
    assert record["kind"] == "index-installation" and record["index"] == "testpypi"
    assert record["files"] == files and record["installed"] == {wheel: files[wheel]}
    assert record["core"] == core and record["require_release"] is True and record["status"] == "success"


def test_index_install_waits_for_the_index_and_then_fails(index):
    args, _, _, host, commands, _ = index
    host["failures"] = 2
    ci.index_install(args)
    assert sum("--report" in command for command in commands) == 3
    host["failures"] = ci.INDEX_ATTEMPTS
    args.work = args.work.with_name("again")
    with pytest.raises(subprocess.CalledProcessError):
        ci.index_install(args)
    assert not args.output.exists()


@pytest.mark.parametrize("field,value,message", [
    ("sha", "0" * 64, "another archive"), ("value", "files.pythonhosted.org", "another host")])
def test_index_install_rejects_other_bytes_or_hosts(index, field, value, message):
    args, _, _, host, _, _ = index
    host[field] = value
    with pytest.raises(ValueError, match=message):
        ci.index_install(args)
    assert not args.output.exists()


def test_index_install_rejects_another_served_sdist(index, monkeypatch):
    args = index[0]
    monkeypatch.setattr(ci, "download", lambda url, path: path.write_bytes(b"other"))
    with pytest.raises(ValueError, match="another sdist"):
        ci.index_install(args)
    assert not args.output.exists()


@pytest.mark.parametrize("field,value", [("index", "pypi"), ("commit", "b" * 40), ("version", "0.2.0"),
                                         ("repository", "fork/opentlv-python"), ("files", {})])
def test_index_install_rejects_a_receipt_of_something_else(index, field, value):
    args = index[0]
    path = args.receipts / "python-package-index-testpypi-2/receipt.json"
    write(path, {**read(path), field: value})
    with pytest.raises(ValueError, match="receipt differs"):
        ci.index_install(args)


def test_index_install_requires_one_receipt_content(index):
    args = index[0]
    path = args.receipts / "python-package-index-testpypi-2/receipt.json"
    receipt = read(path)
    write(args.receipts / "python-package-index-testpypi-3/receipt.json", {**receipt, "run_attempt": 1})
    with pytest.raises(ValueError, match="contradictory"):
        ci.index_install(args)
    shutil.rmtree(args.receipts)
    args.receipts.mkdir()
    args.work = args.work.with_name("again")
    with pytest.raises(ValueError, match="Missing"):
        ci.index_install(args)
