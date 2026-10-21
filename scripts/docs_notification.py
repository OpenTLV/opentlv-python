# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Record documentation changes after successful Main CI, without dispatch credentials."""

import json
import os
from pathlib import Path
import re
import subprocess
from urllib.request import Request, urlopen

REPOSITORY = "OpenTLV/opentlv-python"
WORKFLOW = ".github/workflows/python-main.yml"
ZERO = "0" * 40
FILES = {"README.md", "CONTRIBUTING.md", "CHANGELOG.md", "src/README.md", "native/README.md",
         WORKFLOW, ".github/workflows/docs-notify.yml", "scripts/docs_notification.py"}


def relevant(path):
    return path in FILES or path.startswith(("docs/", "examples/"))


def baseline(runs, number):
    # Include changes from cancelled/failed pushes since the previous success.
    previous = [run for run in runs if run.get("event") == "push"
                and run.get("status") == "completed" and run.get("conclusion") == "success"
                and run.get("head_branch") == "main" and run.get("path") == WORKFLOW
                and run.get("head_repository", {}).get("full_name") == REPOSITORY
                and type(run.get("run_number")) is int and run["run_number"] < number
                and re.fullmatch(r"[0-9a-f]{40}", run.get("head_sha", ""))]
    return max(previous, key=lambda run: run["run_number"])["head_sha"] if previous else ZERO


def changed_files(root, before, commit):
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (before, commit)) or commit == ZERO:
        raise ValueError("Documentation detection requires exact Git revisions")
    command = (["ls-tree", "-r", "--name-only", "-z", commit] if before == ZERO else
               ["diff", "--no-renames", "--name-only", "-z", before, commit, "--"])
    output = subprocess.check_output(["git", "-C", str(root), *command])
    return [name for name in output.decode("utf-8").split("\0") if name]


def main():
    root = Path(__file__).resolve().parents[1]
    if (os.environ["GITHUB_REPOSITORY"] != REPOSITORY or os.environ["GITHUB_EVENT_NAME"] != "push"
            or os.environ["GITHUB_REF"] != "refs/heads/main"):
        raise ValueError("Documentation evidence requires an official main push")
    commit = os.environ["GITHUB_SHA"]
    request = Request(f"https://api.github.com/repos/{REPOSITORY}/actions/workflows/python-main.yml/runs"
                      "?event=push&status=success&branch=main&per_page=100",
                      headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                               "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"})
    with urlopen(request, timeout=30) as response:
        runs = json.load(response)["workflow_runs"]
    before = baseline(runs, int(os.environ["GITHUB_RUN_NUMBER"]))
    record = {"schema": 1, "repository": REPOSITORY, "commit": commit, "ref": "main",
              "run_id": int(os.environ["GITHUB_RUN_ID"]),
              "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
              "changed": any(relevant(path) for path in changed_files(root, before, commit))}
    destination = root / "build/docs-notification/notification.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
