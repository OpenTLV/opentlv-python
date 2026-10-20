#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Verify the initial import against the complete pinned Core Git tree."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "5e0aae9c77e9c22d07c7f03d6110243e9ecad85f"
EXTRA_FILES = {
    "bindings/common/path_query.h": "bindings/common/path_query.h",
    "bindings/common/query_schema.h": "bindings/common/query_schema.h",
    "tests/query/python_facade.py": "tests/query/python_facade.py",
    "docs/development/python.md": "docs/development/python.md",
    "docs/guides/python.md": "docs/guides/python.md",
    ".github/workflows/python.yml": "docs/migration/original-python.yml",
}


def verify(core):
    manifest = json.loads(
        (ROOT / "docs/migration/source-inventory.json").read_text(encoding="utf-8")
    )
    if manifest["source_commit"] != SOURCE_COMMIT:
        raise ValueError("The initial migration baseline must not change")
    if manifest["source_repository"] != "https://github.com/OpenTLV/opentlv":
        raise ValueError("Unexpected source repository")
    paths = subprocess.check_output(
        ["git", "-C", str(core), "ls-tree", "-r", "--name-only", SOURCE_COMMIT,
         "--", "bindings/python"], text=True
    ).splitlines()
    expected = {path: path for path in paths}
    expected.update(EXTRA_FILES)
    entries = manifest["files"]
    actual = {entry["source"]: entry["destination"] for entry in entries}
    if len(entries) != len(actual) or actual != expected:
        raise ValueError("Inventory differs from the complete Python tree and explicit dependencies")
    destinations = {entry["destination"] for entry in entries}
    if len(destinations) != len(entries):
        raise ValueError("Duplicate destination")
    for entry in entries:
        original = subprocess.check_output(
            ["git", "-C", str(core), "show", f"{SOURCE_COMMIT}:{entry['source']}"]
        )
        imported = (ROOT / entry["destination"]).read_bytes()
        if hashlib.sha256(original).hexdigest() != entry["sha256"]:
            raise ValueError(f"Incorrect source hash: {entry['source']}")
        if imported != original:
            raise ValueError(f"Modified imported file: {entry['destination']}")
    # Ignore only disposable interpreter/test cache files.
    imported_paths = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "bindings/python").rglob("*")
        if path.is_file()
        and not {"__pycache__", ".pytest_cache"}.intersection(path.parts)
    }
    if imported_paths != set(paths):
        raise ValueError("Missing or extra files in bindings/python")
    print(f"Verified {len(entries)} imported files against Core {SOURCE_COMMIT}")
    print(f"Complete bindings/python tree: {len(paths)} files; "
          f"explicit dependencies and evidence: {len(EXTRA_FILES)} files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=ROOT.parent / "opentlv",
                        help="Core Git checkout containing the recorded commit")
    args = parser.parse_args()
    try:
        verify(args.core)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Migration verification failed: {error}\n")
