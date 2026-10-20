# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Select Core before CMake executes any dependency build files."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

from build_support import read, require, run, write
from verified_core import REPOSITORY, lock, resolve


def in_ci():
    return any(os.environ.get(key, "").lower() not in ("", "0", "false")
               for key in ("CI", "GITHUB_ACTIONS"))


def git_identity(source):
    require((source / ".git").exists(), "Core source must be an explicit Git checkout")
    top = Path(run("git", "-C", source, "rev-parse", "--show-toplevel", capture=True)).resolve()
    require(top == source.resolve(), "Core source must be the Git repository root")
    commit = run("git", "-C", source, "rev-parse", "HEAD", capture=True)
    require(re.fullmatch("[0-9a-f]{40}", commit), "Core checkout has no exact commit")
    dirty = bool(run("git", "-C", source, "status", "--porcelain", "--untracked-files=all", capture=True))
    tag = run("git", "-C", source, "describe", "--tags", "--abbrev=0",
              "--match", "v[0-9]*", "--match", "[0-9]*", "HEAD", capture=True)
    tag_commit = run("git", "-C", source, "rev-list", "-n", "1", tag, capture=True)
    # Match Core's preference for stable tags when several tags share a commit.
    tags = run("git", "-C", source, "tag", "--points-at", tag_commit,
               "--list", "v[0-9]*", "[0-9]*", "--sort=-version:refname", capture=True).splitlines()
    stable = [t for t in tags if re.fullmatch(r"v?\d+\.\d+\.\d+", t)]
    prerelease = [t for t in tags if re.fullmatch(r"v?\d+\.\d+\.\d+-[0-9A-Za-z.-]+", t)]
    require(stable or prerelease, "Core checkout has no supported version tag")
    return {"commit": commit, "version": (stable or prerelease)[0].removeprefix("v"),
            "dirty": dirty}


def select(work, probe, configuration, source=None, require_release=False):
    selected = lock(require_release)
    work.mkdir(parents=True, exist_ok=True)
    if source is not None:
        require(not require_release and not in_ci(),
                "Local Core overrides are development-only and forbidden in CI/verified-release builds")
        source = source.resolve()
        identity = git_identity(source)
        return {"mode": "local-source", "verified": False, **identity,
                "source_dir": str(source), "source_path": str(source),
                "repository": REPOSITORY, "locked_commit": selected["commit"]}
    if selected["release_tag"] is not None:
        # Never fall back to Git following a failed artifact verification.
        attempt = Path(tempfile.mkdtemp(prefix="release-", dir=work))
        return resolve(attempt / "assets", probe, configuration)
    source = work / "source"
    if not source.exists():
        run("git", "clone", "--no-checkout", f"https://github.com/{REPOSITORY}.git", source)
        run("git", "-C", source, "checkout", "--detach", selected["commit"])
    identity = git_identity(source)
    require(identity["commit"] == selected["commit"], "Core checkout differs from locked commit")
    require(identity["version"] == selected["version"], "Core checkout differs from locked version")
    require(not identity["dirty"], "Pinned Core checkout is modified")
    return {"mode": "pinned-git", "verified": False, **identity,
            "source_dir": str(source.resolve()), "source_path": str(source.resolve()),
            "repository": REPOSITORY}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--configuration", default="Release")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--require-release", action="store_true")
    args = parser.parse_args()
    # A failed reconfigure must not leave apparently valid previous evidence.
    args.output.unlink(missing_ok=True)
    try:
        evidence = select(args.work, read(args.probe), args.configuration,
                          args.source, args.require_release)
        write(args.output, evidence)
        print(f"Python Core: {evidence['mode']} {evidence['version']} "
              f"{evidence['commit']} (attested={evidence['verified']})")
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Core dependency verification failed: {error}\n")


if __name__ == "__main__":
    main()
