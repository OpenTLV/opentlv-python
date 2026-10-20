# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import re

import opentlv


def test_version_matches_semver_shape():
    assert re.match(r"^\d+\.\d+\.\d+", opentlv.__version__)
