# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Execute the real workflow shell steps, including macOS Bash 3.2 in the matrix."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def bash_executable():
    override = os.environ.get("OPENTLV_TEST_BASH")
    if override:
        return str(Path(override).resolve())
    if os.name == "nt":
        # GitHub uses Git Bash; System32/bash.exe is a WSL launcher, not this shell.
        git = shutil.which("git")
        if git:
            candidate = Path(git).resolve().parents[1] / "bin/bash.exe"
            if candidate.is_file():
                return str(candidate)
    else:
        executable = shutil.which("bash")
        if executable:
            return executable
    pytest.fail("Bash is required; set OPENTLV_TEST_BASH to the intended executable")


@pytest.mark.parametrize("job", ["build", "gate"])
@pytest.mark.parametrize("release", ["false", "true"])
@pytest.mark.parametrize("runner_exit", [0, 23])
def test_workflow_runner_arguments_and_exit_status(tmp_path, job, release, runner_exit):
    workflow = yaml.load((ROOT / ".github/workflows/python-checks.yml").read_text(),
                         Loader=yaml.BaseLoader)
    steps = [step for step in workflow["jobs"][job]["steps"]
             if "scripts/ci.py " + job in step.get("run", "")]
    assert len(steps) == 1
    work = tmp_path / "workflow with spaces"
    work.mkdir()
    # Record the argument vector without building packages or fabricating CI evidence.
    stub = """python() {
  printf '%s\\0' "$@" > arguments.bin
  printf '%s\\n' 'runner stdout'
  printf '%s\\n' 'runner stderr' >&2
  return "$RUNNER_EXIT"
}
"""
    script = work / "step.sh"
    script.write_text(stub + steps[0]["run"], encoding="utf-8", newline="\n")
    result = subprocess.run([bash_executable(), "--noprofile", "--norc", "-e", "-o", "pipefail", "step.sh"],
                            cwd=work, env={**os.environ, "TIER": "full",
                                           "CONFIGURATION": "configuration with spaces",
                                           "REQUIRE_RELEASE": release, "RUNNER_EXIT": str(runner_exit)},
                            capture_output=True, text=True)
    assert result.returncode == runner_exit, result.stdout + result.stderr
    expected = ["-B", "scripts/ci.py", job, "--tier", "full"]
    if job == "build":
        expected += ["--configuration", "configuration with spaces", "--work", "build/ci",
                     "--output", "build/record.json"]
        log = (work / "build/ci.log").read_text()
        assert "runner stdout\n" in log and "runner stderr\n" in log
    else:
        expected += ["--evidence", "build/evidence", "--output", "build/quality.json"]
    if release == "true":
        expected.append("--require-release")
    assert (work / "arguments.bin").read_bytes().split(b"\0") == [
        *[argument.encode() for argument in expected], b""]
