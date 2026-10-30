# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Stage the verified upload set on TestPyPI or promote it to PyPI; never build or replace packages."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import zipfile

from build_support import ROOT, api, read, require, write
from ci_contract import REPOSITORY
from package_contract import DISTRIBUTION, check_sdist, check_wheel, policy, upload_names
from package_index import INDEXES, UPLOAD_URLS, index_files, index_release, provenance
from publish_release import WORKFLOW, staged_candidate, verify_candidate, verify_published
from release import checked_dispatch, requested_tag, unused_tag

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
    """Bind a staging upload to this run's Full CI, or a production upload to the staged candidate."""
    current, package, pinned = checked_dispatch(tag)
    require(os.environ.get("GITHUB_WORKFLOW_REF") == REPOSITORY + "/" + WORKFLOW + "@refs/heads/main",
            "Package index publication requires the canonical workflow")
    published = os.environ.get("PUBLISH_RESULT")
    if index == "pypi":
        require(published == "success", "PyPI requires the GitHub release published by this run")
        directory, manifest, _ = staged_candidate(root, tag, current, package, pinned)
        # The publisher created the tag and release in this run; both must match this candidate.
        releases = [item for item in api(f"repos/{REPOSITORY}/releases?per_page=100") if item.get("tag_name") == tag]
        require(len(releases) == 1, "Missing or duplicate GitHub release")
        verify_published(api(f"repos/{REPOSITORY}/releases/{releases[0]['id']}"), directory, tag,
                         current["commit"], False)
        return directory, package, manifest
    require(os.environ.get("FULL_RESULT") == os.environ.get("ASSEMBLE_RESULT") == "success",
            "Package index publication requires successful Full/assembly jobs")
    require(published == "skipped", "TestPyPI staging leaves the tag and GitHub release to the promotion")
    directory, producer = select_candidate(root, current)
    # Staging must not claim a tag that another run created.
    unused_tag(tag)
    return directory, package, verify_candidate(directory, tag, producer, package, pinned, current["run_attempt"])


def extract(directory, manifest, package, destination):
    """Copy the selected upload set out of the candidate and recheck every file's bytes and contract."""
    expected = upload_names(package)
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
        # The Full gate accepts an upload set only after every configuration installed and tested it.
        quality = json.loads(archive.read("quality.json"))
        require(quality.get("upload") == distributions, "Candidate upload set was not verified by Full CI")
    return files


def attested(index, version, name):
    """Whether the index holds this file's provenance; a bundle from any other publisher fails."""
    record = provenance(index, version, name)
    if record is None:
        return False
    bundles = record.get("attestation_bundles", [])
    for bundle in bundles:
        publisher = bundle.get("publisher", {})
        require(publisher.get("kind") == "GitHub"
                and str(publisher.get("repository", "")).casefold() == REPOSITORY.casefold()
                and publisher.get("workflow") == Path(WORKFLOW).name and publisher.get("environment") == index
                and bundle.get("attestations"),
                "Package index provenance does not name this workflow and environment: " + name)
    return bool(bundles)


def check_metadata(release, package):
    """Require the single, dependency-free distribution as the index parsed it."""
    info = release.get("info", {})
    require(info.get("name") == DISTRIBUTION and info.get("version") == package["version"]
            and info.get("requires_python") == package["requires_python"] and not info.get("requires_dist"),
            "Package index metadata differs from the verified distribution")


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
    """Require exactly the planned files, bytes, metadata and provenance on the index, then record a receipt."""
    plan = read(WORK / "plan.json")
    require(plan["index"] == index, "Package index differs from the plan")
    for attempt in range(attempts):
        existing = index_files(index, plan["version"])
        require(all(plan["files"].get(name) == sha for name, sha in existing.items()),
                "Package index files differ from the verified upload set")
        if existing == plan["files"] and all(attested(index, plan["version"], name) for name in existing):
            break
        if attempt + 1 < attempts:
            time.sleep(delay)
    else:
        raise ValueError("Package index does not list the complete upload set with its provenance")
    check_metadata(index_release(index, plan["version"]), policy())
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
