# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Publish an attested GitHub release after Full CI; never upload to a package index."""

import json
import os
from pathlib import Path
import re

from build_support import ROOT, api, digest, read, require, run, write
from ci_contract import REPOSITORY, definition_hashes
from release import NOTES, preflight, requested_tag

WORKFLOW = ".github/workflows/python-release.yml"


def verify(directory, tag):
    current, package, pinned = preflight(tag)
    require(os.environ.get("GITHUB_WORKFLOW_REF") == REPOSITORY + "/" + WORKFLOW + "@refs/heads/main",
            "Release publication requires the canonical workflow")
    require(os.environ.get("PUBLISH_RELEASE") == "true" and
            os.environ.get("FULL_RESULT") == os.environ.get("ASSEMBLE_RESULT") == "success",
            "GitHub publication requires explicit opt-in and successful Full/assembly jobs")
    require(re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", package["version"]),
            "Python releases require a stable package version")
    manifest = read(directory / "manifest.json")
    require(manifest.get("schema") == 1 and manifest.get("kind") == "python-release-candidate"
            and manifest.get("publication_enabled") is False and manifest.get("tag") == tag
            and manifest.get("identity") == current
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


def verify_published(released, directory, tag, commit, draft):
    """Check the release text, uploaded bytes and tag before and after leaving draft."""
    require(released.get("tag_name") == tag and released.get("draft") is draft
            and released.get("prerelease") is False and type(released.get("id")) is int
            and released["id"] > 0 and (draft or bool(released.get("published_at"))),
            "Unexpected draft release" if draft else "GitHub release was not published")
    require((released.get("body") or "").strip() == NOTES.read_text(encoding="utf-8").strip(),
            "Published release notes differ")
    assets = released.get("assets", [])
    paths = {path.name: path for path in directory.iterdir()}
    require(len(assets) == len(paths) and {asset.get("name") for asset in assets} == set(paths),
            "Published release asset set differs")
    for asset in assets:
        path = paths[asset["name"]]
        require(asset.get("state") == "uploaded" and asset.get("size") == path.stat().st_size
                and asset.get("digest") == "sha256:" + digest(path), "Published asset digest differs")
    require(api(f"repos/{REPOSITORY}/commits/{tag}").get("sha") == commit, "Release tag changed")


def publish(directory, tag):
    current, package = verify(directory, tag)
    # A verified candidate alone is insufficient: create a tag and a real GitHub release.
    created = json.loads(run("gh", "api", f"repos/{REPOSITORY}/git/refs", "-X", "POST",
                             "-f", "ref=refs/tags/" + tag, "-f", "sha=" + current["commit"], capture=True))
    require(created.get("object", {}).get("sha") == current["commit"], "Unexpected created release tag")
    # Upload as a draft first, so nothing is published before the uploaded bytes are checked.
    run("gh", "release", "create", tag, "--repo", REPOSITORY, "--verify-tag", "--draft",
        "--title", "OpenTLV Python " + package["version"], "--notes-file", NOTES, *sorted(directory.iterdir()))
    drafts = [item for item in api(f"repos/{REPOSITORY}/releases?per_page=100") if item.get("tag_name") == tag]
    require(len(drafts) == 1, "Missing or duplicate draft release")
    verify_published(api(f"repos/{REPOSITORY}/releases/{drafts[0]['id']}"), directory, tag,
                     current["commit"], True)
    run("gh", "release", "edit", tag, "--repo", REPOSITORY, "--draft=false")
    released = api(f"repos/{REPOSITORY}/releases/{drafts[0]['id']}")
    verify_published(released, directory, tag, current["commit"], False)
    write(ROOT / "build/docs-release/release.json", {
        "schema": 1, "kind": "component-release", "status": "published", "source": "python",
        "repository": REPOSITORY, "commit": current["commit"], "workflow_commit": current["commit"],
        "tag": tag, "version": package["version"], "run_id": int(current["run_id"]),
        "run_attempt": int(current["run_attempt"]), "release_id": released["id"]})


if __name__ == "__main__":
    publish(ROOT / "build/release", requested_tag())
