# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Stage or publish the verified upload set on TestPyPI or PyPI; never build or replace packages."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import urlopen
import zipfile

from build_support import ROOT, api, read, require, write
from ci_contract import REPOSITORY
from package_contract import DISTRIBUTION, check_sdist, check_wheel, wheel_name
from publish_release import WORKFLOW, verify_candidate, verify_published
from release import checked_dispatch, requested_tag, unused_tag

INDEXES = {"testpypi": "https://test.pypi.org", "pypi": "https://pypi.org"}
UPLOAD_URLS = {"testpypi": "https://test.pypi.org/legacy/", "pypi": "https://upload.pypi.org/legacy/"}
CANDIDATES = ROOT / "build/candidates"
WORK = ROOT / "build/pypi"


def requested_index():
    index = os.environ.get("PYPI_TARGET", "")
    require(index in INDEXES, "Select the testpypi or pypi package index")
    return index


def select_candidate(root, current):
    """Choose this run's newest candidate; a re-run of failed jobs keeps an earlier attempt's bytes."""
    candidates = {}
    for path in root.glob("*/manifest.json"):
        identity = read(path).get("identity", {})
        attempt = str(identity.get("run_attempt", ""))
        require(identity.get("run_id") == current["run_id"] and attempt.isdigit()
                and 0 < int(attempt) <= int(current["run_attempt"])
                and path.parent.name == "python-release-candidate-" + attempt
                and int(attempt) not in candidates, "Release candidate is not from this run")
        candidates[int(attempt)] = path.parent
    require(candidates, "Missing release candidate")
    attempt = max(candidates)
    return candidates[attempt], {**current, "run_attempt": str(attempt)}


def verify(root, tag, index):
    """Bind the upload to this run's Full CI, attested candidate and tag state."""
    current, package, pinned = checked_dispatch(tag)
    directory, producer = select_candidate(root, current)
    require(os.environ.get("GITHUB_WORKFLOW_REF") == REPOSITORY + "/" + WORKFLOW + "@refs/heads/main",
            "Package index publication requires the canonical workflow")
    require(os.environ.get("FULL_RESULT") == os.environ.get("ASSEMBLE_RESULT") == "success",
            "Package index publication requires successful Full/assembly jobs")
    published = os.environ.get("PUBLISH_RESULT")
    require(published == "success" or (index == "testpypi" and published == "skipped"),
            "PyPI requires the GitHub release published by this run")
    if published == "success":
        # The publisher created the tag and release in this run; both must match this candidate.
        releases = [item for item in api(f"repos/{REPOSITORY}/releases?per_page=100") if item.get("tag_name") == tag]
        require(len(releases) == 1, "Missing or duplicate GitHub release")
        verify_published(api(f"repos/{REPOSITORY}/releases/{releases[0]['id']}"), directory, tag,
                         current["commit"], False)
    else:
        # A TestPyPI rehearsal must not claim a tag that another run created.
        unused_tag(tag)
    return directory, package, verify_candidate(directory, tag, producer, package, pinned, current["run_attempt"])


def extract(directory, manifest, package, destination):
    """Copy the selected upload set out of the candidate and recheck every file's bytes and contract."""
    expected = {wheel_name(package, system): system for system in package["wheel_platforms"]}
    expected[f'{DISTRIBUTION}-{package["version"]}.tar.gz'] = None
    distributions = manifest.get("distributions", {})
    require(set(distributions) == set(expected), "Candidate upload set differs from the package policy")
    destination.mkdir(parents=True)
    files = {}
    with zipfile.ZipFile(directory / f'opentlv-python-{package["version"]}.zip') as archive:
        for name, item in sorted(distributions.items()):
            data = archive.read("dist/" + name)
            sha = hashlib.sha256(data).hexdigest()
            require(sha == item["sha256"] == manifest["files"]["dist/" + name] == manifest["files"][item["source"]]
                    and hashlib.sha256(archive.read(item["source"])).hexdigest() == sha,
                    "Selected distribution differs from its tested build")
            configuration = item["source"].split("/")[0]
            record = json.loads(archive.read(configuration + "/record.json"))
            require(record.get("status") == "success" and record["configuration"]["id"] == configuration
                    and (expected[name] is None or record["configuration"]["system"] == expected[name]),
                    "Selected distribution has no matching build record")
            path = destination / name
            path.write_bytes(data)
            if expected[name] is None:
                check_sdist(path, package)
            else:
                check_wheel(path, package, record["core"], expected[name])
            files[name] = sha
    return files


def index_files(index, version):
    """Return the files the index already holds for this version, by SHA-256."""
    try:
        with urlopen(f"{INDEXES[index]}/pypi/{DISTRIBUTION}/{version}/json", timeout=60) as response:
            release = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return {}
        raise
    return {item["filename"]: item["digests"]["sha256"] for item in release["urls"]}


def prepare(root, tag, index):
    directory, package, manifest = verify(root, tag, index)
    require(not WORK.exists(), "Package index work directory must be fresh")
    files = extract(directory, manifest, package, WORK / "dist")
    existing = index_files(index, package["version"])
    # Index files are immutable. A retry may complete a partial upload of the same bytes, but a
    # version that already holds other files or other bytes needs a new version instead.
    require(all(files.get(name) == sha for name, sha in existing.items()),
            "The package index already has different files for this version; release a new version")
    upload = WORK / "upload"
    upload.mkdir()
    for name in sorted(set(files) - set(existing)):
        (upload / name).write_bytes((WORK / "dist" / name).read_bytes())
    write(WORK / "plan.json", {"schema": 1, "index": index, "tag": tag, "version": package["version"],
                               "manifest": manifest["identity"], "files": files,
                               "already_published": sorted(existing), "upload": sorted(set(files) - set(existing))})
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"upload={'true' if set(files) - set(existing) else 'false'}\n")
        output.write(f"repository_url={UPLOAD_URLS[index]}\n")


def confirm(index, attempts=10, delay=15):
    """Require exactly the planned files and bytes on the index, then record a receipt."""
    plan = read(WORK / "plan.json")
    require(plan["index"] == index, "Package index differs from the plan")
    for attempt in range(attempts):
        existing = index_files(index, plan["version"])
        if existing == plan["files"]:
            break
        require(all(plan["files"].get(name) == sha for name, sha in existing.items()),
                "Package index files differ from the verified upload set")
        if attempt + 1 < attempts:
            time.sleep(delay)
    else:
        raise ValueError("Package index does not list the complete upload set")
    identity = plan["manifest"]
    write(WORK / "receipt.json", {
        "schema": 1, "kind": "python-package-index-release", "index": index, "repository": REPOSITORY,
        "project": f"{INDEXES[index]}/project/{DISTRIBUTION}/{plan['version']}/", "tag": plan["tag"],
        "version": plan["version"], "commit": identity["commit"], "run_id": int(identity["run_id"]),
        "run_attempt": int(identity["run_attempt"]), "files": plan["files"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "confirm"))
    args = parser.parse_args()
    index = requested_index()
    if args.command == "prepare":
        prepare(CANDIDATES, requested_tag(), index)
    else:
        confirm(index)


if __name__ == "__main__":
    main()
