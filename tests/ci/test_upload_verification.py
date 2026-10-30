# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Full CI accepts the upload set only after every configuration installed and tested its exact bytes."""

import argparse
import copy
from pathlib import Path
import platform
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from build_support import digest, read, write
import ci
import ci_contract as contract
import package_contract as packages
from package_contract import DISTRIBUTION
from test_gate import DEFINITIONS, IDENTITY, checks, records, verifications
from test_packages import PREFIX, artifacts, sdist_contents, wheel_contents, write_sdist, write_wheel

WHEEL = packages.wheel_name(packages.policy(), "Linux")
SDIST = PREFIX + ".tar.gz"


def gate(data, verified):
    return contract.validate_records(data, "full", IDENTITY, DEFINITIONS, checks("full"), False, verified)


@pytest.mark.parametrize("path,value", [
    (("kind",), "build"), (("tier",), "pr"), (("status",), "failed"), (("schema",), 2),
    (("identity", "run_attempt"), "1"), (("definitions", "scripts/ci.py"), "e" * 64),
    (("configuration", "python"), "3.12"), (("require_release",), True), (("runtime", "python"), "3.12.1"),
    (("runtime", "system"), "Windows"), (("upload", WHEEL), "0" * 64), (("upload", SDIST), "0" * 64),
    (("upload", "opentlv-0.1.0-cp311-abi3-linux_x86_64.whl"), "c" * 64),
    (("installed",), {WHEEL: "0" * 64}), (("installed",), {SDIST: "e" * 64}),
    (("core", "commit"), "f" * 40), (("smoke",), False),
    (("package_versions", "opentlv-core"), "0.1.0"), (("package_versions", DISTRIBUTION), "0.2.0"),
    (("tests", "tests"), 1), (("tests", "skipped"), 1), (("examples",), 13), (("query", "checks"), 663)])
def test_gate_rejects_incomplete_or_foreign_verification(path, value):
    data = records("full")
    verified = verifications(data)
    # linux-3.13 installed the wheel that linux-3.11 built and tested.
    target = next(record for record in verified if record["configuration"]["id"] == "linux-3.13")
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        gate(data, verified)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "substitution", "none"])
def test_gate_requires_one_verification_per_full_configuration(kind):
    data = records("full")
    verified = verifications(data)
    if kind == "missing":
        verified.pop()
    elif kind == "duplicate":
        verified.append(copy.deepcopy(verified[0]))
    elif kind == "substitution":
        verified[-1] = copy.deepcopy(verified[0])
    else:
        verified = []
    with pytest.raises(ValueError, match="verification"):
        gate(data, verified)


def test_gate_rejects_bytes_that_no_configuration_verified():
    data = records("full")
    verified = verifications(data)
    # A rebuilt linux-3.11 wheel replaces the bytes that every Linux configuration installed.
    data[0]["artifacts"]["wheels/" + WHEEL] = data[0]["wheels"][DISTRIBUTION] = "d" * 64
    with pytest.raises(ValueError, match="selected upload set"):
        gate(data, verified)


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    """Downloaded Full build artifacts with real package bytes, as the select job receives them."""
    monkeypatch.setattr(ci, "identity", lambda: copy.deepcopy(IDENTITY))
    monkeypatch.setattr(ci, "definition_hashes", lambda: dict(DEFINITIONS))
    root = tmp_path / "evidence"
    data = records("full")
    for record in data:
        directory = root / ("python-build-full-" + record["configuration"]["id"] + "-2")
        artifacts(directory / "ci", record)
        write(directory / "record.json", record)
    return root, data


def select(evidence, tmp_path):
    output = tmp_path / "upload"
    ci.select(argparse.Namespace(evidence=evidence, output=output, require_release=False))
    return output


def test_select_copies_the_tested_upload_set(tmp_path, evidence):
    root, data = evidence
    output = select(root, tmp_path)
    selection = read(output / "selection.json")
    upload = contract.select_distributions(data)
    assert selection["distributions"] == upload
    assert {path.name: digest(path) for path in (output / "dist").iterdir()} == {
        name: item["sha256"] for name, item in upload.items()}
    assert selection["core"] == {name: data[0]["core"] for name in upload if name.endswith(".whl")}
    assert selection["identity"] == IDENTITY and selection["require_release"] is False
    with pytest.raises(ValueError, match="fresh"):
        select(root, tmp_path)


@pytest.mark.parametrize("mutation,message", [
    ("wheel-bytes", "differ from validated build"), ("sdist-content", "differ between configurations"),
    ("attempt", "this Full attempt"), ("release", "this Full attempt"), ("missing", "configuration evidence")])
def test_select_rejects_untested_or_inconsistent_builds(tmp_path, evidence, mutation, message):
    root, _ = evidence
    directory = root / "python-build-full-windows-3.14-2"
    record = read(directory / "record.json")
    if mutation == "wheel-bytes":
        wheel = next((directory / "ci/wheels").iterdir())
        wheel.write_bytes(wheel.read_bytes() + b"changed")
    elif mutation == "sdist-content":
        # Its own wheel was rebuilt from this sdist; the published sdist must have the same files.
        path = directory / "ci/sdists" / SDIST
        contents = sdist_contents(path)
        contents[PREFIX + "/src/opentlv/reader.py"] += b"# changed\n"
        write_sdist(path, contents)
        record["artifacts"]["sdists/" + SDIST] = digest(path)
        write(directory / "record.json", record)
    elif mutation == "missing":
        (directory / "record.json").unlink()
    else:
        if mutation == "attempt":
            record["identity"]["run_attempt"] = "1"
        else:
            record["require_release"] = True
        write(directory / "record.json", record)
    with pytest.raises(ValueError, match=message):
        select(root, tmp_path)
    assert not (tmp_path / "upload").exists()


def rewrite(output, name, change):
    """Change one packaged file and record the new bytes, as a substituted upload set would."""
    path = output / "dist" / name
    contents = wheel_contents(path)
    change(contents)
    write_wheel(path, contents)
    selection = read(output / "selection.json")
    selection["distributions"][name]["sha256"] = digest(path)
    write(output / "selection.json", selection)


@pytest.mark.parametrize("mutation,message", [
    ("bytes", "differs from its selection"), ("extra", "differs from its selection"),
    ("missing", "differs from its selection"), ("platform", "package policy"), ("attempt", "this attempt"),
    ("definitions", "this attempt"), ("release", "this attempt"), ("native", "native _opentlv"),
    ("dependency", "must not depend"), ("tag", "tag differs")])
def test_verification_rejects_a_substituted_or_invalid_upload_set(tmp_path, evidence, mutation, message):
    output = select(evidence[0], tmp_path)
    record = {"identity": copy.deepcopy(IDENTITY), "definitions": dict(DEFINITIONS), "require_release": False}
    info = PREFIX + ".dist-info/"
    if mutation == "bytes":
        path = output / "dist" / WHEEL
        path.write_bytes(path.read_bytes() + b"changed")
    elif mutation == "extra":
        (output / "dist/opentlv_core-0.1.0-cp311-abi3-manylinux_2_28_x86_64.whl").write_bytes(b"split")
    elif mutation == "missing":
        (output / "dist" / SDIST).unlink()
    elif mutation == "platform":
        selection = read(output / "selection.json")
        del selection["distributions"][WHEEL], selection["core"][WHEEL]
        write(output / "selection.json", selection)
        (output / "dist" / WHEEL).unlink()
    elif mutation == "attempt":
        record["identity"]["run_attempt"] = "3"
    elif mutation == "definitions":
        record["definitions"] = {}
    elif mutation == "release":
        record["require_release"] = True
    elif mutation == "native":
        rewrite(output, WHEEL, lambda contents: contents.pop("_opentlv.abi3.so"))
    elif mutation == "dependency":
        rewrite(output, WHEEL, lambda contents: contents.__setitem__(
            info + "METADATA", contents[info + "METADATA"] + b"Requires-Dist: opentlv-core==0.1.0\n"))
    else:
        rewrite(output, WHEEL, lambda contents: contents.__setitem__(
            info + "WHEEL", contents[info + "WHEEL"].replace(b"manylinux_2_28_x86_64", b"linux_x86_64")))
    with pytest.raises(ValueError, match=message):
        ci.upload_set(output, record, packages.policy())


def report(*items):
    return {"install": [{"metadata": {"name": name},
                         "download_info": {"url": "file:///D:/a/build/upload/dist/" + archive,
                                           "archive_info": {"hashes": {"sha256": sha}}}}
                        for name, archive, sha in items]}


def test_installed_wheel_reads_pip_report():
    assert ci.installed_wheel(report((DISTRIBUTION, WHEEL, "c" * 64))) == {WHEEL: "c" * 64}
    with pytest.raises(ValueError, match="other distributions"):
        ci.installed_wheel(report((DISTRIBUTION, WHEEL, "c" * 64), ("opentlv-core", "core.whl", "d" * 64)))
    with pytest.raises(ValueError, match="other distributions"):
        ci.installed_wheel({"install": []})


def current_configuration():
    system = {"Linux": "linux", "Windows": "windows", "Darwin": "macos"}[platform.system()]
    name = f"{system}-{sys.version_info.major}.{sys.version_info.minor}"
    if name not in {item["id"] for item in contract.matrix("full")}:
        pytest.skip("This interpreter is outside the Full matrix")
    return name


@pytest.mark.parametrize("installed", ["selected", "other"])
def test_verify_installs_the_selected_wheel_by_name(tmp_path, evidence, monkeypatch, installed):
    name = current_configuration()
    system = next(item["system"] for item in contract.matrix("full") if item["id"] == name)
    wheel = packages.wheel_name(packages.policy(), system)
    output = select(evidence[0], tmp_path)
    sha = read(output / "selection.json")["distributions"][wheel]["sha256"]
    # The committed lock names an attested Core release, as the fixture records do.
    monkeypatch.setattr(ci, "core_corpus", lambda work, core: tmp_path / "corpus")
    commands = []

    def run(*args, **kwargs):
        command = [str(item) for item in args]
        commands.append(command)
        if "--report" in command:
            write(Path(command[command.index("--report") + 1]),
                  report((DISTRIBUTION, wheel, sha if installed == "selected" else "0" * 64)))
        elif any(item.endswith("check_python.py") for item in command):
            policy = read(ci.ROOT / "cmake/ci-matrix.json")
            junit = Path(command[command.index("--junit") + 1])
            junit.write_text('<testsuite tests="%d">%s</testsuite>' % (
                policy["pytest_cases"], "<testcase/>" * policy["pytest_cases"]))
            write(Path(command[command.index("--output") + 1]), {
                "smoke": True, "package_versions": {DISTRIBUTION: packages.policy()["version"]},
                "tests": {"tests": policy["pytest_cases"], "failures": 0, "errors": 0, "skipped": 0},
                "examples": policy["examples"],
                "query": {"fixtures": policy["query_fixtures"], "checks": policy["query_checks"]}})
    monkeypatch.setattr(ci, "run", run)
    args = argparse.Namespace(tier="full", configuration=name, upload=output, work=tmp_path / "verify",
                              output=tmp_path / "verified.json", require_release=False)
    if installed == "other":
        with pytest.raises(ValueError, match="selected wheel"):
            ci.verify(args)
        assert not args.output.exists()
        return
    ci.verify(args)
    install = next(command for command in commands if "--report" in command)
    # By name from the upload set only, never an sdist build, and only with the selected wheel's hash.
    assert install[install.index("--find-links") + 1] == str(output.resolve() / "dist")
    assert {"--no-index", "--require-hashes"} <= set(install)
    assert install[install.index("--only-binary") + 1] == ":all:"
    assert (tmp_path / "verify/requirements.txt").read_text() == (
        f'{DISTRIBUTION}=={packages.policy()["version"]} --hash=sha256:{sha}\n')
    checker = next(command for command in commands if any(item.endswith("check_python.py") for item in command))
    assert checker[checker.index("--corpus") + 1] == str(tmp_path / "corpus")
    assert "--smoke" not in checker
    record = read(args.output)
    assert record["kind"] == "upload-verification" and record["installed"] == {wheel: sha}
    assert record["upload"] == {key: item["sha256"] for key, item in read(output / "selection.json")[
        "distributions"].items()}
    assert record["configuration"]["id"] == name and record["status"] == "success"


def test_verify_requires_a_full_configuration_of_this_runner(tmp_path):
    args = argparse.Namespace(tier="full", configuration="linux-2.7", upload=tmp_path, work=tmp_path / "verify",
                              output=tmp_path / "verified.json", require_release=False)
    args.output.write_text('{"status": "success"}')
    with pytest.raises(ValueError, match="outside this tier"):
        ci.verify(args)
    assert not args.output.exists()


def test_sdist_payload_ignores_archive_metadata_only(tmp_path):
    contents = {PREFIX + "/PKG-INFO": b"Name: opentlv\n", PREFIX + "/pyproject.toml": b"[project]\n"}
    write_sdist(tmp_path / "a.tar.gz", contents)
    write_sdist(tmp_path / "b.tar.gz", dict(reversed(list(contents.items()))))
    assert packages.sdist_payload(tmp_path / "a.tar.gz") == packages.sdist_payload(tmp_path / "b.tar.gz")
    write_sdist(tmp_path / "c.tar.gz", {**contents, PREFIX + "/pyproject.toml": b"[project]\nname = 'x'\n"})
    assert packages.sdist_payload(tmp_path / "a.tar.gz") != packages.sdist_payload(tmp_path / "c.tar.gz")
