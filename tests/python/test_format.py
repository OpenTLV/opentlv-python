# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

from opentlv import Format


def test_values_match_what_the_native_module_expects():
    # _opentlv's format IDs are fixed; see format.c's lookup.
    assert not hasattr(Format, "COMPACT")
    assert Format.BER == 1
    assert Format.CER == 2
    assert Format.DER == 3
