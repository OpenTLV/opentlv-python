# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Execute the notifier's real inline code with mocked HTTP, never real dispatches."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import yaml

ROOT = next(path for path in Path(__file__).resolve().parents if (path / ".github/workflows").is_dir())
SOURCE = ROOT.name.removeprefix("opentlv-")
REPOSITORY = "OpenTLV/opentlv-" + SOURCE
WORKFLOW = ".github/workflows/" + ("release.yml" if SOURCE == "lua" else "python-release.yml")


class ReleaseNotificationTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.load((ROOT / ".github/workflows/docs-release-notify.yml").read_text(), Loader=yaml.BaseLoader)
        self.run = {"id": 123, "run_attempt": 2, "head_sha": "a" * 40, "status": "completed",
                    "conclusion": "success", "event": "workflow_dispatch", "head_branch": "main",
                    "path": WORKFLOW, "head_repository": {"full_name": REPOSITORY}}
        self.receipt = {"schema": 1, "kind": "component-release", "status": "published", "source": SOURCE,
                        "repository": REPOSITORY, "commit": "a" * 40, "workflow_commit": "a" * 40,
                        "tag": "v0.1.0", "version": "0.1.0", "run_id": 123, "run_attempt": 2, "release_id": 456}
        self.sent = []
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        previous = Path.cwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)
        (self.work / "evidence").mkdir()
        env = patch.dict(os.environ, {"GITHUB_REPOSITORY": REPOSITORY, "DOCS_TOKEN": "fixture-secret",
                                     "GITHUB_EVENT_PATH": str(self.work / "event.json")})
        env.start()
        self.addCleanup(env.stop)

    def execute(self, failure=None):
        (self.work / "event.json").write_text(json.dumps({"workflow_run": self.run}))
        (self.work / "evidence/release.json").write_text(json.dumps(self.receipt))
        class Response:
            status = 204
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        def send(request, **kwargs):
            if failure:
                raise failure
            self.sent.append(request)
            return Response()
        script = self.workflow["jobs"]["notify"]["steps"][-1]["run"]
        with patch("urllib.request.urlopen", send):
            exec(compile(script, "docs-release-notify.yml", "exec"), {})

    def test_exact_payload_and_fixed_destination(self):
        self.execute()
        self.assertEqual(self.sent[0].full_url, "https://api.github.com/repos/OpenTLV/opentlv-docs/dispatches")
        self.assertEqual(json.loads(self.sent[0].data), {"event_type": "component-release-published", "client_payload": {
            "source": SOURCE, "repository": REPOSITORY, "commit": "a" * 40,
            "ref": "v0.1.0", "run_id": 123, "run_attempt": 2}})

    def test_preparation_forged_and_stale_receipts_never_dispatch(self):
        for change in ({"status": "prepared"}, {"kind": "python-release-candidate"}, {"commit": "b" * 40},
                       {"run_id": 124}, {"run_attempt": 1}, {"source": "other"}, {"repository": "fork/source"},
                       {"tag": "main"}, {"version": "0.2.0"}, {"release_id": True}, {"schema": True}):
            with self.subTest(change=change), patch.dict(self.receipt, change), self.assertRaises(SystemExit):
                self.execute()
        self.assertFalse(self.sent)

    def test_untrusted_producer_never_dispatches(self):
        for change in ({"event": "pull_request"}, {"conclusion": "failure"}, {"head_branch": "feature"},
                       {"path": ".github/workflows/other.yml"}, {"head_repository": {"full_name": "fork/source"}}):
            with patch.dict(self.run, change), self.assertRaises(SystemExit):
                self.execute()
        self.assertFalse(self.sent)

    def test_authentication_and_network_failures_do_not_expose_secret(self):
        with patch.dict(os.environ, {"DOCS_TOKEN": ""}), self.assertRaisesRegex(SystemExit, "TOKEN"):
            self.execute()
        for error in (HTTPError("fixture", 403, "fixture-secret", {}, None), URLError("fixture-secret")):
            with self.assertRaises(SystemExit) as result:
                self.execute(error)
            self.assertNotIn("fixture-secret", str(result.exception))

    def test_privileged_step_has_no_checkout_and_requires_successful_publication(self):
        job = self.workflow["jobs"]["notify"]
        self.assertIn("event == 'workflow_dispatch'", job["if"])
        self.assertEqual(self.workflow["permissions"], {"contents": "read", "actions": "read"})
        self.assertFalse(any("checkout@" in step.get("uses", "") for step in job["steps"]))
        self.assertIn("listJobsForWorkflowRunAttempt", job["steps"][0]["with"]["script"])
        for step in job["steps"][1:]:
            self.assertEqual(step["if"], "steps.producer.outputs.published == 'true'")
        self.assertEqual(job["steps"][1]["with"]["name"], "component-release-${{ github.event.workflow_run.run_attempt }}")
        self.assertEqual(job["steps"][-1]["env"], {"DOCS_TOKEN": "${{ secrets.OPENTLV_DOCS_DISPATCH_TOKEN }}"})


if __name__ == "__main__":
    unittest.main()
