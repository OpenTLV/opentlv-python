# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Build and validate the installed Python distribution, or aggregate exact CI evidence."""

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import sysconfig
import time
import venv

from build_support import ROOT, digest, read, require, run, write
from ci_contract import (TIERS, definition_hashes, identity, matrix,
                         validate_dependency, validate_records)
from verified_core import lock
from package_contract import (DISTRIBUTION, inspect_artifacts, policy as package_policy,
                              validate_bundle, wheel_name)


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


def build(args):
    # Invalidate a previous success before any check/build can fail.
    args.output.unlink(missing_ok=True)
    lock(args.require_release)
    package = package_policy()
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
    started = time.monotonic()
    record = {"schema": 1, "tier": args.tier, "configuration": configuration,
              "identity": identity(), "definitions": definition_hashes(),
              "require_release": args.require_release,
              "runtime": {"python": platform.python_version(), "system": platform.system(),
                          "machine": platform.machine()}}
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
    # Runtime installation is isolated from both the build environment and source imports.
    environment = work / "runtime"
    # pip --python supports an empty venv even on distributions without ensurepip.
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    pip = [sys.executable, "-m", "pip", "--python", python]
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
    from ci_contract import junit_counts
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
    gate = commands.add_parser("gate")
    gate.add_argument("--tier", choices=TIERS, required=True)
    gate.add_argument("--evidence", type=Path, required=True)
    gate.add_argument("--output", type=Path, required=True)
    gate.add_argument("--require-release", action="store_true")
    args = parser.parse_args()
    if args.command == "matrix":
        print(json.dumps({"include": matrix(args.tier)}, separators=(",", ":")))
    elif args.command == "build":
        build(args)
    else:
        args.output.unlink(missing_ok=True)
        current = identity()
        require(current["hosted"] and not current["dirty"] and current["repository"] == "OpenTLV/opentlv-python",
                "Hosted quality evidence requires the official clean checkout")
        records = [read(path) for path in sorted(args.evidence.rglob("record.json"))]
        for path in sorted(args.evidence.rglob("record.json")):
            validate_bundle(path.parent / "ci", read(path), package_policy())
        report = validate_records(records, args.tier, current, definition_hashes(),
                                  json.loads(os.environ["CHECK_RESULTS"]), args.require_release)
        write(args.output, report)


if __name__ == "__main__":
    main()
