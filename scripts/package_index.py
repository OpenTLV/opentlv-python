# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Read the public JSON and Integrity APIs of TestPyPI and PyPI; uploads use Trusted Publishing only."""

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from package_contract import DISTRIBUTION

INDEXES = {"testpypi": "https://test.pypi.org", "pypi": "https://pypi.org"}
UPLOAD_URLS = {"testpypi": "https://test.pypi.org/legacy/", "pypi": "https://upload.pypi.org/legacy/"}
FILE_HOSTS = {"testpypi": "test-files.pythonhosted.org", "pypi": "files.pythonhosted.org"}


def fetch(url, accept="application/json"):
    """Return the parsed response, or None when the index has no such resource."""
    try:
        with urlopen(Request(url, headers={"Accept": accept}), timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def index_release(index, version):
    return fetch(f"{INDEXES[index]}/pypi/{DISTRIBUTION}/{version}/json")


def index_files(index, version):
    """Return the files the index already holds for this version, by SHA-256."""
    release = index_release(index, version)
    return {} if release is None else {item["filename"]: item["digests"]["sha256"] for item in release["urls"]}


def provenance(index, version, filename):
    """Return one file's PEP 740 provenance, or None while the index has none."""
    return fetch(f"{INDEXES[index]}/integrity/{DISTRIBUTION}/{version}/{filename}/provenance",
                 "application/vnd.pypi.integrity.v1+json")


def download(url, path):
    with urlopen(url, timeout=60) as response:
        path.write_bytes(response.read())
