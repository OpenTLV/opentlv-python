# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Prepare a verified Python release candidate; never create tags or publish packages."""

import argparse
from pathlib import Path
import os
import shutil
import tempfile
import zipfile

from build_support import digest, read, require, write
from ci_contract import REPOSITORY, definition_hashes, identity, validate_records
from package_contract import policy, validate_bundle
from verified_core import lock


def preflight():
    pinned = lock(True)
    package = policy()
    current = identity()
    require(current["hosted"] and not current["dirty"] and current["repository"] == REPOSITORY,
            "Release preparation requires the official clean hosted checkout")
    require(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and
            os.environ.get("GITHUB_REF") == "refs/heads/main",
            "Dispatch release preparation from main")
    return current, package, pinned


def assemble(evidence, quality_path, output):
    current, package, pinned = preflight()
    definitions = definition_hashes()
    require(not output.exists(), "Release output must be fresh")
    paths = sorted(evidence.rglob("record.json"))
    records = [read(path) for path in paths]
    quality = read(quality_path)
    expected = validate_records(records, "full", current, definitions, quality["checks"], True)
    require(quality == expected, "Full quality report differs from this run's package records")
    for path, record in zip(paths, records):
        validate_bundle(path.parent / "ci", record, package)
    # Construct everything in a private fresh directory. A failed assembly leaves no candidate.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="python-candidate-", dir=output.parent) as temporary:
        work = Path(temporary)
        payload = work / "payload"
        files = {}
        for path, record in zip(paths, records):
            configuration = record["configuration"]["id"]
            destination = payload / configuration
            for relative, sha in record["artifacts"].items():
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path.parent / "ci" / relative, target)
                require(digest(target) == sha, "Package changed during release assembly")
                files[target.relative_to(payload).as_posix()] = sha
            write(destination / "record.json", record)
            files[configuration + "/record.json"] = digest(destination / "record.json")
        write(payload / "quality.json", quality)
        files["quality.json"] = digest(payload / "quality.json")
        manifest = {"schema": 1, "kind": "python-release-candidate", "publication_enabled": False,
                    "package": package, "core_lock": pinned, "identity": current,
                    "definitions": definitions, "configurations": expected["configurations"],
                    "run_url": f'https://github.com/{REPOSITORY}/actions/runs/{current["run_id"]}/attempts/{current["run_attempt"]}',
                    "files": files}
        candidate = work / "candidate"
        candidate.mkdir()
        write(candidate / "manifest.json", manifest)
        archive = candidate / f'opentlv-python-{package["version"]}.zip'
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(payload.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(payload).as_posix())
            bundle.write(candidate / "manifest.json", "manifest.json")
        sums = "".join(f"{digest(path)}  {path.name}\n" for path in sorted(candidate.iterdir()))
        (candidate / "SHA256SUMS").write_text(sums, encoding="utf-8")
        require(preflight() == (current, package, pinned) and definition_hashes() == definitions,
                "Release inputs changed during assembly")
        candidate.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    prepare = commands.add_parser("assemble")
    prepare.add_argument("--evidence", type=Path, required=True)
    prepare.add_argument("--quality", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "preflight":
        preflight()
    else:
        assemble(args.evidence, args.quality, args.output)


if __name__ == "__main__":
    main()
