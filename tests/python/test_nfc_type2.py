# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import pytest
import _opentlv
from opentlv import Format, Reader, Writer, InvalidLengthError


def test_nfc_availability():
    assert hasattr(Format, "NFC_TYPE2") == bool(_opentlv.HAS_NFC)


@pytest.mark.skipif(not _opentlv.HAS_NFC, reason="NFC disabled")
def test_nfc_stream_roundtrip_and_extended_length():
    wire = bytes.fromhex("00 03 03 D1 01 00 FE 00")
    elements = list(Reader(wire, format=Format.NFC_TYPE2))
    assert [bytes(e.tag) for e in elements] == [b"\x00", b"\x03", b"\xfe", b"\x00"]
    assert bytes(elements[1].value) == bytes.fromhex("D1 01 00")
    writer = Writer(format=Format.NFC_TYPE2)
    for element in elements:
        writer.write(bytes(element.tag), bytes(element.value))
    assert writer.bytes() == wire
    writer = Writer(format=Format.NFC_TYPE2)
    writer.write(b"\x03", b"x" * 255)
    assert writer.bytes() == bytes.fromhex("03 FF 00 FF") + b"x" * 255
    assert len(list(Reader(writer.bytes(), format=Format.NFC_TYPE2))[0].value) == 255
    for invalid in ("03 FF 00 FE", "03 FF FF FF"):
        with pytest.raises(InvalidLengthError):
            list(Reader(bytes.fromhex(invalid), format=Format.NFC_TYPE2))
