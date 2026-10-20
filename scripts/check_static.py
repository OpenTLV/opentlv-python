# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Analyze the Python extension only, using its actual compilation commands."""

import argparse
from pathlib import Path
import shutil

from build_support import ROOT, digest, read, require, run, write

SOURCE = ROOT / "bindings/python/opentlv-core/src"


def baseline():
    entries = read(ROOT / "cmake/static-analysis-baseline.json")
    for name, entry in entries.items():
        require((ROOT / name).resolve().is_relative_to(SOURCE), "Invalid baseline source")
        require(digest(ROOT / name) == entry["sha256"],
                "Reassess static-analysis false positives after changing " + name)
    return entries


def sources(build):
    items = [item for item in read(build / "compile_commands.json")
             if Path(item["file"]).resolve().is_relative_to(SOURCE)]
    require({Path(item["file"]).resolve() for item in items} == set(SOURCE.rglob("*.c")),
            "Static analysis requires every Python extension translation unit")
    return items


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--tool", choices=("cppcheck", "clang-tidy"), required=True)
    args = parser.parse_args()
    items = sources(args.build)
    exceptions = baseline()
    if args.tool == "cppcheck":
        database = args.build / "python-compile-commands.json"
        write(database, items)
        suppressions = []
        for name, entry in exceptions.items():
            for diagnostic in entry["cppcheck"]:
                check, line = diagnostic.split(":")
                suppressions.append(f"--suppress={check}:*{name}:{line}")
        run("cppcheck", "--project=" + str(database), "--enable=warning,performance,portability",
            "--error-exitcode=1", "--std=c99", "--inline-suppr", "--suppress=missingIncludeSystem",
            "--suppress=normalCheckLevelMaxBranches", *suppressions)
    else:
        executable = shutil.which("clang-tidy-18") or shutil.which("clang-tidy")
        require(executable, "clang-tidy is required")
        for item in items:
            relative = Path(item["file"]).resolve().relative_to(ROOT).as_posix()
            checks = exceptions.get(relative, {}).get("clang-tidy", [])
            options = ["--checks=" + ",".join("-" + check for check in checks)] if checks else []
            run(executable, "-quiet", "-p", args.build, "--warnings-as-errors=*",
                "--header-filter=.*bindings/(common|python/opentlv-core)/.*", *options, item["file"])


if __name__ == "__main__":
    main()
