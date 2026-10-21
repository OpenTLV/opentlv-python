# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Timing collection must wait for the same attempt and exclude itself."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ci_timings as timings


def job(name, complete=True):
    return {"name": "checks / " + name, "status": "completed" if complete else "in_progress",
            "conclusion": "success" if complete else None,
            "started_at": "2026-10-20T10:00:00Z",
            "completed_at": "2026-10-20T10:00:10Z" if complete else None}


def test_waits_for_metadata_excludes_collector(monkeypatch):
    calls = []
    def fetch(repo, run, attempt):
        calls.append((repo, run, attempt))
        return [job("Python quality gate", len(calls) > 1), job("Python / linux-3.11"),
                job("Python timings", False)]
    monkeypatch.setattr(timings, "fetch_jobs", fetch)
    monkeypatch.setattr(timings.time, "sleep", lambda _: None)
    result = timings.measure("OpenTLV/opentlv-python", "100", "2", "python")
    assert calls == [("OpenTLV/opentlv-python", "100", "2")] * 2
    assert result["job_count"] == 2 and result["job_seconds"] == 20


def test_rejects_partial_report_after_bounded_retry(monkeypatch):
    calls = []
    monkeypatch.setattr(timings, "fetch_jobs", lambda *args:
                        calls.append(args) or [job("Python quality gate"), job("build", False)])
    monkeypatch.setattr(timings.time, "sleep", lambda _: None)
    with pytest.raises(ValueError, match="incomplete"):
        timings.measure("repo", "100", "2", "python")
    assert len(calls) == 6


def test_jobs_api_pagination_is_attempt_scoped(monkeypatch):
    urls = []
    def api(url):
        urls.append(url)
        return {"jobs": [job("build")] * (100 if len(urls) == 1 else 1)}
    monkeypatch.setattr(timings, "api", api)
    assert len(timings.fetch_jobs("repo", "100", "2")) == 101
    assert all("/attempts/2/jobs?" in url for url in urls)
    assert urls[-1].endswith("page=2")
