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
import release
from test_gate import CHECKS, IDENTITY, records


def metadata(name, value):
    result = (f'Metadata-Version: 2.4\nName: {name}\nVersion: {value["version"]}\n'
              f'License-Expression: MIT\nLicense-File: LICENSE\n'
              f'Requires-Python: {value["requires_python"]}\n')
    if name == "opentlv":
        result += f'Requires-Dist: opentlv-core=={value["version"]}\n'
    return result.encode()


def artifacts(work, record):
    value = packages.policy()
    for name in packages.DISTRIBUTIONS:
        prefix = name.replace("-", "_") + "-" + value["version"]
        native = name == "opentlv-core"
        tag = "cp311-abi3-linux_x86_64" if native else "py3-none-any"
        path = work / "wheels" / (prefix + "-" + tag + ".whl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            info = prefix + ".dist-info/"
            archive.writestr(info + "METADATA", metadata(name, value))
            archive.writestr(info + "WHEEL", f'Wheel-Version: 1.0\nTag: {tag}\nRoot-Is-Purelib: {str(not native).lower()}\n')
            archive.writestr(info + "licenses/LICENSE", (ROOT / "LICENSE").read_bytes())
            if native:
                archive.writestr(info + "licenses/OpenTLV/LICENSE", b"MIT License\n")
                archive.writestr("_opentlv.abi3.so", b"fixture")
                archive.writestr("_opentlv_core_dependency.json", json.dumps(record["core"]))
            else:
                for source in (ROOT / "src/opentlv").glob("*.py"):
                    archive.writestr("opentlv/" + source.name, source.read_bytes())
        record["wheels"][name] = digest(path)
        if record["tier"] == "full":
            path = work / "sdists" / (prefix + ".tar.gz")
            path.parent.mkdir(parents=True, exist_ok=True)
            project = packages.PROJECTS[packages.DISTRIBUTIONS.index(name)]
            contents = {"PKG-INFO": metadata(name, value), "pyproject.toml": (ROOT / project).read_bytes()}
            for relative in packages.sdist_inputs(name):
                contents[relative] = (ROOT / Path(project).parent / relative).read_bytes()
            if native:
                for relative in ("cmake/python-package.json", "cmake/core-artifact.json",
                                 "docs/migration/source-inventory.json"):
                    contents[relative] = (ROOT / relative).read_bytes()
            with tarfile.open(path, "w:gz") as archive:
                for relative, content in contents.items():
                    entry = tarfile.TarInfo(prefix + "/" + relative)
                    entry.size = len(content)
                    archive.addfile(entry, io.BytesIO(content))
    record["artifacts"] = packages.inspect_artifacts(work, record["tier"], record["core"], value)


@pytest.mark.parametrize("tier", ["pr", "main", "full"])
def test_distribution_roundtrip(tmp_path, tier):
    record = records(tier)[0]
    artifacts(tmp_path, record)
    packages.validate_bundle(tmp_path, record, packages.policy())
    assert len(record["artifacts"]) == (4 if tier == "full" else 2)


@pytest.mark.parametrize("name", packages.DISTRIBUTIONS)
@pytest.mark.parametrize("mutation", ["missing-source", "obsolete-layout"])
def test_sdist_rejects_incomplete_or_obsolete_layout(tmp_path, name, mutation):
    record = records("full")[0]
    artifacts(tmp_path, record)
    path = tmp_path / "sdists" / (name.replace("-", "_") + "-0.1.0.tar.gz")
    with tarfile.open(path) as archive:
        contents = {member.name: archive.extractfile(member).read()
                    for member in archive.getmembers() if member.isfile()}
    prefix = name.replace("-", "_") + "-0.1.0/"
    if mutation == "missing-source":
        del contents[prefix + ("native/common/path_query.h" if name == "opentlv-core"
                               else "opentlv/reader.py")]
    else:
        contents[prefix + "bindings/obsolete.py"] = b"# stale source\n"
    with tarfile.open(path, "w:gz") as archive:
        for relative, content in contents.items():
            entry = tarfile.TarInfo(relative)
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
    with pytest.raises(ValueError, match="build inputs|obsolete bindings"):
        packages.check_sdist(path, name, packages.policy())


@pytest.mark.parametrize("mutation", ["missing-source", "test-payload"])
def test_public_wheel_rejects_incomplete_or_test_payload(tmp_path, mutation):
    record = records()[0]
    artifacts(tmp_path, record)
    path = next((tmp_path / "wheels").glob("opentlv-*.whl"))
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    if mutation == "missing-source":
        del contents["opentlv/reader.py"]
    else:
        contents["opentlv/tests/test_reader.py"] = b"# test\n"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match="source inventory"):
        packages.check_wheel(path, "opentlv", packages.policy(), record["core"])


@pytest.mark.parametrize("name,entry", [
    ("opentlv", "licenses/LICENSE"),
    ("opentlv-core", "licenses/LICENSE"),
    ("opentlv-core", "licenses/OpenTLV/LICENSE"),
])
@pytest.mark.parametrize("mutation", ["missing", "changed"])
def test_wheel_requires_license_texts(tmp_path, name, entry, mutation):
    record = records()[0]
    artifacts(tmp_path, record)
    path = next((tmp_path / "wheels").glob(name.replace("-", "_") + "-*.whl"))
    entry = name.replace("-", "_") + "-0.1.0.dist-info/" + entry
    with zipfile.ZipFile(path) as archive:
        contents = {item: archive.read(item) for item in archive.namelist()}
    if mutation == "missing":
        del contents[entry]
    else:
        # An empty Core license, or a project license that differs from LICENSE.
        contents[entry] = b"" if entry.endswith("OpenTLV/LICENSE") else b"Copyright (c) 2026 OpenTLV\n"
    with zipfile.ZipFile(path, "w") as archive:
        for item, content in contents.items():
            archive.writestr(item, content)
    with pytest.raises(ValueError, match="license"):
        packages.check_wheel(path, name, packages.policy(), record["core"])


@pytest.mark.parametrize("name", packages.DISTRIBUTIONS)
def test_sdist_requires_license_text(tmp_path, name):
    record = records("full")[0]
    artifacts(tmp_path, record)
    path = tmp_path / "sdists" / (name.replace("-", "_") + "-0.1.0.tar.gz")
    with tarfile.open(path) as archive:
        contents = {member.name: archive.extractfile(member).read()
                    for member in archive.getmembers() if member.isfile()}
    contents[name.replace("-", "_") + "-0.1.0/LICENSE"] = b"Copyright (c) 2026 OpenTLV\n"
    with tarfile.open(path, "w:gz") as archive:
        for relative, content in contents.items():
            entry = tarfile.TarInfo(relative)
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
    with pytest.raises(ValueError, match="license"):
        packages.check_sdist(path, name, packages.policy())


@pytest.mark.parametrize("before,after", [
    (b"Version: 0.1.0", b"Version: 0.7.1"),
    (b"Name: opentlv", b"Name: other"),
    (b"Requires-Python: >=3.11", b"Requires-Python: >=3.12"),
    (b"opentlv-core==0.1.0", b"opentlv-core"),
    (b"opentlv-core==0.1.0", b"opentlv-core>=0.1.0"),
    (b"opentlv-core==0.1.0", b"opentlv-core==0.7.1"),
    (b"License-Expression: MIT", b"License-Expression: Apache-2.0"),
    (b"License-File: LICENSE\n", b""),
])
def test_metadata_rejects_incompatible_packages(before, after):
    value = packages.policy()
    with pytest.raises(ValueError):
        packages.check_metadata(metadata("opentlv", value).replace(before, after), "opentlv", value)


@pytest.mark.parametrize("mutation", ["version", "dependency", "core", "baseline",
                                      "license", "license-files", "license-copy"])
def test_source_policy_drift(tmp_path, mutation):
    for relative in (*packages.PROJECTS, "cmake/python-package.json", "cmake/core-artifact.json",
                     "docs/migration/source-inventory.json", "LICENSE", "src/LICENSE"):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    if mutation in ("version", "dependency"):
        path = tmp_path / packages.PROJECTS[1]
        text = path.read_text()
        text = text.replace('version = "0.1.0"', 'version = "0.2.0"') if mutation == "version" else text.replace("==0.1.0", "")
        path.write_text(text)
    elif mutation in ("license", "license-files"):
        path = tmp_path / packages.PROJECTS[0]
        text = path.read_text()
        path.write_text(text.replace('license = "MIT"', 'license = "Apache-2.0"') if mutation == "license"
                        else text.replace('license-files = ["LICENSE"]\n', ""))
    elif mutation == "license-copy":
        path = tmp_path / "src/LICENSE"
        path.write_bytes(path.read_bytes().replace(b"Marek Cingel", b"OpenTLV"))
    else:
        path = tmp_path / ("cmake/core-artifact.json" if mutation == "core" else "cmake/python-package.json")
        data = read(path)
        if mutation == "core":
            data["version"] = "99.0.0"
        else:
            data["migration"]["commit"] = "f" * 40
        write(path, data)
    with pytest.raises(ValueError):
        packages.policy(tmp_path)


@pytest.mark.parametrize("mutation", ["digest", "core", "missing", "extra", "traversal"])
def test_bundle_rejects_tampering(tmp_path, mutation):
    record = records()[0]
    artifacts(tmp_path, record)
    native = next((tmp_path / "wheels").glob("opentlv_core*.whl"))
    if mutation == "digest":
        native.write_bytes(native.read_bytes() + b"changed")
    elif mutation == "core":
        record["core"]["commit"] = "f" * 40
    elif mutation == "missing":
        native.unlink()
    elif mutation == "extra":
        (tmp_path / "wheels/unexpected.whl").write_bytes(b"extra")
    else:
        record["artifacts"]["../outside.whl"] = record["artifacts"].pop(next(iter(record["artifacts"])))
    with pytest.raises(ValueError):
        packages.validate_bundle(tmp_path, record, packages.policy())


def release_fixture(tmp_path, monkeypatch):
    data = records("full")
    pinned = ci_contract.lock()
    verified = {**pinned, "release_tag": "v" + pinned["version"]}
    monkeypatch.setattr(ci_contract, "lock", lambda *_: verified)
    monkeypatch.setattr(release, "preflight", lambda: (IDENTITY, packages.policy(), verified))
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
    release.assemble(evidence, quality, output)
    manifest = read(output / "manifest.json")
    assert manifest["publication_enabled"] is False
    assert manifest["identity"] == IDENTITY
    assert len(manifest["configurations"]) == 15
    for line in (output / "SHA256SUMS").read_text().splitlines():
        sha, name = line.split("  ")
        assert sha == digest(output / name)
    import hashlib
    with zipfile.ZipFile(next(output.glob("*.zip"))) as archive:
        assert json.loads(archive.read("manifest.json")) == manifest
        for name, sha in manifest["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == sha
    with pytest.raises(ValueError, match="fresh"):
        release.assemble(evidence, quality, output)


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
        release.assemble(evidence, quality, output)
    assert not output.exists()


def test_release_preflight_rejects_current_null_lock():
    with pytest.raises(ValueError, match="published Core"):
        release.preflight()


@pytest.mark.parametrize("key,value", [("hosted", False), ("dirty", True), ("repository", "other/repo")])
def test_release_preflight_rejects_untrusted_identity(monkeypatch, key, value):
    monkeypatch.setattr(release, "lock", lambda *_: {})
    monkeypatch.setattr(release, "identity", lambda: {**IDENTITY, key: value})
    with pytest.raises(ValueError, match="official clean hosted"):
        release.preflight()


def test_release_preflight_requires_manual_main(monkeypatch):
    monkeypatch.setattr(release, "lock", lambda *_: {})
    monkeypatch.setattr(release, "identity", lambda: copy.deepcopy(IDENTITY))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature/test")
    with pytest.raises(ValueError, match="main"):
        release.preflight()
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    assert release.preflight()[0] == IDENTITY
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    with pytest.raises(ValueError, match="main"):
        release.preflight()
