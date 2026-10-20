# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Build and validate installed Python packages, or aggregate exact CI evidence."""

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import time
import venv
import zipfile

from build_support import ROOT, digest, read, require, run, write
from ci_contract import (TIERS, definition_hashes, identity, matrix,
                         validate_dependency, validate_records)
from verified_core import lock


def wheel_inventory(directory):
    wheels = {}
    for wheel in directory.glob("*.whl"):
        distribution = wheel.name.split("-")[0].replace("_", "-")
        require(distribution in ("opentlv", "opentlv-core") and distribution not in wheels,
                "Unexpected or duplicate wheel")
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            if distribution == "opentlv-core":
                require("-cp311-abi3-" in wheel.name, "Native wheel lost its stable ABI tag")
                payload = [name for name in names if ".dist-info/" not in name]
                require(len(payload) == 2 and "_opentlv_core_dependency.json" in payload
                        and any(name.startswith("_opentlv.") and name.endswith((".so", ".pyd"))
                                for name in payload), "Unexpected native wheel payload")
            else:
                require(wheel.name.endswith("-py3-none-any.whl"), "Unexpected public wheel tag")
                require("opentlv/__init__.py" in names, "Public facade is missing")
        wheels[distribution] = wheel
    require(set(wheels) == {"opentlv", "opentlv-core"}, "Both distributions must be built")
    return wheels


def build(args):
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
    started = time.monotonic()
    record = {"schema": 1, "tier": args.tier, "configuration": configuration,
              "identity": identity(), "definitions": definition_hashes(),
              "require_release": args.require_release,
              "runtime": {"python": platform.python_version(), "system": platform.system(),
                          "machine": platform.machine()}}
    native = work / "native"
    wheel_dir = work / "wheels"
    wheel_dir.mkdir()
    sources = [ROOT, ROOT / "bindings/python/opentlv"]
    if args.tier == "full":
        sdist_dir = work / "sdists"
        for source in sources:
            run(sys.executable, "-B", "-m", "build", "--sdist", "--no-isolation",
                "--outdir", sdist_dir, source)
        sources = sorted(sdist_dir.glob("*.tar.gz"))
        require(len(sources) == 2, "Both source distributions must be built")
        # Native first, facade second. --no-deps prevents accidental index substitutes.
        sources.sort(key=lambda path: "opentlv_core-" not in path.name)
    for index, source in enumerate(sources):
        settings = [] if index else [
            "--config-settings=build-dir=" + str(native),
            "--config-settings=cmake.define.CMAKE_BUILD_TYPE=Release",
            "--config-settings=cmake.define.OPENTLV_PYTHON_REQUIRE_VERIFIED_CORE="
            + ("ON" if args.require_release else "OFF")]
        run(sys.executable, "-B", "-m", "pip", "wheel", "--no-deps", "--no-cache-dir",
            "--no-build-isolation", *settings, "--wheel-dir", wheel_dir, source)
    selected = read(native / "core-selection.json")
    validate_dependency(selected, args.require_release)
    wheels = wheel_inventory(wheel_dir)
    # Runtime installation is isolated from both the build environment and source imports.
    environment = work / "runtime"
    # pip --python supports an empty venv even on distributions without ensurepip.
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    pip = [sys.executable, "-m", "pip", "--python", python]
    run(*pip, "install", "--no-index", "--no-deps", *wheels.values())
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
                   "wheels": {name: digest(path) for name, path in wheels.items()},
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
        report = validate_records(records, args.tier, current, definition_hashes(),
                                  json.loads(os.environ["CHECK_RESULTS"]), args.require_release)
        write(args.output, report)


if __name__ == "__main__":
    main()
