# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Package index uploads require the exact verified candidate, its tag state and immutable index files."""

import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from urllib.error import HTTPError

from build_support import read, write
import package_contract as packages
import publish_pypi as pypi
import release
from test_gate import IDENTITY
from test_packages import release_fixture


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    evidence, quality, assembled = release_fixture(tmp_path, monkeypatch)
    release.assemble(evidence, quality, assembled, "v0.1.0")
    # download-artifact places each attempt's candidate in a directory named after its artifact.
    output = tmp_path / "candidates" / ("python-release-candidate-" + IDENTITY["run_attempt"])
    output.parent.mkdir()
    shutil.move(assembled, output)
    manifest = read(output / "manifest.json")
    calls = {"unused_tag": 0, "verify_published": 0, "producer": []}
    monkeypatch.setattr(pypi, "trusted_dispatch", lambda tag: (IDENTITY, packages.policy(), manifest["core_lock"]))
    # verify_candidate's manifest, checksum, attestation and producer checks are covered with the GitHub publisher.
    def verify_candidate(directory, tag, producer, package, pinned, latest):
        calls["producer"].append((directory.name, producer["run_attempt"], latest))
        return read(directory / "manifest.json")
    monkeypatch.setattr(pypi, "verify_candidate", verify_candidate)
    monkeypatch.setattr(pypi, "unused_tag", lambda tag: calls.__setitem__("unused_tag", calls["unused_tag"] + 1))
    monkeypatch.setattr(pypi, "verify_published",
                        lambda *args: calls.__setitem__("verify_published", calls["verify_published"] + 1))
    monkeypatch.setattr(pypi, "api", lambda path: [{"id": 7, "tag_name": "v0.1.0"}] if "?" in path else {"id": 7})
    monkeypatch.setattr(pypi, "WORK", tmp_path / "pypi")
    index = {}
    monkeypatch.setattr(pypi, "index_files", lambda name, version: dict(index))
    for key, value in {"GITHUB_WORKFLOW_REF": pypi.REPOSITORY + "/" + pypi.WORKFLOW + "@refs/heads/main",
                       "FULL_RESULT": "success", "ASSEMBLE_RESULT": "success", "PUBLISH_RESULT": "skipped",
                       "GITHUB_OUTPUT": str(tmp_path / "github-output")}.items():
        monkeypatch.setenv(key, value)
    return output, manifest, index, calls, tmp_path


def outputs(tmp_path):
    return dict(line.split("=", 1) for line in (tmp_path / "github-output").read_text().splitlines())


def test_testpypi_rehearsal_uploads_the_complete_selected_set(candidate):
    output, manifest, _, calls, tmp_path = candidate
    pypi.prepare(output.parent, "v0.1.0", "testpypi")
    uploaded = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (pypi.WORK / "upload").iterdir()}
    assert uploaded == {name: item["sha256"] for name, item in manifest["distributions"].items()}
    assert len(uploaded) == 4 and sum(name.endswith(".whl") for name in uploaded) == 3
    assert outputs(tmp_path) == {"upload": "true", "repository_url": "https://test.pypi.org/legacy/"}
    assert calls == {"unused_tag": 1, "verify_published": 0, "producer": [("python-release-candidate-2", "2", "2")]}
    assert read(pypi.WORK / "plan.json")["manifest"] == IDENTITY


def test_pypi_requires_the_github_release_of_this_run(candidate, monkeypatch):
    output, _, _, calls, tmp_path = candidate
    with pytest.raises(ValueError, match="GitHub release"):
        pypi.prepare(output.parent, "v0.1.0", "pypi")
    assert not pypi.WORK.exists()
    monkeypatch.setenv("PUBLISH_RESULT", "success")
    pypi.prepare(output.parent, "v0.1.0", "pypi")
    assert calls["unused_tag"] == 0 and calls["verify_published"] == 1
    assert outputs(tmp_path)["repository_url"] == "https://upload.pypi.org/legacy/"


@pytest.mark.parametrize("key,value", [("FULL_RESULT", "failure"), ("ASSEMBLE_RESULT", "skipped"),
                                       ("PUBLISH_RESULT", "failure"), ("PUBLISH_RESULT", "cancelled"),
                                       ("GITHUB_WORKFLOW_REF", "fork/opentlv-python/.github/workflows/x.yml@refs/heads/main")])
def test_failed_gate_or_foreign_workflow_never_prepares_an_upload(candidate, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        pypi.prepare(candidate[0].parent, "v0.1.0", "testpypi")
    assert not pypi.WORK.exists()


@pytest.mark.parametrize("present", [1, 4])
def test_retry_uploads_only_missing_files_with_identical_bytes(candidate, present):
    output, manifest, index, _, tmp_path = candidate
    names = sorted(manifest["distributions"])
    index.update({name: manifest["distributions"][name]["sha256"] for name in names[:present]})
    pypi.prepare(output.parent, "v0.1.0", "testpypi")
    assert sorted(path.name for path in (pypi.WORK / "upload").iterdir()) == names[present:]
    assert outputs(tmp_path)["upload"] == ("true" if present < 4 else "false")


@pytest.mark.parametrize("change", ["bytes", "extra"])
def test_index_with_other_files_for_the_version_is_never_overwritten(candidate, change):
    output, manifest, index, _, _ = candidate
    name = sorted(manifest["distributions"])[0]
    if change == "bytes":
        index[name] = "0" * 64
    else:
        index["opentlv-0.1.0-cp311-abi3-manylinux_2_17_x86_64.whl"] = "1" * 64
    with pytest.raises(ValueError, match="new version"):
        pypi.prepare(output.parent, "v0.1.0", "testpypi")
    assert not (pypi.WORK / "upload").exists()


def rewrite_candidate(output, change):
    archive_path = next(output.glob("*.zip"))
    with zipfile.ZipFile(archive_path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    change(contents)
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, content in contents.items():
            archive.writestr(name, content)


@pytest.mark.parametrize("mutation,message", [
    ("dist-bytes", "tested build"), ("source-bytes", "tested build"), ("missing-platform", "upload set"),
    ("foreign-record", "build record"), ("wheel-contract", "native _opentlv")])
def test_candidate_upload_set_is_rechecked_before_upload(candidate, mutation, message):
    output, manifest, _, _, _ = candidate
    name = packages.wheel_name(packages.policy(), "Linux")
    item = manifest["distributions"][name]
    if mutation == "dist-bytes":
        rewrite_candidate(output, lambda contents: contents.__setitem__("dist/" + name, b"changed"))
    elif mutation == "source-bytes":
        rewrite_candidate(output, lambda contents: contents.__setitem__(item["source"], b"changed"))
    elif mutation == "missing-platform":
        del manifest["distributions"][name]
        write(output / "manifest.json", manifest)
    elif mutation == "foreign-record":
        record = read(output.parent.parent / "evidence/windows-3.11/record.json")
        rewrite_candidate(output, lambda contents: contents.__setitem__(
            "linux-3.11/record.json", json.dumps(record).encode()))
    else:
        # A wheel whose bytes match the manifest but violate the contract still cannot be uploaded.
        work = output.parent.parent / "broken"
        with zipfile.ZipFile(output.parent.parent / "evidence/linux-3.11/ci/wheels" / name) as archive:
            contents = {entry: archive.read(entry) for entry in archive.namelist()}
        contents.pop("_opentlv.abi3.so")
        work.mkdir()
        with zipfile.ZipFile(work / name, "w") as archive:
            for entry, content in contents.items():
                archive.writestr(entry, content)
        data = (work / name).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        rewrite_candidate(output, lambda contents: contents.update({"dist/" + name: data, item["source"]: data}))
        item["sha256"] = manifest["files"]["dist/" + name] = manifest["files"][item["source"]] = sha
        write(output / "manifest.json", manifest)
    with pytest.raises(ValueError, match=message):
        pypi.prepare(output.parent, "v0.1.0", "testpypi")
    assert not (pypi.WORK / "upload").exists()


def test_confirm_waits_for_the_index_and_records_a_receipt(candidate, monkeypatch):
    output, manifest, index, _, _ = candidate
    pypi.prepare(output.parent, "v0.1.0", "testpypi")
    files = {name: item["sha256"] for name, item in manifest["distributions"].items()}
    responses = [{}, dict(list(files.items())[:2]), files]
    monkeypatch.setattr(pypi, "index_files", lambda *args: responses.pop(0))
    pypi.confirm("testpypi", delay=0)
    receipt = read(pypi.WORK / "receipt.json")
    assert receipt["files"] == files and receipt["index"] == "testpypi" and receipt["tag"] == "v0.1.0"
    assert receipt["run_attempt"] == int(IDENTITY["run_attempt"]) and receipt["commit"] == IDENTITY["commit"]


@pytest.mark.parametrize("listed,message", [("partial", "complete upload set"), ("different", "differ")])
def test_confirm_rejects_incomplete_or_different_index_files(candidate, monkeypatch, listed, message):
    output, manifest, _, _, _ = candidate
    pypi.prepare(output.parent, "v0.1.0", "testpypi")
    files = {name: item["sha256"] for name, item in manifest["distributions"].items()}
    shown = dict(list(files.items())[:3]) if listed == "partial" else {**files, next(iter(files)): "0" * 64}
    monkeypatch.setattr(pypi, "index_files", lambda *args: shown)
    with pytest.raises(ValueError, match=message):
        pypi.confirm("testpypi", attempts=2, delay=0)
    assert not (pypi.WORK / "receipt.json").exists()
    with pytest.raises(ValueError, match="differs from the plan"):
        pypi.confirm("pypi", delay=0)


@pytest.mark.parametrize("index,publish,message", [
    ("none", "false", None), ("testpypi", "false", None), ("pypi", "true", None),
    ("pypi", "false", "publish_release"), ("pypi", "", "publish_release"), ("other", "true", "Unknown")])
def test_preflight_rejects_a_pypi_upload_that_could_never_run(monkeypatch, index, publish, message):
    monkeypatch.setenv("PYPI_TARGET", index)
    monkeypatch.setenv("PUBLISH_RELEASE", publish)
    if message is None:
        release.requested_publication()
    else:
        with pytest.raises(ValueError, match=message):
            release.requested_publication()


@pytest.mark.parametrize("value", ["", "none", "pypi.org", "PyPI"])
def test_publisher_requires_an_explicit_index(monkeypatch, value):
    monkeypatch.setenv("PYPI_TARGET", value)
    with pytest.raises(ValueError, match="package index"):
        pypi.requested_index()


def test_index_files_reads_the_version_json_and_treats_404_as_unpublished(monkeypatch):
    requested = []

    def urlopen(url, timeout):
        requested.append(url)
        if "/9.9.9/" in url:
            raise HTTPError(url, 404, "Not Found", {}, None)
        return io.BytesIO(json.dumps({"urls": [
            {"filename": "opentlv-0.1.0.tar.gz", "digests": {"sha256": "a" * 64}}]}).encode())
    monkeypatch.setattr(pypi, "urlopen", urlopen)
    assert pypi.index_files("testpypi", "0.1.0") == {"opentlv-0.1.0.tar.gz": "a" * 64}
    assert pypi.index_files("pypi", "9.9.9") == {}
    assert requested == ["https://test.pypi.org/pypi/opentlv/0.1.0/json", "https://pypi.org/pypi/opentlv/9.9.9/json"]


def test_rerun_of_failed_jobs_uploads_the_earlier_attempts_candidate(candidate, monkeypatch):
    output, _, _, calls, _ = candidate
    # Attempt 3 re-runs only the failed upload job; attempt 2's attested candidate is reused.
    monkeypatch.setattr(pypi, "trusted_dispatch", lambda tag: (
        {**IDENTITY, "run_attempt": "3"}, packages.policy(), read(output / "manifest.json")["core_lock"]))
    pypi.prepare(output.parent, "v0.1.0", "testpypi")
    assert calls["producer"] == [("python-release-candidate-2", "2", "3")]


def test_newest_candidate_of_the_run_is_selected(candidate, monkeypatch):
    output, _, _, calls, _ = candidate
    newer = output.parent / "python-release-candidate-3"
    shutil.copytree(output, newer)
    manifest = read(newer / "manifest.json")
    manifest["identity"]["run_attempt"] = "3"
    write(newer / "manifest.json", manifest)
    monkeypatch.setattr(pypi, "trusted_dispatch", lambda tag: (
        {**IDENTITY, "run_attempt": "3"}, packages.policy(), manifest["core_lock"]))
    pypi.prepare(output.parent, "v0.1.0", "testpypi")
    assert calls["producer"] == [("python-release-candidate-3", "3", "3")]


@pytest.mark.parametrize("change", ["run", "future-attempt", "directory", "missing"])
def test_candidate_from_another_run_or_attempt_is_rejected(candidate, change):
    output = candidate[0]
    manifest = read(output / "manifest.json")
    if change == "run":
        manifest["identity"]["run_id"] = "99"
    elif change == "future-attempt":
        manifest["identity"]["run_attempt"] = "3"
        output = output.rename(output.with_name("python-release-candidate-3"))
    elif change == "directory":
        output = output.rename(output.with_name("python-release-candidate-1"))
    else:
        shutil.rmtree(output)
    if output.exists():
        write(output / "manifest.json", manifest)
    with pytest.raises(ValueError, match="this run|Missing release candidate"):
        pypi.prepare(candidate[0].parent, "v0.1.0", "testpypi")
    assert not pypi.WORK.exists()
