# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Exercise distribution metadata, actual artifact bytes and release assembly failures."""

import copy
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from build_support import ROOT, digest, read, write
import ci_contract
import package_contract as packages
from package_contract import DISTRIBUTION
import release
from test_gate import CHECKS, IDENTITY, null_lock, records

PREFIX = DISTRIBUTION + "-" + packages.policy()["version"]


def metadata(value):
    return (f'Metadata-Version: 2.4\nName: {DISTRIBUTION}\nVersion: {value["version"]}\n'
            f'License-Expression: MIT\nLicense-File: LICENSE\n'
            f'Requires-Python: {value["requires_python"]}\n').encode()


def native(system):
    return "_opentlv.pyd" if system == "Windows" else "_opentlv.abi3.so"


def write_wheel(path, contents):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in contents.items():
            archive.writestr(name, content)


def wheel_contents(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def write_sdist(path, contents):
    with tarfile.open(path, "w:gz") as archive:
        for name, content in contents.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))


def sdist_contents(path):
    with tarfile.open(path) as archive:
        return {member.name: archive.extractfile(member).read()
                for member in archive.getmembers() if member.isfile()}


def artifacts(work, record):
    value = packages.policy()
    system = record["configuration"]["system"]
    path = work / "wheels" / packages.wheel_name(value, system)
    path.parent.mkdir(parents=True, exist_ok=True)
    info = PREFIX + ".dist-info/"
    contents = {info + "METADATA": metadata(value),
                info + "WHEEL": (f'Wheel-Version: 1.0\nTag: cp311-abi3-{value["wheel_platforms"][system]}\n'
                                 'Root-Is-Purelib: false\n').encode(),
                info + "licenses/LICENSE": (ROOT / "LICENSE").read_bytes(),
                info + "licenses/OpenTLV/LICENSE": b"MIT License\n",
                native(system): b"fixture",
                "_opentlv_core_dependency.json": json.dumps(record["core"]).encode()}
    for source in (ROOT / "src/opentlv").glob("*.py"):
        contents["opentlv/" + source.name] = source.read_bytes()
    write_wheel(path, contents)
    record["wheels"] = {DISTRIBUTION: digest(path)}
    if record["tier"] == "full":
        path = work / "sdists" / (PREFIX + ".tar.gz")
        path.parent.mkdir(parents=True, exist_ok=True)
        contents = {PREFIX + "/PKG-INFO": metadata(value)}
        for relative in packages.sdist_inputs():
            contents[PREFIX + "/" + relative] = (ROOT / relative).read_bytes()
        write_sdist(path, contents)
    record["artifacts"] = packages.inspect_artifacts(work, record["tier"], record["core"], value, system)


@pytest.mark.parametrize("tier", ["pr", "main", "full"])
def test_distribution_roundtrip(tmp_path, tier):
    for record in records(tier):
        work = tmp_path / record["configuration"]["id"]
        artifacts(work, record)
        packages.validate_bundle(work, record, packages.policy())
        assert len(record["artifacts"]) == (2 if tier == "full" else 1)
        assert next(iter(record["artifacts"])) == "wheels/" + packages.wheel_name(
            packages.policy(), record["configuration"]["system"])


@pytest.mark.parametrize("mutation,message", [
    ("native/common/path_query.h", "build inputs"), ("src/opentlv/reader.py", "build inputs"),
    ("bindings/obsolete.py", "obsolete bindings"), ("src/pyproject.toml", "second build entry point")])
def test_sdist_rejects_incomplete_or_obsolete_layout(tmp_path, mutation, message):
    record = records("full")[0]
    artifacts(tmp_path, record)
    path = tmp_path / "sdists" / (PREFIX + ".tar.gz")
    contents = sdist_contents(path)
    if PREFIX + "/" + mutation in contents:
        del contents[PREFIX + "/" + mutation]
    else:
        contents[PREFIX + "/" + mutation] = b"# stale source\n"
    write_sdist(path, contents)
    with pytest.raises(ValueError, match=message):
        packages.check_sdist(path, packages.policy())


@pytest.mark.parametrize("mutation,message", [
    ("missing-source", "source inventory"), ("test-payload", "source inventory"),
    ("vendored-library", "source inventory"), ("missing-native", "native _opentlv"),
    ("version-specific-native", "native _opentlv"), ("platform-abi3-native", "native _opentlv"),
    ("core-identity", "Core identity")])
def test_wheel_rejects_incomplete_or_foreign_payload(tmp_path, mutation, message):
    record = records()[0]
    artifacts(tmp_path, record)
    path = next((tmp_path / "wheels").glob("*.whl"))
    contents = wheel_contents(path)
    if mutation == "missing-source":
        del contents["opentlv/reader.py"]
    elif mutation == "test-payload":
        contents["opentlv/tests/test_reader.py"] = b"# test\n"
    elif mutation == "vendored-library":
        # auditwheel grafts external libraries here; Core must stay statically linked.
        contents["opentlv.libs/libopentlv-0a1b2c3d.so"] = b"library"
    elif mutation == "core-identity":
        contents["_opentlv_core_dependency.json"] = json.dumps({**record["core"], "commit": "f" * 40}).encode()
    else:
        module = contents.pop("_opentlv.abi3.so")
        if mutation == "version-specific-native":
            contents["_opentlv.cpython-311-x86_64-linux-gnu.so"] = module
        elif mutation == "platform-abi3-native":
            # CPython 3.15's default stable-ABI suffix, which 3.11-3.14 cannot import.
            contents["_opentlv.abi3-x86_64-linux-gnu.so"] = module
    write_wheel(path, contents)
    with pytest.raises(ValueError, match=message):
        packages.check_wheel(path, packages.policy(), record["core"], "Linux")


def test_wheel_accepts_directory_entries_from_repair(tmp_path):
    record = records()[0]
    artifacts(tmp_path, record)
    path = next((tmp_path / "wheels").glob("*.whl"))
    contents = wheel_contents(path)
    for directory in ("opentlv/", PREFIX + ".dist-info/", PREFIX + ".dist-info/licenses/OpenTLV/"):
        contents[directory] = b""
    write_wheel(path, contents)
    packages.check_wheel(path, packages.policy(), record["core"], "Linux")


@pytest.mark.parametrize("mutation,message", [
    ("filename", "filename"), ("tag", "tag differs"), ("purelib", "installation scheme")])
def test_wheel_rejects_unportable_tag(tmp_path, mutation, message):
    record = records()[0]
    artifacts(tmp_path, record)
    path = next((tmp_path / "wheels").glob("*.whl"))
    info = PREFIX + ".dist-info/WHEEL"
    contents = wheel_contents(path)
    if mutation == "filename":
        # A plain linux tag is what pip builds before the manylinux repair.
        path = path.rename(path.with_name(PREFIX + "-cp311-abi3-linux_x86_64.whl"))
    elif mutation == "tag":
        contents[info] = contents[info].replace(b"manylinux_2_28_x86_64", b"linux_x86_64")
    else:
        contents[info] = contents[info].replace(b"Root-Is-Purelib: false", b"Root-Is-Purelib: true")
    write_wheel(path, contents)
    with pytest.raises(ValueError, match=message):
        packages.check_wheel(path, packages.policy(), record["core"], "Linux")


@pytest.mark.parametrize("entry", ["licenses/LICENSE", "licenses/OpenTLV/LICENSE"])
@pytest.mark.parametrize("mutation", ["missing", "changed"])
def test_wheel_requires_license_texts(tmp_path, entry, mutation):
    record = records()[0]
    artifacts(tmp_path, record)
    path = next((tmp_path / "wheels").glob("*.whl"))
    entry = PREFIX + ".dist-info/" + entry
    contents = wheel_contents(path)
    if mutation == "missing":
        del contents[entry]
    else:
        # An empty Core license, or a project license that differs from LICENSE.
        contents[entry] = b"" if entry.endswith("OpenTLV/LICENSE") else b"Copyright (c) 2026 OpenTLV\n"
    write_wheel(path, contents)
    with pytest.raises(ValueError, match="license"):
        packages.check_wheel(path, packages.policy(), record["core"], "Linux")


def test_sdist_requires_license_text(tmp_path):
    record = records("full")[0]
    artifacts(tmp_path, record)
    path = tmp_path / "sdists" / (PREFIX + ".tar.gz")
    contents = sdist_contents(path)
    contents[PREFIX + "/LICENSE"] = b"Copyright (c) 2026 OpenTLV\n"
    write_sdist(path, contents)
    with pytest.raises(ValueError, match="license"):
        packages.check_sdist(path, packages.policy())


@pytest.mark.parametrize("before,after", [
    (b"Version: 0.1.0", b"Version: 0.7.1"),
    (b"Name: opentlv", b"Name: opentlv-core"),
    (b"Requires-Python: >=3.11", b"Requires-Python: >=3.12"),
    (b"Requires-Python: >=3.11\n", b"Requires-Python: >=3.11\nRequires-Dist: opentlv-core==0.1.0\n"),
    (b"License-Expression: MIT", b"License-Expression: Apache-2.0"),
    (b"License-File: LICENSE\n", b""),
])
def test_metadata_rejects_incompatible_packages(before, after):
    value = packages.policy()
    with pytest.raises(ValueError):
        packages.check_metadata(metadata(value).replace(before, after), value)


@pytest.mark.parametrize("mutation", ["version", "dependency", "core", "baseline", "license", "license-files",
                                      "packages", "entry-point", "platform", "missing-platform"])
def test_source_policy_drift(tmp_path, mutation):
    for relative in (packages.PROJECT, "cmake/python-package.json", "cmake/core-artifact.json",
                     "cmake/ci-matrix.json", "docs/migration/source-inventory.json", "LICENSE"):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    packages.policy(tmp_path)
    project = tmp_path / packages.PROJECT
    text = project.read_text()
    if mutation in ("version", "dependency", "license", "license-files", "packages"):
        project.write_text({
            "version": text.replace('version = "0.1.0"', 'version = "0.2.0"'),
            "dependency": text.replace('license-files = ["LICENSE"]\n',
                                       'license-files = ["LICENSE"]\ndependencies = ["opentlv-core==0.1.0"]\n'),
            "license": text.replace('license = "MIT"', 'license = "Apache-2.0"'),
            "license-files": text.replace('license-files = ["LICENSE"]\n', ""),
            "packages": text.replace('wheel.packages = ["src/opentlv"]', "wheel.packages = []")}[mutation])
    elif mutation == "entry-point":
        (tmp_path / "src").mkdir()
        (tmp_path / "src/pyproject.toml").write_text('[project]\nname = "opentlv"\n')
    else:
        path = tmp_path / ("cmake/core-artifact.json" if mutation == "core" else "cmake/python-package.json")
        data = read(path)
        if mutation == "core":
            data["version"] = "99.0.0"
        elif mutation == "baseline":
            data["migration"]["commit"] = "f" * 40
        elif mutation == "platform":
            data["wheel_platforms"]["Linux"] = "linux_x86_64"
        else:
            del data["wheel_platforms"]["Darwin"]
        write(path, data)
    with pytest.raises(ValueError):
        packages.policy(tmp_path)


@pytest.mark.parametrize("mutation", ["digest", "core", "missing", "extra", "traversal"])
def test_bundle_rejects_tampering(tmp_path, mutation):
    record = records()[0]
    artifacts(tmp_path, record)
    wheel = next((tmp_path / "wheels").glob("*.whl"))
    if mutation == "digest":
        wheel.write_bytes(wheel.read_bytes() + b"changed")
    elif mutation == "core":
        record["core"]["commit"] = "f" * 40
    elif mutation == "missing":
        wheel.unlink()
    elif mutation == "extra":
        (tmp_path / "wheels/unexpected.whl").write_bytes(b"extra")
    else:
        record["artifacts"]["../outside.whl"] = record["artifacts"].pop(next(iter(record["artifacts"])))
    with pytest.raises(ValueError):
        packages.validate_bundle(tmp_path, record, packages.policy())


@pytest.mark.parametrize("system,command", [
    ("Linux", ["auditwheel", "repair", "--only-plat", "--plat", "manylinux_2_28_x86_64"]),
    ("Darwin", ["delocate.cmd.delocate_wheel", "--require-archs", "arm64", "--require-target-macos-version", "11.0"]),
    ("Windows", ["delvewheel", "repair"])])
def test_portable_repair_targets_declared_platform(tmp_path, monkeypatch, system, command):
    import ci
    calls = []
    monkeypatch.setattr(ci, "run", lambda *args, **kwargs: calls.append([str(item) for item in args]))
    monkeypatch.setenv("MACOSX_DEPLOYMENT_TARGET", "11.0")
    ci.portable(tmp_path / "raw.whl", tmp_path / "wheels", system, packages.policy()["wheel_platforms"][system])
    assert calls == [[sys.executable, "-m", *command, "--wheel-dir", str(tmp_path / "wheels"),
                      str(tmp_path / "raw.whl")]]


def release_fixture(tmp_path, monkeypatch):
    data = records("full")
    pinned = ci_contract.lock()
    verified = {**pinned, "release_tag": "v" + pinned["version"]}
    monkeypatch.setattr(ci_contract, "lock", lambda *_: verified)
    monkeypatch.setattr(release, "preflight", lambda tag: (IDENTITY, packages.policy(), verified))
    monkeypatch.setattr(release, "definition_hashes", lambda: {})
    evidence = tmp_path / "evidence"
    for record in data:
        record["require_release"] = True
        record["definitions"] = {}
        record["core"].update(mode="verified-source", verified=True, release_id=1,
                              release_tag=verified["release_tag"], manifest_sha256="a" * 64)
        directory = evidence / record["configuration"]["id"]
        artifacts(directory / "ci", record)
        write(directory / "record.json", record)
    quality = tmp_path / "quality.json"
    write(quality, ci_contract.validate_records(data, "full", IDENTITY, {}, CHECKS, True))
    return evidence, quality, tmp_path / "release"


def test_assemble_preserves_validated_packages_and_checksums(tmp_path, monkeypatch):
    evidence, quality, output = release_fixture(tmp_path, monkeypatch)
    release.assemble(evidence, quality, output, "v0.1.0")
    manifest = read(output / "manifest.json")
    assert manifest["publication_enabled"] is False
    assert manifest["tag"] == "v0.1.0"
    assert manifest["identity"] == IDENTITY
    assert len(manifest["configurations"]) == 15
    for line in (output / "SHA256SUMS").read_text().splitlines():
        sha, name = line.split("  ")
        assert sha == digest(output / name)
    # One wheel per platform from its stable-ABI floor build, and one sdist.
    value = packages.policy()
    assert manifest["distributions"] == {
        packages.wheel_name(value, "Linux"): {"source": "linux-3.11/wheels/" + packages.wheel_name(value, "Linux"),
                                              "sha256": manifest["files"]["linux-3.11/wheels/"
                                                                          + packages.wheel_name(value, "Linux")]},
        packages.wheel_name(value, "Windows"): {
            "source": "windows-3.11/wheels/" + packages.wheel_name(value, "Windows"),
            "sha256": manifest["files"]["windows-3.11/wheels/" + packages.wheel_name(value, "Windows")]},
        packages.wheel_name(value, "Darwin"): {
            "source": "macos-3.11/wheels/" + packages.wheel_name(value, "Darwin"),
            "sha256": manifest["files"]["macos-3.11/wheels/" + packages.wheel_name(value, "Darwin")]},
        PREFIX + ".tar.gz": {"source": "linux-3.11/sdists/" + PREFIX + ".tar.gz",
                             "sha256": manifest["files"]["linux-3.11/sdists/" + PREFIX + ".tar.gz"]}}
    import hashlib
    with zipfile.ZipFile(next(output.glob("*.zip"))) as archive:
        assert json.loads(archive.read("manifest.json")) == manifest
        for name, sha in manifest["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == sha
        assert sorted(name for name in archive.namelist() if name.startswith("dist/")) == sorted(
            "dist/" + name for name in manifest["distributions"])
    with pytest.raises(ValueError, match="fresh"):
        release.assemble(evidence, quality, output, "v0.1.0")


@pytest.mark.parametrize("missing", ["windows-3.11", "linux-3.11"])
def test_upload_set_requires_every_platform_and_the_sdist(missing):
    data = records("full")
    assert len(release.select_distributions(data)) == 4
    with pytest.raises(ValueError, match="Incomplete distribution upload set"):
        release.select_distributions([record for record in data if record["configuration"]["id"] != missing])


@pytest.mark.parametrize("mutation", ["attempt", "missing", "digest", "quality", "unverified"])
def test_release_rejects_stale_or_partial_inputs(tmp_path, monkeypatch, mutation):
    evidence, quality, output = release_fixture(tmp_path, monkeypatch)
    path = next(evidence.rglob("record.json"))
    record = read(path)
    if mutation == "missing":
        path.unlink()
    elif mutation == "quality":
        report = read(quality)
        report["records"][record["configuration"]["id"]] = "0" * 64
        write(quality, report)
    elif mutation == "digest":
        wheel = next(evidence.rglob("*.whl"))
        wheel.write_bytes(wheel.read_bytes() + b"changed")
    else:
        if mutation == "attempt":
            record["identity"]["run_attempt"] = "1"
        else:
            record["core"]["verified"] = False
        write(path, record)
    with pytest.raises(ValueError):
        release.assemble(evidence, quality, output, "v0.1.0")
    assert not output.exists()


def remote(monkeypatch, refs=(), releases=()):
    """Serve the tag and release listings that preflight reads before any remote write."""
    calls = []

    def api(path):
        calls.append(path)
        if "/git/matching-refs/tags/" in path:
            return [{"ref": "refs/tags/" + name} for name in refs]
        assert "/releases?" in path
        return [{"tag_name": name} for name in releases]
    monkeypatch.setattr(release, "api", api)
    return calls


def test_release_preflight_rejects_null_lock(monkeypatch):
    null_lock(monkeypatch)
    with pytest.raises(ValueError, match="published Core"):
        release.preflight("v0.1.0")


def test_committed_release_notes_and_changelog_match_requested_tag():
    version = packages.policy()["version"]
    release.release_text("v" + version, version)
    with pytest.raises(ValueError, match="package version"):
        release.release_text("v9.9.9", version)


@pytest.mark.parametrize("tag", ["", "0.1.0", "v0.1", "v0.1.0.0", "v01.1.0", "v0.1.0-rc.1", "V0.1.0",
                                 " v0.1.0", "v0.1.0\n", "refs/tags/v0.1.0"])
def test_release_text_rejects_malformed_tag(tag):
    with pytest.raises(ValueError, match="vMAJOR"):
        release.release_text(tag, "0.1.0")


NOTES = "# OpenTLV Python v0.1.0\n\n- Bullet.\n"
CLOSED = "## [0.1.0] - 2026-10-28\n"


@pytest.mark.parametrize("tag,notes,changelog,message", [
    ("v0.1.1", NOTES, CLOSED, "package version"),
    ("v0.1.0", "# OpenTLV Python v0.1.0\n\nNo bullet.\n", CLOSED, "release notes"),
    ("v0.1.0", NOTES.replace("v0.1.0", "v0.1.1"), CLOSED, "release notes"),
    ("v0.1.0", NOTES, "## [Unreleased]\n", "changelog"),
    ("v0.1.0", NOTES, "## [0.1.0]\n", "changelog"),
    ("v0.1.0", NOTES, "## [0.1.1] - 2026-10-28\n", "changelog"),
    ("v0.1.0", NOTES, CLOSED, None)])
def test_release_text_requires_matching_notes_and_closed_changelog(tmp_path, monkeypatch, tag, notes,
                                                                   changelog, message):
    (tmp_path / "notes.md").write_text(notes, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n" + changelog, encoding="utf-8")
    monkeypatch.setattr(release, "NOTES", tmp_path / "notes.md")
    monkeypatch.setattr(release, "CHANGELOG", tmp_path / "CHANGELOG.md")
    if message is None:
        release.release_text(tag, "0.1.0")
    else:
        with pytest.raises(ValueError, match=message):
            release.release_text(tag, "0.1.0")


def test_requested_tag_is_required(monkeypatch):
    monkeypatch.delenv("RELEASE_TAG", raising=False)
    with pytest.raises(ValueError, match="explicit tag"):
        release.requested_tag()
    monkeypatch.setenv("RELEASE_TAG", "")
    with pytest.raises(ValueError, match="explicit tag"):
        release.requested_tag()
    monkeypatch.setenv("RELEASE_TAG", "v0.1.0")
    assert release.requested_tag() == "v0.1.0"


@pytest.mark.parametrize("refs,releases,message", [
    (["v0.1.0"], [], "tag already exists"), ([], ["v0.1.0"], "release already exists"),
    (["v0.1.0-rc.1"], ["v0.0.9"], None)])
def test_release_tag_must_be_unused(monkeypatch, refs, releases, message):
    remote(monkeypatch, refs, releases)
    if message is None:
        release.unused_tag("v0.1.0")
    else:
        with pytest.raises(ValueError, match=message):
            release.unused_tag("v0.1.0")


@pytest.mark.parametrize("key,value", [("hosted", False), ("dirty", True), ("repository", "other/repo")])
def test_release_preflight_rejects_untrusted_identity(monkeypatch, key, value):
    monkeypatch.setattr(release, "lock", lambda *_: {})
    monkeypatch.setattr(release, "identity", lambda: {**IDENTITY, key: value})
    calls = remote(monkeypatch)
    with pytest.raises(ValueError, match="official clean hosted"):
        release.preflight("v0.1.0")
    assert not calls


def test_release_preflight_requires_manual_main(monkeypatch):
    monkeypatch.setattr(release, "lock", lambda *_: {})
    monkeypatch.setattr(release, "identity", lambda: copy.deepcopy(IDENTITY))
    remote(monkeypatch)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature/test")
    with pytest.raises(ValueError, match="main"):
        release.preflight("v0.1.0")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    assert release.preflight("v0.1.0")[0] == IDENTITY
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    with pytest.raises(ValueError, match="main"):
        release.preflight("v0.1.0")


def test_release_preflight_rejects_existing_or_mismatched_tag(monkeypatch):
    monkeypatch.setattr(release, "lock", lambda *_: {})
    monkeypatch.setattr(release, "identity", lambda: copy.deepcopy(IDENTITY))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    remote(monkeypatch, refs=["v0.1.0"])
    with pytest.raises(ValueError, match="already exists"):
        release.preflight("v0.1.0")
    calls = remote(monkeypatch)
    with pytest.raises(ValueError, match="package version"):
        release.preflight("v0.2.0")
    assert not calls
