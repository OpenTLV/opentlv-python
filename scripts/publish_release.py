# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Publish an attested GitHub release after Full CI; never upload to a package index."""

import json
import os
from pathlib import Path
import re

from build_support import ROOT, api, digest, read, require, run, write
from ci_contract import REPOSITORY, definition_hashes
from release import preflight

WORKFLOW = ".github/workflows/python-release.yml"


def verify(directory):
    current, package, pinned = preflight()
    require(os.environ.get("GITHUB_WORKFLOW_REF") == REPOSITORY + "/" + WORKFLOW + "@refs/heads/main",
            "Release publication requires the canonical workflow")
    require(os.environ.get("PUBLISH_RELEASE") == "true" and
            os.environ.get("FULL_RESULT") == os.environ.get("ASSEMBLE_RESULT") == "success",
            "GitHub publication requires explicit opt-in and successful Full/assembly jobs")
    require(re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", package["version"]),
            "Python releases require a stable package version")
    manifest = read(directory / "manifest.json")
    require(manifest.get("schema") == 1 and manifest.get("kind") == "python-release-candidate"
            and manifest.get("publication_enabled") is False and manifest.get("identity") == current
            and manifest.get("package") == package and manifest.get("core_lock") == pinned
            and manifest.get("definitions") == definition_hashes(), "Candidate identity differs from this release")
    files = {"manifest.json", f"opentlv-python-{package['version']}.zip"}
    lines = (directory / "SHA256SUMS").read_text().splitlines()
    expected = sorted(f"{digest(directory / name)}  {name}" for name in files)
    require(sorted(lines) == expected and {p.name for p in directory.iterdir()} == files | {"SHA256SUMS"},
            "Release files or checksums differ from the candidate")
    for path in sorted(directory.iterdir()):
        require(path.is_file() and not path.is_symlink(), "Release assets must be regular files")
        run("gh", "attestation", "verify", path, "--repo", REPOSITORY,
            "--signer-workflow", REPOSITORY + "/" + WORKFLOW, "--source-digest", current["commit"])
    producer = api(f"repos/{REPOSITORY}/actions/runs/{current['run_id']}")
    require(producer.get("status") == "in_progress" and producer.get("conclusion") is None
            and producer.get("event") == "workflow_dispatch" and producer.get("head_branch") == "main"
            and producer.get("head_sha") == current["commit"] and producer.get("path") == WORKFLOW
            and str(producer.get("run_attempt")) == current["run_attempt"]
            and producer.get("head_repository", {}).get("full_name") == REPOSITORY,
            "Release producer is no longer the current trusted attempt")
    return current, package


def publish(directory):
    current, package = verify(directory)
    tag = "v" + package["version"]
    # A verified candidate alone is insufficient: create a tag and a real GitHub release.
    created = json.loads(run("gh", "api", f"repos/{REPOSITORY}/git/refs", "-X", "POST",
                             "-f", "ref=refs/tags/" + tag, "-f", "sha=" + current["commit"], capture=True))
    require(created.get("object", {}).get("sha") == current["commit"], "Unexpected created release tag")
    run("gh", "release", "create", tag, "--repo", REPOSITORY, "--verify-tag",
        "--title", "OpenTLV Python " + package["version"], "--generate-notes", *sorted(directory.iterdir()))
    released = api(f"repos/{REPOSITORY}/releases/tags/{tag}")
    require(released.get("tag_name") == tag and released.get("draft") is False
            and released.get("prerelease") is False and bool(released.get("published_at"))
            and type(released.get("id")) is int and released["id"] > 0, "GitHub release was not published")
    write(ROOT / "build/docs-release/release.json", {
        "schema": 1, "kind": "component-release", "status": "published", "source": "python",
        "repository": REPOSITORY, "commit": current["commit"], "workflow_commit": current["commit"],
        "tag": tag, "version": package["version"], "run_id": int(current["run_id"]),
        "run_attempt": int(current["run_attempt"]), "release_id": released["id"]})


if __name__ == "__main__":
    publish(ROOT / "build/release")
