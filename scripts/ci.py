# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Build and validate the installed Python distribution, verify the selected upload set on every
Full configuration, install it from a package index, or aggregate exact CI evidence."""

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import sysconfig
import time
from urllib.parse import unquote, urlparse
import venv

from build_support import ROOT, digest, read, require, run, write
from ci_contract import (TIERS, definition_hashes, identity, junit_counts, matrix, select_distributions,
                         validate_dependency, validate_records, validate_suite)
from core_dependency import corpus as core_corpus
from verified_core import lock
from package_contract import (DISTRIBUTION, check_sdist, check_wheel, inspect_artifacts,
                              policy as package_policy, sdist_payload, upload_names, validate_bundle, wheel_name)
from package_index import FILE_HOSTS, INDEXES, download, index_release

INDEX_ATTEMPTS = 10
INDEX_DELAY = 30


def portable(raw, destination, system, platform_tag):
    """Repair the raw wheel to its declared portable tag; the contract rejects vendored libraries."""
    destination.mkdir()
    if system == "Linux":
        # auditwheel runs the patchelf executable installed beside this interpreter.
        os.environ["PATH"] = sysconfig.get_path("scripts") + os.pathsep + os.environ["PATH"]
        # --only-plat keeps the declared glibc floor instead of a tag inferred from the runner.
        run(sys.executable, "-m", "auditwheel", "repair", "--only-plat", "--plat", platform_tag,
            "--wheel-dir", destination, raw)
    elif system == "Darwin":
        run(sys.executable, "-m", "delocate.cmd.delocate_wheel", "--require-archs", "arm64",
            "--require-target-macos-version", os.environ["MACOSX_DEPLOYMENT_TARGET"],
            "--wheel-dir", destination, raw)
    else:
        run(sys.executable, "-m", "delvewheel", "repair", "--wheel-dir", destination, raw)


def start(args):
    """Check the requested configuration against this runner and create its fresh work directory."""
    # Invalidate a previous success before any check/build can fail.
    args.output.unlink(missing_ok=True)
    lock(args.require_release)
    require(not args.require_release or args.tier == "full", "Release requires Full CI")
    configurations = {item["id"]: item for item in matrix(args.tier)}
    require(args.configuration in configurations, "Configuration is outside this tier")
    configuration = configurations[args.configuration]
    require(platform.system() == configuration["system"]
            and platform.python_version().startswith(configuration["python"] + "."),
            "Interpreter/platform does not match requested configuration")
    work = args.work.resolve()
    require(not work.exists(), "Use a fresh --work directory; cached evidence is not accepted")
    work.mkdir(parents=True)
    record = {"schema": 1, "tier": args.tier, "configuration": configuration,
              "identity": identity(), "definitions": definition_hashes(),
              "require_release": args.require_release,
              "runtime": {"python": platform.python_version(), "system": platform.system(),
                          "machine": platform.machine()}}
    return configuration, work, record


def runtime(work):
    """Create a virtualenv isolated from the build environment and source imports."""
    environment = work / "runtime"
    # pip --python supports an empty venv even on distributions without ensurepip.
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return python, [sys.executable, "-m", "pip", "--python", python]


def build(args):
    configuration, work, record = start(args)
    package = package_policy()
    started = time.monotonic()
    native = work / "native"
    system = configuration["system"]
    platform_tag = package["wheel_platforms"][system]
    if system == "Darwin":
        # The tag's deployment target also bounds Core, which is compiled in this build.
        os.environ["MACOSX_DEPLOYMENT_TARGET"] = ".".join(platform_tag.split("_")[1:3])
    source = ROOT
    if args.tier == "full":
        run(sys.executable, "-B", "-m", "build", "--sdist", "--no-isolation",
            "--outdir", work / "sdists", ROOT)
        sdists = list((work / "sdists").glob("*.tar.gz"))
        require(len(sdists) == 1, "Expected one source distribution")
        source = sdists[0]
    # --no-deps prevents accidental index substitutes.
    run(sys.executable, "-B", "-m", "pip", "wheel", "--no-deps", "--no-cache-dir", "--no-build-isolation",
        "--config-settings=build-dir=" + str(native),
        "--config-settings=cmake.define.CMAKE_BUILD_TYPE=Release",
        "--config-settings=cmake.define.OPENTLV_PYTHON_REQUIRE_VERIFIED_CORE="
        + ("ON" if args.require_release else "OFF"), "--wheel-dir", work / "raw", source)
    raw = list((work / "raw").glob("*.whl"))
    require(len(raw) == 1, "Expected one raw wheel")
    portable(raw[0], work / "wheels", system, platform_tag)
    selected = read(native / "core-selection.json")
    validate_dependency(selected, args.require_release)
    artifacts = inspect_artifacts(work, args.tier, selected, package, system)
    run(sys.executable, "-m", "twine", "check", "--strict", *(work / path for path in artifacts))
    wheel = work / "wheels" / wheel_name(package, system)
    python, pip = runtime(work)
    run(*pip, "install", "--no-index", "--no-deps", wheel)
    if args.tier != "main":
        run(*pip, "install", "--no-cache-dir", "pytest>=8,<10")
    run(*pip, "check")
    report = work / "runtime.json"
    runtime_args = ["--smoke"] if args.tier == "main" else ["--junit", work / "pytest.xml"]
    run(python, "-I", "-B", ROOT / "scripts/check_python.py",
        "--selection", native / "core-selection.json", "--output", report, *runtime_args,
        cwd=work)
    record.update(read(report))
    record.update({"core": selected, "compiler": read(native / "core-probe.json"),
                   "packaging": "sdist-wheel" if args.tier == "full" else "wheel",
                   "wheels": {DISTRIBUTION: digest(wheel)},
                   "package_version": package["version"], "artifacts": artifacts,
                   "seconds": time.monotonic() - started, "status": "success"})
    # Check test completeness before uploading a success record.
    if args.tier != "main":
        require(record["tests"] == junit_counts(work / "pytest.xml"), "Test report changed")
        policy = read(ROOT / "cmake/ci-matrix.json")
        require(record["tests"]["tests"] == policy["pytest_cases"]
                and record["examples"] == policy["examples"]
                and record["query"] == {"fixtures": policy["query_fixtures"],
                                        "checks": policy["query_checks"]},
                "Binding validation inventory differs")
    require(record["identity"] == identity() and record["definitions"] == definition_hashes(),
            "Checkout changed during validation")
    write(args.output, record)


def select(args):
    """Copy the upload set out of this attempt's Full builds; the gate derives and checks it again."""
    output = args.output.resolve()
    require(not output.exists(), "Use a fresh --output directory")
    current, definitions, package = identity(), definition_hashes(), package_policy()
    paths = sorted(args.evidence.rglob("record.json"))
    records = [read(path) for path in paths]
    directories = {record["configuration"]["id"]: path.parent / "ci" for path, record in zip(paths, records)}
    require(len(directories) == len(records) and set(directories) == {item["id"] for item in matrix("full")},
            "Missing or duplicate configuration evidence")
    for path, record in zip(paths, records):
        require(record.get("tier") == "full" and record.get("status") == "success"
                and record.get("identity") == current and record.get("definitions") == definitions
                and record.get("require_release") is args.require_release,
                "Build evidence is not from this Full attempt")
        validate_bundle(path.parent / "ci", record, package)
    upload = select_distributions(records)

    def located(item):
        configuration, relative = item["source"].split("/", 1)
        return directories[configuration] / relative

    # Every configuration rebuilt and tested a wheel from its own sdist; only their archive metadata
    # may differ from the published one.
    sdist = next(name for name in upload if name.endswith(".tar.gz"))
    payload = sdist_payload(located(upload[sdist]))
    require(all(sdist_payload(directory / "sdists" / sdist) == payload for directory in directories.values()),
            "Source distributions differ between configurations")
    (output / "dist").mkdir(parents=True)
    for name, item in upload.items():
        shutil.copyfile(located(item), output / "dist" / name)
        require(digest(output / "dist" / name) == item["sha256"], "Package changed during selection")
    builds = {record["configuration"]["id"]: record for record in records}
    write(output / "selection.json", {
        "schema": 1, "kind": "upload-set", "identity": current, "definitions": definitions,
        "require_release": args.require_release, "distributions": upload,
        "core": {name: builds[item["source"].split("/")[0]]["core"]
                 for name, item in upload.items() if name.endswith(".whl")}})


def upload_set(directory, record, package):
    """Check the downloaded upload set against its selection, this attempt and the package contract."""
    selection = read(directory / "selection.json")
    require(selection.get("schema") == 1 and selection.get("kind") == "upload-set"
            and selection.get("identity") == record["identity"]
            and selection.get("definitions") == record["definitions"]
            and selection.get("require_release") is record["require_release"],
            "Upload set is not from this attempt")
    names = upload_names(package)
    wheels = {name for name, system in names.items() if system}
    distributions = selection.get("distributions", {})
    require(set(distributions) == set(names) and set(selection.get("core", {})) == wheels,
            "Upload set differs from the package policy")
    files = {path.name: path for path in (directory / "dist").iterdir()}
    require(set(files) == set(distributions)
            and all(path.is_file() and digest(path) == distributions[name]["sha256"] for name, path in files.items()),
            "Upload set differs from its selection")
    for name, system in names.items():
        if system:
            check_wheel(files[name], package, selection["core"][name], system)
        else:
            check_sdist(files[name], package)
    return selection


def installed_wheel(report):
    """Return the archive and digest that pip's installation report names."""
    items = report.get("install", [])
    require(len(items) == 1 and items[0].get("metadata", {}).get("name") == DISTRIBUTION,
            "pip installed other distributions than opentlv")
    info = items[0].get("download_info", {})
    name = unquote(PurePosixPath(urlparse(info.get("url", "")).path).name)
    return {name: info.get("archive_info", {}).get("hashes", {}).get("sha256")}


def install_command(pip, work, version, sha, *source):
    """Install by name, as `pip install opentlv` does: pip has to choose this platform's wheel for the
    running interpreter, and the hash admits no other bytes."""
    requirement = work / "requirements.txt"
    requirement.write_text(f"{DISTRIBUTION}=={version} --hash=sha256:{sha}\n", encoding="utf-8")
    return [*pip, "install", *source, "--only-binary", ":all:", "--require-hashes",
            "--report", work / "install.json", "-r", requirement]


def installed_suite(args, work, record, python, pip, core, started, **evidence):
    """Run the complete installed checks on the wheel in this environment and record their success."""
    write(work / "core-selection.json", core)
    corpus = core_corpus(work / "core", core)
    run(*pip, "install", "--no-cache-dir", "pytest>=8,<10")
    run(*pip, "check")
    report = work / "runtime.json"
    run(python, "-I", "-B", ROOT / "scripts/check_python.py", "--selection", work / "core-selection.json",
        "--corpus", corpus, "--output", report, "--junit", work / "pytest.xml", cwd=work)
    record.update(read(report))
    record.update({"core": core, "seconds": time.monotonic() - started, "status": "success", **evidence})
    require(record["tests"] == junit_counts(work / "pytest.xml"), "Test report changed")
    validate_suite(record, read(ROOT / "cmake/ci-matrix.json"))
    require(record["identity"] == identity() and record["definitions"] == definition_hashes(),
            "Checkout changed during validation")
    write(args.output, record)


def verify(args):
    configuration, work, record = start(args)
    package = package_policy()
    started = time.monotonic()
    upload = args.upload.resolve()
    selection = upload_set(upload, record, package)
    wheel = wheel_name(package, configuration["system"])
    core = selection["core"][wheel]
    validate_dependency(core, args.require_release)
    python, pip = runtime(work)
    sha = selection["distributions"][wheel]["sha256"]
    run(*install_command(pip, work, package["version"], sha, "--no-index", "--find-links", upload / "dist"))
    installed = installed_wheel(read(work / "install.json"))
    require(installed == {wheel: sha}, "pip installed another archive than the selected wheel")
    installed_suite(args, work, record, python, pip, core, started, kind="upload-verification", installed=installed,
                    upload={name: item["sha256"] for name, item in selection["distributions"].items()})


def index_receipt(directory, index, record, package):
    """Return the files that this run's upload confirmed on the index; a re-run reuses its receipt."""
    receipts = [read(path) for path in sorted(directory.glob("*/receipt.json"))]
    require(receipts and all(item == receipts[0] for item in receipts),
            "Missing or contradictory package index receipts")
    receipt = receipts[0]
    require(receipt.get("schema") == 1 and receipt.get("kind") == "python-package-index-release"
            and receipt.get("index") == index and receipt.get("repository") == record["identity"]["repository"]
            and receipt.get("commit") == record["identity"]["commit"] and receipt.get("version") == package["version"]
            and set(receipt.get("files", {})) == set(upload_names(package)),
            "Package index receipt differs from this installation")
    return receipt["files"]


def install_from_index(command, attempts=INDEX_ATTEMPTS, delay=INDEX_DELAY):
    """A project's first upload can take minutes to reach the index's cached simple page."""
    for attempt in range(attempts):
        try:
            return run(*command)
        except subprocess.CalledProcessError:
            if attempt + 1 == attempts:
                raise
            time.sleep(delay)


def index_install(args):
    """Install the published wheel into a fresh environment from the index alone and run the suite on it."""
    args.tier, args.require_release = "full", True
    configuration, work, record = start(args)
    package = package_policy()
    started = time.monotonic()
    files = index_receipt(args.receipts, args.index, record, package)
    wheel = wheel_name(package, configuration["system"])
    python, pip = runtime(work)
    # No second index: opentlv has no dependencies, and a dependency name on another index could be anyone's.
    install_from_index(install_command(pip, work, package["version"], files[wheel], "--no-cache-dir",
                                       "--index-url", INDEXES[args.index] + "/simple/"))
    report = read(work / "install.json")
    installed = installed_wheel(report)
    require(installed == {wheel: files[wheel]}, "pip installed another archive than the published wheel")
    require(urlparse(report["install"][0]["download_info"]["url"]).hostname == FILE_HOSTS[args.index],
            "pip installed the wheel from another host than the package index")
    # The hash binds these bytes to the receipt, and the wheel records the Core it was built with.
    core = read(next(python.parents[1].rglob("_opentlv_core_dependency.json")))
    validate_dependency(core, True)
    # Building the sdist needs the build requirements, which TestPyPI cannot be trusted to supply,
    # and Full already rebuilt these files; check the bytes that the index serves.
    sdist = next(name for name, system in upload_names(package).items() if system is None)
    served = {item["filename"]: item["url"] for item in index_release(args.index, package["version"])["urls"]}
    download(served[sdist], work / sdist)
    require(digest(work / sdist) == files[sdist], "The index serves another sdist than the published one")
    check_sdist(work / sdist, package)
    installed_suite(args, work, record, python, pip, core, started, kind="index-installation", index=args.index,
                    files=files, installed=installed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("matrix")
    plan.add_argument("--tier", choices=TIERS, required=True)
    runner = commands.add_parser("build")
    runner.add_argument("--tier", choices=TIERS, required=True)
    runner.add_argument("--configuration", required=True)
    runner.add_argument("--work", type=Path, required=True)
    runner.add_argument("--output", type=Path, required=True)
    runner.add_argument("--require-release", action="store_true")
    # Only Full builds every platform's wheel, so only Full selects and verifies an upload set.
    chooser = commands.add_parser("select")
    chooser.add_argument("--tier", choices=("full",), required=True)
    chooser.add_argument("--evidence", type=Path, required=True)
    chooser.add_argument("--output", type=Path, required=True)
    chooser.add_argument("--require-release", action="store_true")
    verifier = commands.add_parser("verify")
    verifier.add_argument("--tier", choices=("full",), required=True)
    verifier.add_argument("--configuration", required=True)
    verifier.add_argument("--upload", type=Path, required=True)
    verifier.add_argument("--work", type=Path, required=True)
    verifier.add_argument("--output", type=Path, required=True)
    verifier.add_argument("--require-release", action="store_true")
    installer = commands.add_parser("index")
    installer.add_argument("--index", choices=tuple(INDEXES), required=True)
    installer.add_argument("--configuration", required=True)
    installer.add_argument("--receipts", type=Path, required=True)
    installer.add_argument("--work", type=Path, required=True)
    installer.add_argument("--output", type=Path, required=True)
    gate = commands.add_parser("gate")
    gate.add_argument("--tier", choices=TIERS, required=True)
    gate.add_argument("--evidence", type=Path, required=True)
    gate.add_argument("--verification", type=Path, required=True)
    gate.add_argument("--output", type=Path, required=True)
    gate.add_argument("--require-release", action="store_true")
    args = parser.parse_args()
    if args.command == "matrix":
        print(json.dumps({"include": matrix(args.tier)}, separators=(",", ":")))
    elif args.command == "build":
        build(args)
    elif args.command == "select":
        select(args)
    elif args.command == "verify":
        verify(args)
    elif args.command == "index":
        index_install(args)
    else:
        args.output.unlink(missing_ok=True)
        current = identity()
        require(current["hosted"] and not current["dirty"] and current["repository"] == "OpenTLV/opentlv-python",
                "Hosted quality evidence requires the official clean checkout")
        records = [read(path) for path in sorted(args.evidence.rglob("record.json"))]
        for path in sorted(args.evidence.rglob("record.json")):
            validate_bundle(path.parent / "ci", read(path), package_policy())
        # Only Full downloads verification evidence.
        verifications = [read(path) for path in sorted(args.verification.rglob("verified.json"))]
        report = validate_records(records, args.tier, current, definition_hashes(),
                                  json.loads(os.environ["CHECK_RESULTS"]), args.require_release, verifications)
        write(args.output, report)


if __name__ == "__main__":
    main()
