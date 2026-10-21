# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import pytest
import _opentlv
from opentlv import Format, Reader, Writer, InvalidLengthError


@pytest.mark.skipif(not _opentlv.HAS_EMV, reason="EMV disabled")
def test_definite_emv_framing():
    writer = Writer(format=Format.EMV)
    writer.write(b"\x9f\x02", b"\x00" * 6)
    assert writer.bytes() == b"\x9f\x02\x06" + b"\x00" * 6
    (element,) = Reader(writer.bytes(), format=Format.EMV)
    assert bytes(element.tag) == b"\x9f\x02"
    assert bytes(element.value) == b"\x00" * 6
    with pytest.raises(InvalidLengthError):
        list(Reader(b"\x70\x80\x00\x00", format=Format.EMV))
    assert len(list(Reader(b"\x70\x80\x00\x00", format=Format.BER))) == 1
