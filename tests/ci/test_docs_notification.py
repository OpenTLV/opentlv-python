# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Exercise the actual notifier script without sending repository dispatches."""

import io
import json
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
import urllib.request

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import docs_notification as producer


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def test_notification_security_and_ci_ownership():
    notify = workflow("docs-notify.yml")
    assert notify["on"] == {"workflow_run": {"workflows": ["Python Main CI"],
                                           "types": ["completed"], "branches": ["main"]}}
    assert notify["permissions"] == {"contents": "read", "actions": "read"}
    assert notify["concurrency"]["cancel-in-progress"] == "false"
    job = notify["jobs"]["notify"]
    for guard in ("conclusion == 'success'", "event == 'push'", "head_branch == 'main'",
                  "path == '.github/workflows/python-main.yml'", "head_repository.full_name"):
        assert guard in job["if"]
    assert not any("checkout@" in step.get("uses", "") for step in job["steps"])
    download, dispatch = job["steps"]
    assert download["with"]["name"] == "docs-notification-${{ github.event.workflow_run.run_attempt }}"
    assert download["with"]["run-id"] == "${{ github.event.workflow_run.id }}"
    assert dispatch["env"]["DOCS_TOKEN"] == "${{ secrets.OPENTLV_DOCS_DISPATCH_TOKEN }}"
    main = workflow("python-main.yml")["jobs"]["docs_changes"]
    assert main["needs"] == ["checks"]
    assert main["steps"][0]["with"] == {"fetch-depth": "0", "persist-credentials": "false"}
    for name in ("python-pr.yml", "python-main.yml", "docs-notify.yml"):
        text = (ROOT / ".github/workflows" / name).read_text()
        assert "docs-full.yml" not in text
    assert "DOCS_DISPATCH_TOKEN" not in (ROOT / ".github/workflows/python-main.yml").read_text()


@pytest.mark.parametrize("path", ["docs/guides/python.md", "docs/validation/layout.md", "examples/query.py",
                                  "README.md", "CHANGELOG.md", "CONTRIBUTING.md", "src/README.md",
                                  ".github/workflows/docs-notify.yml"])
def test_documentation_inputs_are_relevant(path):
    assert producer.relevant(path)


@pytest.mark.parametrize("path", ["native/src/module.c", "src/opentlv/reader.py", "tests/python/test_reader.py",
                                  "requirements-dev.txt", "docs_other/file.md", ".github/workflows/python-full.yml"])
def test_unrelated_changes_are_not_relevant(path):
    assert not producer.relevant(path)


def test_successful_baseline_covers_cancelled_pushes_and_excludes_self_and_future():
    good = {"run_number": 10, "head_sha": "a" * 40, "event": "push", "status": "completed",
            "conclusion": "success", "head_branch": "main", "path": producer.WORKFLOW,
            "head_repository": {"full_name": producer.REPOSITORY}}
    runs = [good, dict(good, run_number=11, conclusion="cancelled"),
            dict(good, run_number=12, conclusion="failure"), dict(good, run_number=13),
            dict(good, run_number=14), dict(good, run_number=12, event="pull_request"),
            dict(good, run_number=12, head_repository={"full_name": "attacker/fork"})]
    assert producer.baseline(runs, 13) == "a" * 40
    assert producer.baseline(runs[1:], 13) == producer.ZERO


@pytest.mark.parametrize("files,expected", [(["docs/guides/python.md", "native/src/module.c"], True),
                                          (["src/opentlv/reader.py"], False)])
def test_main_records_exact_push_and_attempt_without_dispatch(tmp_path, monkeypatch, files, expected):
    monkeypatch.setattr(producer, "__file__", str(tmp_path / "scripts/docs_notification.py"))
    for key, value in {"GITHUB_REPOSITORY": producer.REPOSITORY, "GITHUB_EVENT_NAME": "push",
                       "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": "a" * 40,
                       "GITHUB_RUN_NUMBER": "10", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
                       "GH_TOKEN": "read-only-fixture-token"}.items():
        monkeypatch.setenv(key, value)
    def api(request, timeout):
        assert request.full_url.startswith("https://api.github.com/repos/OpenTLV/opentlv-python/actions/")
        assert request.get_method() == "GET"
        assert timeout == 30
        return io.BytesIO(b'{"workflow_runs": []}')
    monkeypatch.setattr(producer, "urlopen", api)
    def changed(root, before, after):
        assert (root, before, after) == (tmp_path, producer.ZERO, "a" * 40)
        return files
    monkeypatch.setattr(producer, "changed_files", changed)
    producer.main()
    assert json.loads((tmp_path / "build/docs-notification/notification.json").read_text()) == {
        "schema": 1, "repository": producer.REPOSITORY, "commit": "a" * 40, "ref": "main",
        "run_id": 123, "run_attempt": 2, "changed": expected}


def test_real_git_diff_handles_multicommit_push_deletion_and_rename(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], stderr=subprocess.PIPE).decode().strip()
    def commit():
        git("add", ".")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-m", "fixture")
        return git("rev-parse", "HEAD")
    git("init", "-b", "main")
    (tmp_path / "README.md").write_text("old\n")
    first = commit()
    (tmp_path / "README.md").write_text("new\n")
    docs = commit()
    (tmp_path / "native.c").write_text("/* unrelated */\n")
    last = commit()
    assert producer.changed_files(tmp_path, docs, last) == ["native.c"]
    assert "README.md" in producer.changed_files(tmp_path, first, last)
    git("mv", "README.md", "old.txt")
    renamed = commit()
    assert "README.md" in producer.changed_files(tmp_path, last, renamed)
    assert any(map(producer.relevant, producer.changed_files(tmp_path, producer.ZERO, last)))
    assert producer.changed_files(tmp_path, last, last) == []
    with pytest.raises(ValueError):
        producer.changed_files(tmp_path, "--bad-ref", last)


@pytest.fixture
def notification(tmp_path, monkeypatch):
    run = {"id": 123, "run_attempt": 2, "head_sha": "a" * 40, "status": "completed",
           "conclusion": "success", "event": "push", "head_branch": "main",
           "path": producer.WORKFLOW, "head_repository": {"full_name": producer.REPOSITORY}}
    record = {"schema": 1, "repository": producer.REPOSITORY, "commit": run["head_sha"],
              "ref": "main", "run_id": 123, "run_attempt": 2, "changed": True}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "event.json"))
    monkeypatch.setenv("GITHUB_REPOSITORY", producer.REPOSITORY)
    monkeypatch.setenv("DOCS_TOKEN", "fake-secret-do-not-log")
    (tmp_path / "evidence").mkdir()
    sent = []
    class Response:
        status = 204
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
    def send(request, **kwargs):
        sent.append(request)
        assert kwargs == {"timeout": 30}
        return Response()
    monkeypatch.setattr(urllib.request, "urlopen", send)
    def execute():
        (tmp_path / "event.json").write_text(json.dumps({"workflow_run": run}))
        (tmp_path / "evidence/notification.json").write_text(json.dumps(record))
        script = workflow("docs-notify.yml")["jobs"]["notify"]["steps"][-1]["run"]
        exec(compile(script, "docs-notify.yml", "exec"), {})
    return run, record, sent, execute


def test_exact_payload_and_destination(notification):
    run, record, sent, execute = notification
    execute()
    assert len(sent) == 1
    assert sent[0].full_url == "https://api.github.com/repos/OpenTLV/opentlv-docs/dispatches"
    assert sent[0].get_method() == "POST"
    assert sent[0].get_header("Authorization") == "Bearer fake-secret-do-not-log"
    assert json.loads(sent[0].data) == {"event_type": "component-docs-updated", "client_payload": {
        "source": "python", "repository": producer.REPOSITORY, "commit": run["head_sha"],
        "ref": "main", "run_id": 123}}


def test_unrelated_changes_need_no_token_or_dispatch(notification, monkeypatch):
    _, record, sent, execute = notification
    record["changed"] = False
    monkeypatch.delenv("DOCS_TOKEN")
    execute()
    assert not sent


@pytest.mark.parametrize("change", [{"event": "pull_request"}, {"conclusion": "failure"},
    {"status": "in_progress"}, {"path": ".github/workflows/evil.yml"}, {"head_branch": "feature"},
    {"head_repository": {"full_name": "attacker/fork"}}, {"head_sha": "b" * 40}, {"run_attempt": 3}])
def test_rejects_untrusted_or_mismatched_producer(notification, change):
    run, _, sent, execute = notification
    run.update(change)
    with pytest.raises(SystemExit, match="evidence"):
        execute()
    assert not sent


@pytest.mark.parametrize("change", [{"commit": "b" * 40}, {"run_id": 99}, {"run_attempt": 1},
    {"repository": "attacker/fork"}, {"changed": "false"}, {"schema": True}, {"extra": "data"}])
def test_rejects_stale_or_malformed_evidence(notification, change):
    _, record, sent, execute = notification
    record.update(change)
    with pytest.raises(SystemExit, match="evidence"):
        execute()
    assert not sent


def test_missing_authentication_fails_clearly(notification, monkeypatch):
    _, _, sent, execute = notification
    monkeypatch.setenv("DOCS_TOKEN", "")
    with pytest.raises(SystemExit, match="OPENTLV_DOCS_DISPATCH_TOKEN is required"):
        execute()
    assert not sent


@pytest.mark.parametrize("error", [HTTPError("https://fixture", code, "fake-secret-do-not-log", {}, None)
                                  for code in (401, 403, 404, 500)] + [URLError("fake-secret-do-not-log")])
def test_api_errors_are_clear_without_secret_values(notification, monkeypatch, error, capsys):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(SystemExit, match="Docs dispatch failed") as failure:
        notification[-1]()
    assert "fake-secret-do-not-log" not in str(failure.value) + str(capsys.readouterr())
