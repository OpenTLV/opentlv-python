# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Small dependency-verification helpers, using only the Python standard library."""

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(*args, cwd=ROOT, capture=False):
    command = list(map(str, args))
    print("+ " + " ".join(command), flush=True)
    result = subprocess.run(command, cwd=cwd, check=True, text=True, encoding="utf-8",
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def api(path):
    return json.loads(run("gh", "api", path, capture=True))
