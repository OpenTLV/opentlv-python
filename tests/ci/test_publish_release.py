# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""GitHub release publication requires exact attested candidate evidence and opt-in."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import publish_release as release
from build_support import digest, write


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    current = {"repository": release.REPOSITORY, "commit": "a" * 40, "run_id": "123", "run_attempt": "2",
               "hosted": True, "dirty": False}
    package = {"version": "0.1.0"}
    pinned = {"release_tag": "v0.7.0"}
    definitions = {"script.py": "b" * 64}
    directory = tmp_path / "release"
    directory.mkdir()
    manifest = {"schema": 1, "kind": "python-release-candidate", "publication_enabled": False,
                "identity": current, "package": package, "core_lock": pinned, "definitions": definitions}
    write(directory / "manifest.json", manifest)
    (directory / "opentlv-python-0.1.0.zip").write_bytes(b"attested-candidate-fixture")
    (directory / "SHA256SUMS").write_text("".join(f"{digest(path)}  {path.name}\n"
                                               for path in sorted(directory.iterdir())))
    monkeypatch.setattr(release, "preflight", lambda: (current, package, pinned))
    monkeypatch.setattr(release, "definition_hashes", lambda: definitions)
    monkeypatch.setattr(release, "ROOT", tmp_path)
    for key, value in {"GITHUB_WORKFLOW_REF": release.REPOSITORY + "/" + release.WORKFLOW + "@refs/heads/main",
                       "PUBLISH_RELEASE": "true", "FULL_RESULT": "success", "ASSEMBLE_RESULT": "success"}.items():
        monkeypatch.setenv(key, value)
    producer = {"status": "in_progress", "conclusion": None, "event": "workflow_dispatch",
                "head_branch": "main", "head_sha": current["commit"], "path": release.WORKFLOW,
                "run_attempt": 2, "head_repository": {"full_name": release.REPOSITORY}}
    published = {"id": 456, "tag_name": "v0.1.0", "draft": False, "prerelease": False,
                 "published_at": "2026-10-21T12:00:00Z"}
    monkeypatch.setattr(release, "api", lambda path: producer if "/actions/" in path else published)
    commands = []
    def run(*args, **kwargs):
        commands.append(args)
        if args[:2] == ("gh", "api"):
            return json.dumps({"object": {"sha": current["commit"]}})
    monkeypatch.setattr(release, "run", run)
    return directory, current, producer, published, commands


def test_opted_in_verified_release_emits_published_receipt(candidate):
    directory, current, _, _, commands = candidate
    release.publish(directory)
    receipt = json.loads((release.ROOT / "build/docs-release/release.json").read_text())
    assert receipt == {"schema": 1, "kind": "component-release", "status": "published", "source": "python",
                       "repository": release.REPOSITORY, "commit": current["commit"],
                       "workflow_commit": current["commit"], "tag": "v0.1.0", "version": "0.1.0",
                       "run_id": 123, "run_attempt": 2, "release_id": 456}
    assert sum(command[:3] == ("gh", "attestation", "verify") for command in commands) == 3
    assert any(command[:3] == ("gh", "release", "create") and "--verify-tag" in command for command in commands)


@pytest.mark.parametrize("key,value", [("PUBLISH_RELEASE", "false"), ("FULL_RESULT", "failure"),
                                     ("ASSEMBLE_RESULT", "skipped"), ("GITHUB_WORKFLOW_REF", "other")])
def test_failed_gate_or_missing_opt_in_never_mutates_remote(candidate, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        release.publish(candidate[0])
    assert not candidate[-1]


@pytest.mark.parametrize("change", [{"status": "completed"}, {"run_attempt": 1}, {"head_sha": "b" * 40},
                                    {"event": "push"}, {"head_repository": {"full_name": "fork/python"}}])
def test_cancelled_or_changed_producer_cannot_create_release(candidate, change):
    candidate[2].update(change)
    with pytest.raises(ValueError, match="producer"):
        release.publish(candidate[0])
    assert all(command[:3] == ("gh", "attestation", "verify") for command in candidate[-1])


def test_modified_bytes_and_stale_candidate_identity_cannot_publish(candidate):
    directory = candidate[0]
    (directory / "opentlv-python-0.1.0.zip").write_bytes(b"modified")
    with pytest.raises(ValueError, match="checksums"):
        release.publish(directory)
    assert not candidate[-1]
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["identity"]["run_attempt"] = "1"
    write(directory / "manifest.json", manifest)
    with pytest.raises(ValueError, match="identity"):
        release.publish(directory)


def test_failed_attestation_or_publication_emits_no_receipt(candidate, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("attestation failed")
    monkeypatch.setattr(release, "run", fail)
    with pytest.raises(RuntimeError):
        release.publish(candidate[0])
    assert not (release.ROOT / "build/docs-release/release.json").exists()


def test_draft_release_cannot_emit_published_receipt(candidate):
    candidate[3]["draft"] = True
    with pytest.raises(ValueError, match="not published"):
        release.publish(candidate[0])
    assert not (release.ROOT / "build/docs-release/release.json").exists()
