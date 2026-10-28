# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Dependency failures must stop before compiling or executing Core build files."""

import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from unittest.mock import Mock
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import core_dependency as dependency
import verified_core as verified
from build_support import digest, write

PIN = verified.lock()
COMMIT = PIN["commit"]
VERSION = PIN["version"]


@pytest.fixture
def release_lock():
    return {**PIN, "release_tag": "v" + VERSION}


@pytest.fixture
def null_lock(monkeypatch):
    """Select the locked commit through pinned Git, as a lock without a release tag does."""
    monkeypatch.setattr(verified, "read", lambda _: {**PIN, "release_tag": None})


@pytest.fixture
def probe():
    return {"COMPILER_ID": "MSVC", "COMPILER_VERSION": "19.44", "SIZEOF_DATA_PTR": "8",
            "SYSTEM": "Windows", "COMPILER_ARCHITECTURE": "x64", "PROCESSOR": "AMD64",
            "CROSS_COMPILING": "FALSE"}


@pytest.fixture
def binary():
    return {"kind": "binary", "id": "windows-x64-static", "architecture": "x64",
            "os": "windows", "build_type": "Release", "linkage": "static",
            "compiler": {"CMAKE_C_COMPILER_ID": "MSVC", "CMAKE_C_COMPILER_VERSION": "19.44"},
            "msvc_runtime": "MultiThreadedDLL",
            "options": dict.fromkeys(verified.REQUIRED_FEATURES, "ON")}


@pytest.fixture
def manifest(release_lock):
    definition = "fixture workflow\n"
    definition_hash = hashlib.sha256(definition.encode()).hexdigest()
    return {"schema": 2, "version": VERSION, "commit": COMMIT,
            "candidate": {"version": VERSION, "tag": release_lock["release_tag"], "commit": COMMIT,
                          "repository": verified.REPOSITORY, "run_id": "123", "run_attempt": "2"},
            "quality": {"schema": 2, "tier": "full", "repository": verified.REPOSITORY,
                        "commit": COMMIT, "run_id": "123", "run_attempt": "2",
                        "configuration": {
                            "inputs": {"full": True, "release_tag": release_lock["release_tag"]},
                            "configuration_sources": dict.fromkeys(verified.CONFIGURATION_SOURCES, definition_hash),
                            "workflows": {name: {"sha256": definition_hash, "definition": definition}
                                          for name in verified.WORKFLOWS}},
                        "checks": dict.fromkeys(verified.FULL_CHECKS, "success")},
            "artifacts": [{"kind": "source", "filename": "source.tar.gz", "sha256": "a" * 64,
                           "version": VERSION, "commit": COMMIT}]}


def test_committed_lock_selects_core_080():
    selected = verified.lock(True)
    assert selected["version"] == "0.8.0" and selected["release_tag"] == "v0.8.0"
    assert selected["commit"] == "345c77acb29266036df5f27d04ce315bb61853cc"
    assert selected["allow_verified_source"] is True


def test_null_lock_cannot_require_release(null_lock):
    with pytest.raises(ValueError, match="published Core"):
        verified.lock(True)


@pytest.mark.parametrize("field,value", [("commit", "main"), ("commit", "abc1234"),
                                       ("version", None), ("release_tag", "v9.0.0"),
                                       ("allow_verified_source", "yes")])
def test_invalid_lock(monkeypatch, field, value):
    monkeypatch.setattr(verified, "read", lambda _: {**PIN, field: value})
    with pytest.raises(ValueError):
        verified.lock()


@pytest.mark.parametrize("variable", ["CI", "GITHUB_ACTIONS"])
def test_ci_rejects_local_override(monkeypatch, tmp_path, variable):
    monkeypatch.setenv(variable, "true")
    with pytest.raises(ValueError, match="development-only"):
        dependency.select(tmp_path, {}, "Release", tmp_path)


def test_local_identity_is_recorded(monkeypatch, tmp_path):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(dependency, "git_identity",
                        lambda _: {"commit": "b" * 40, "version": "0.8.0", "dirty": True})
    result = dependency.select(tmp_path, {}, "Release", tmp_path)
    assert result["mode"] == "local-source" and not result["verified"]
    assert result["commit"] == "b" * 40 and result["dirty"]
    assert result["locked_commit"] == COMMIT


@pytest.mark.parametrize("field,value", [("commit", "b" * 40), ("version", "0.0.0"), ("dirty", True)])
def test_pinned_source_mismatch(monkeypatch, tmp_path, null_lock, field, value):
    (tmp_path / "source").mkdir()
    identity = {"commit": COMMIT, "version": VERSION, "dirty": False, field: value}
    monkeypatch.setattr(dependency, "git_identity", lambda _: identity)
    with pytest.raises(ValueError):
        dependency.select(tmp_path, {}, "Release")


def test_pinned_source_positive(monkeypatch, tmp_path, null_lock):
    (tmp_path / "source").mkdir()
    monkeypatch.setattr(dependency, "git_identity",
                        lambda _: {"commit": COMMIT, "version": VERSION, "dirty": False})
    result = dependency.select(tmp_path, {}, "Release")
    assert result["mode"] == "pinned-git" and not result["verified"]


def test_unavailable_commit_stops(monkeypatch, tmp_path, null_lock):
    command = Mock(side_effect=subprocess.CalledProcessError(128, ["git", "clone"]))
    monkeypatch.setattr(dependency, "run", command)
    with pytest.raises(subprocess.CalledProcessError):
        dependency.select(tmp_path, {}, "Release")
    assert command.call_count == 1


def test_failed_attestation_never_falls_back(monkeypatch, tmp_path, release_lock):
    monkeypatch.setattr(dependency, "lock", lambda _: release_lock)
    monkeypatch.setattr(dependency, "resolve", Mock(side_effect=ValueError("attestation failed")))
    git = Mock()
    monkeypatch.setattr(dependency, "run", git)
    with pytest.raises(ValueError, match="attestation"):
        dependency.select(tmp_path, {}, "Release")
    git.assert_not_called()


def test_committed_lock_resolves_release_artifacts(monkeypatch, tmp_path):
    resolve = Mock(return_value={"mode": "verified-source", "verified": True})
    monkeypatch.setattr(dependency, "resolve", resolve)
    git = Mock()
    monkeypatch.setattr(dependency, "run", git)
    assert dependency.select(tmp_path, {}, "Release")["mode"] == "verified-source"
    resolve.assert_called_once()
    git.assert_not_called()


def test_manifest_identity(manifest, release_lock):
    verified.verify_manifest(manifest, release_lock)


@pytest.mark.parametrize("section,field,value", [
    (None, "commit", "b" * 40), (None, "version", "9.0.0"),
    ("quality", "repository", "other/repo"), ("quality", "tier", "pr"),
    ("quality", "checks", {"clang": "skipped"}), ("quality", "configuration", {}),
    ("candidate", "run_id", "999"), ("candidate", "run_attempt", "1"),
    ("candidate", "commit", "b" * 40)])
def test_manifest_rejects_mismatch(manifest, release_lock, section, field, value):
    (manifest if section is None else manifest[section])[field] = value
    with pytest.raises(ValueError):
        verified.verify_manifest(manifest, release_lock)


def test_manifest_duplicate_artifact(manifest, release_lock):
    manifest["artifacts"] *= 2
    with pytest.raises(ValueError, match="Duplicate"):
        verified.verify_manifest(manifest, release_lock)


def test_binary_compatibility(monkeypatch, binary, probe):
    monkeypatch.setattr(verified.platform, "system", lambda: "Windows")
    monkeypatch.setattr(verified.platform, "machine", lambda: "AMD64")
    assert verified.compatible(binary, probe, "OFF", "Release")
    for field, value in [("COMPILER_VERSION", "19.43"), ("SIZEOF_DATA_PTR", "4"),
                         ("COMPILER_ARCHITECTURE", "ARM64"), ("CROSS_COMPILING", "TRUE")]:
        assert not verified.compatible(binary, {**probe, field: value}, "OFF", "Release")
    assert not verified.compatible(binary, probe, "OFF", "Debug")
    assert not verified.compatible(binary, probe, "OFF", "MultiConfig")
    for feature in verified.REQUIRED_FEATURES:
        reduced = copy.deepcopy(binary)
        reduced["options"][feature] = "OFF"
        assert not verified.compatible(reduced, probe, "OFF", "Release")


def test_linux_static_requires_pic(monkeypatch, binary, probe):
    monkeypatch.setattr(verified.platform, "system", lambda: "Linux")
    monkeypatch.setattr(verified.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(verified.platform, "libc_ver", lambda: ("glibc", "2.39"))
    binary.update(id="linux-x64-static", os="linux", libc=["glibc", "2.39"])
    probe["SYSTEM"] = "Linux"
    assert not verified.compatible(binary, probe, "OFF", "Release")
    binary["position_independent_code"] = True
    assert verified.compatible(binary, probe, "OFF", "Release")


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/escape", "a\\escape"])
def test_archive_traversal(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        entry = zipfile.ZipInfo("placeholder")
        entry.filename = name  # Do not let Windows ZipInfo normalize the attack.
        stream.writestr(entry, "bad")
    with pytest.raises(ValueError):
        verified.extract(archive, tmp_path / "out")


def source_archive(tmp_path, commit=COMMIT):
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        data = f"version={VERSION}\ncommit={commit}\n".encode()
        member = tarfile.TarInfo(f"OpenTLV-{VERSION}/opentlv-source.txt")
        member.size = len(data)
        stream.addfile(member, io.BytesIO(data))
        for path in list(verified.CONFIGURATION_SOURCES) + [
                ".github/workflows/" + name for name in verified.WORKFLOWS]:
            data = b"fixture workflow\n"
            member = tarfile.TarInfo(f"OpenTLV-{VERSION}/{path}")
            member.size = len(data)
            stream.addfile(member, io.BytesIO(data))
    return archive


@pytest.mark.parametrize("failure", [None, "checksum", "identity", "fallback"])
def test_verified_source_resolution(monkeypatch, tmp_path, manifest, release_lock, probe, failure):
    archive = source_archive(tmp_path, "b" * 40 if failure == "identity" else COMMIT)
    manifest["artifacts"][0].update(sha256=digest(archive), filename=archive.name)
    sums = {archive.name: "b" * 64 if failure == "checksum" else digest(archive)}
    if failure == "fallback":
        release_lock["allow_verified_source"] = False
    monkeypatch.setattr(verified, "lock", lambda _: release_lock)
    monkeypatch.setattr(verified, "authenticated_release",
                        lambda *_: (manifest, sums, lambda _: archive, {"release_id": 1}))
    if failure:
        with pytest.raises(ValueError):
            verified.resolve(tmp_path / "work", probe, "Release")
    else:
        result = verified.resolve(tmp_path / "work", probe, "Release")
        assert result["mode"] == "verified-source" and result["verified"]
        assert Path(result["source_dir"], "opentlv-source.txt").is_file()


def test_attestation_failure_stops_before_manifest_parse(monkeypatch, tmp_path, release_lock):
    monkeypatch.setattr(verified, "api", lambda path:
                        {"sha": COMMIT} if "/commits/" in path else
                        {"draft": False, "tag_name": release_lock["release_tag"],
                         "assets": [{"name": "release-manifest.json"}]})
    calls = []

    def command(*args):
        calls.append(args)
        if args[1] == "attestation":
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(verified, "run", command)
    with pytest.raises(subprocess.CalledProcessError):
        verified.authenticated_release(tmp_path / "assets", release_lock)
    assert calls[-1][1:3] == ("attestation", "verify")
    assert calls[-1][-4:] == ("--signer-workflow", verified.SIGNER, "--source-digest", COMMIT)


def test_git_identity_uses_own_repository(tmp_path):
    with pytest.raises(ValueError, match="explicit Git"):
        dependency.git_identity(tmp_path)


def test_checksum_file_rejects_duplicates(tmp_path):
    path = tmp_path / "SHA256SUMS"
    path.write_text((("a" * 64) + "  source.tar.gz\n") * 2)
    with pytest.raises(ValueError, match="Duplicate"):
        verified.checksums(path)


def test_partial_full_gate_rejected(manifest, release_lock):
    manifest["quality"]["checks"].pop("abi")
    with pytest.raises(ValueError, match="Full CI"):
        verified.verify_manifest(manifest, release_lock)


def test_workflow_hash_rejected(manifest, release_lock):
    manifest["quality"]["configuration"]["workflows"]["core-release.yml"]["definition"] += "changed"
    with pytest.raises(ValueError, match="definition/hash"):
        verified.verify_manifest(manifest, release_lock)


def test_configuration_bound_to_source(tmp_path, manifest):
    archive = source_archive(tmp_path)
    verified.extract(archive, tmp_path / "out")
    source = tmp_path / "out" / f"OpenTLV-{VERSION}"
    verified.verify_configuration(manifest, source)
    (source / "CMakeLists.txt").write_text("different\n")
    with pytest.raises(ValueError, match="configuration source"):
        verified.verify_configuration(manifest, source)


def test_verified_binary_resolution(monkeypatch, tmp_path, manifest, release_lock, probe, binary):
    source = source_archive(tmp_path)
    archive = tmp_path / "binary.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("lib/cmake/OpenTLV/OpenTLVConfig.cmake", "# authenticated fixture\n")
    manifest["artifacts"][0].update(sha256=digest(source), filename=source.name)
    binary.update(filename=archive.name, sha256=digest(archive), version=VERSION, commit=COMMIT)
    manifest["artifacts"].append(binary)
    monkeypatch.setattr(verified, "lock", lambda _: release_lock)
    monkeypatch.setattr(verified.platform, "system", lambda: "Windows")
    monkeypatch.setattr(verified.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(verified, "authenticated_release",
                        lambda *_: (manifest, {p.name: digest(p) for p in (source, archive)},
                                    lambda name: tmp_path / name, {"release_id": 1}))
    result = verified.resolve(tmp_path / "work", probe, "Release")
    assert result["mode"] == "verified-binary" and result["verified"]
    assert Path(result["package_dir"], "OpenTLVConfig.cmake").is_file()
    assert Path(result["source_path"], "opentlv-source.txt").is_file()


def test_real_git_identity_and_dirty_state(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()
    git("init")
    (tmp_path / "CMakeLists.txt").write_text("# fixture\n")
    git("add", "CMakeLists.txt")
    git("-c", "user.name=Dependency Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-m", "fixture")
    git("-c", "user.name=Dependency Test", "-c", "user.email=test@example.invalid",
        "-c", "tag.gpgsign=false", "tag", "-a", "v0.7.1", "-m", "annotated release")
    identity = dependency.git_identity(tmp_path)
    assert identity == {"commit": git("rev-parse", "HEAD"), "version": "0.7.1", "dirty": False}
    (tmp_path / "CMakeLists.txt").write_text("# changed\n")
    assert dependency.git_identity(tmp_path)["dirty"]


def test_authenticated_manifest_success(monkeypatch, tmp_path, release_lock, manifest):
    files = tmp_path / "download"
    files.mkdir()
    write(files / "release-manifest.json", manifest)
    (files / "SHA256SUMS").write_text(
        digest(files / "release-manifest.json") + "  release-manifest.json\n")
    monkeypatch.setattr(verified, "api", lambda path:
                        {"sha": COMMIT} if "/commits/" in path else
                        {"id": 42, "draft": False, "tag_name": release_lock["release_tag"],
                         "assets": [{"name": name} for name in ("release-manifest.json", "SHA256SUMS")]})
    calls = []

    def command(*args):
        calls.append(args)
        if args[1:3] == ("release", "download"):
            name = args[args.index("--pattern") + 1]
            destination = Path(args[args.index("--dir") + 1])
            (destination / name).write_bytes((files / name).read_bytes())

    monkeypatch.setattr(verified, "run", command)
    actual, _, _, identity = verified.authenticated_release(tmp_path / "assets", release_lock)
    assert actual == manifest and identity["release_id"] == 42
    attestations = [args for args in calls if args[1:3] == ("attestation", "verify")]
    assert len(attestations) == 2
    assert all(args[-4:] == ("--signer-workflow", verified.SIGNER, "--source-digest", COMMIT)
               for args in attestations)
