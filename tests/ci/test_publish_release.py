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
                "tag": "v0.1.0", "identity": current, "package": package, "core_lock": pinned, "definitions": definitions}
    write(directory / "manifest.json", manifest)
    (directory / "opentlv-python-0.1.0.zip").write_bytes(b"attested-candidate-fixture")
    (directory / "SHA256SUMS").write_text("".join(f"{digest(path)}  {path.name}\n"
                                               for path in sorted(directory.iterdir())))
    notes = tmp_path / "release-notes.md"
    notes.write_text("# OpenTLV Python v0.1.0\n\n- Fixture release.\n", encoding="utf-8")
    monkeypatch.setattr(release, "NOTES", notes)
    monkeypatch.setattr(release, "preflight", lambda tag: (current, package, pinned))
    monkeypatch.setattr(release, "definition_hashes", lambda: definitions)
    monkeypatch.setattr(release, "ROOT", tmp_path)
    for key, value in {"GITHUB_WORKFLOW_REF": release.REPOSITORY + "/" + release.WORKFLOW + "@refs/heads/main",
                       "PUBLISH_RELEASE": "true", "FULL_RESULT": "success", "ASSEMBLE_RESULT": "success"}.items():
        monkeypatch.setenv(key, value)
    producer = {"status": "in_progress", "conclusion": None, "event": "workflow_dispatch",
                "head_branch": "main", "head_sha": current["commit"], "path": release.WORKFLOW,
                "run_attempt": 2, "head_repository": {"full_name": release.REPOSITORY}}
    # The created release starts as a draft; `gh release edit --draft=false` publishes it.
    published = {"id": 456, "tag_name": "v0.1.0", "draft": True, "prerelease": False,
                 "published_at": None, "body": notes.read_text(encoding="utf-8"),
                 "assets": [{"name": path.name, "state": "uploaded", "size": path.stat().st_size,
                             "digest": "sha256:" + digest(path)} for path in directory.iterdir()]}
    tag = {"sha": current["commit"]}

    def api(path):
        if "/actions/" in path:
            return producer
        if path.endswith("/commits/v0.1.0"):
            return tag
        if "/releases?" in path:
            return [{"id": 1, "tag_name": "v0.0.9"}, published]
        assert path.endswith("/releases/456")
        return published
    monkeypatch.setattr(release, "api", api)
    commands = []
    def run(*args, **kwargs):
        commands.append(args)
        if args[:2] == ("gh", "api"):
            return json.dumps({"object": {"sha": current["commit"]}})
        if args[:3] == ("gh", "release", "edit"):
            published.update(draft=False, published_at="2026-10-21T12:00:00Z")
    monkeypatch.setattr(release, "run", run)
    return directory, current, producer, published, commands


def test_opted_in_verified_release_emits_published_receipt(candidate):
    directory, current, _, _, commands = candidate
    release.publish(directory, "v0.1.0")
    receipt = json.loads((release.ROOT / "build/docs-release/release.json").read_text())
    assert receipt == {"schema": 1, "kind": "component-release", "status": "published", "source": "python",
                       "repository": release.REPOSITORY, "commit": current["commit"],
                       "workflow_commit": current["commit"], "tag": "v0.1.0", "version": "0.1.0",
                       "run_id": 123, "run_attempt": 2, "release_id": 456}
    assert sum(command[:3] == ("gh", "attestation", "verify") for command in commands) == 3
    create = next(command for command in commands if command[:3] == ("gh", "release", "create"))
    assert {"--verify-tag", "--draft", "--notes-file"} <= set(create)
    assert "--generate-notes" not in create
    assert commands[-1] == ("gh", "release", "edit", "v0.1.0", "--repo", release.REPOSITORY, "--draft=false")
    created = next(command for command in commands if command[:2] == ("gh", "api"))
    assert "ref=refs/tags/v0.1.0" in created and create[3] == "v0.1.0"


def test_requested_tag_must_match_the_assembled_candidate(candidate):
    directory, _, _, _, commands = candidate
    with pytest.raises(ValueError, match="Candidate identity"):
        release.publish(directory, "v0.1.1")
    assert not commands


@pytest.mark.parametrize("change", ["body", "digest", "size", "missing", "state", "tag"])
def test_unverified_draft_is_never_published(candidate, change):
    directory, _, _, published, commands = candidate
    asset = published["assets"][0]
    if change == "body":
        published["body"] = "Generated notes"
    elif change == "digest":
        asset["digest"] = "sha256:" + "0" * 64
    elif change == "size":
        asset["size"] += 1
    elif change == "missing":
        published["assets"].pop()
    elif change == "state":
        asset["state"] = "starter"
    else:
        release.api(f"repos/{release.REPOSITORY}/commits/v0.1.0")["sha"] = "b" * 40
    with pytest.raises(ValueError):
        release.publish(directory, "v0.1.0")
    assert not any(command[:3] == ("gh", "release", "edit") for command in commands)
    assert not (release.ROOT / "build/docs-release/release.json").exists()


@pytest.mark.parametrize("key,value", [("PUBLISH_RELEASE", "false"), ("FULL_RESULT", "failure"),
                                     ("ASSEMBLE_RESULT", "skipped"), ("GITHUB_WORKFLOW_REF", "other")])
def test_failed_gate_or_missing_opt_in_never_mutates_remote(candidate, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        release.publish(candidate[0], "v0.1.0")
    assert not candidate[-1]


@pytest.mark.parametrize("change", [{"status": "completed"}, {"run_attempt": 1}, {"head_sha": "b" * 40},
                                    {"event": "push"}, {"head_repository": {"full_name": "fork/python"}}])
def test_cancelled_or_changed_producer_cannot_create_release(candidate, change):
    candidate[2].update(change)
    with pytest.raises(ValueError, match="producer"):
        release.publish(candidate[0], "v0.1.0")
    assert all(command[:3] == ("gh", "attestation", "verify") for command in candidate[-1])


def test_modified_bytes_and_stale_candidate_identity_cannot_publish(candidate):
    directory = candidate[0]
    (directory / "opentlv-python-0.1.0.zip").write_bytes(b"modified")
    with pytest.raises(ValueError, match="checksums"):
        release.publish(directory, "v0.1.0")
    assert not candidate[-1]
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["identity"]["run_attempt"] = "1"
    write(directory / "manifest.json", manifest)
    with pytest.raises(ValueError, match="identity"):
        release.publish(directory, "v0.1.0")


def test_failed_attestation_or_publication_emits_no_receipt(candidate, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("attestation failed")
    monkeypatch.setattr(release, "run", fail)
    with pytest.raises(RuntimeError):
        release.publish(candidate[0], "v0.1.0")
    assert not (release.ROOT / "build/docs-release/release.json").exists()


def test_draft_release_cannot_emit_published_receipt(candidate, monkeypatch):
    commands = candidate[-1]
    monkeypatch.setattr(release, "run", lambda *args, **kwargs: commands.append(args) or (
        json.dumps({"object": {"sha": "a" * 40}}) if args[:2] == ("gh", "api") else None))
    with pytest.raises(ValueError, match="not published"):
        release.publish(candidate[0], "v0.1.0")
    assert not (release.ROOT / "build/docs-release/release.json").exists()
