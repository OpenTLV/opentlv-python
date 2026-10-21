# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Check Python syntax, workflow structure and the inherited native formatting."""

import ast
from pathlib import Path
import shutil

import yaml

from build_support import ROOT, require, run
from package_contract import policy


def main():
    policy()
    for directory in ("bindings", "scripts", "tests"):
        for path in (ROOT / directory).rglob("*.py"):
            if "__pycache__" not in path.parts:
                ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        # BaseLoader retains the GitHub Actions `on` key instead of YAML 1.1 booleans.
        workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        require(workflow.get("name") and workflow.get("on") and workflow.get("jobs"),
                "Invalid workflow: " + str(path))
    formatter = shutil.which("clang-format")
    require(formatter, "clang-format is required")
    require("version 23.1.1" in run(formatter, "--version", capture=True),
            "Use Core's pinned clang-format 23.1.1")
    for path in sorted((ROOT / "bindings").rglob("*")):
        if path.suffix in (".c", ".h"):
            run(formatter, "--dry-run", "--Werror", path)
    run("git", "diff", "--check")


if __name__ == "__main__":
    main()
