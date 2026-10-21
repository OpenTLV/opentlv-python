# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import pytest
import _opentlv
from opentlv import Format, Reader, Writer, InvalidLengthError, TruncatedError


def test_preset_tracks_native_build_option():
    assert hasattr(Format, "LLDP") == bool(_opentlv.HAS_LLDP)


@pytest.mark.skipif(not _opentlv.HAS_LLDP, reason="LLDP disabled")
@pytest.mark.parametrize("length", [0, 255, 256, 511])
def test_lldp_preset_roundtrip(length):
    writer = Writer(format=Format.LLDP)
    writer.write(b"\x7f", b"\xaa" * length)
    wire = writer.bytes()
    assert wire[:2] == bytes([254 | (length >> 8), length & 255])
    (element,) = list(Reader(wire, format=Format.LLDP))
    assert bytes(element.tag) == b"\x7f"
    assert bytes(element.value) == b"\xaa" * length


@pytest.mark.skipif(not _opentlv.HAS_LLDP, reason="LLDP disabled")
def test_lldp_preset_rejects_truncation_and_large_values():
    with pytest.raises(TruncatedError):
        list(Reader(b"\x03\x00", format=Format.LLDP))
    with pytest.raises(InvalidLengthError):
        Writer(format=Format.LLDP).write(b"\x01", bytes(512))
