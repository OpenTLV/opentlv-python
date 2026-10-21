# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Run this module alone for builds with optional formats disabled."""
import pytest
import _opentlv as native
from opentlv import Document, FixedFormat, Format, Reader, Writer, codec, encoded_size


@pytest.mark.parametrize("name, identifier", [("BER", 1), ("CER", 2), ("DER", 3), ("LLDP", 4), ("EMV", 5), ("NFC_TYPE2", 6)])
def test_format_availability(name, identifier):
    available = bool(getattr(native, "HAS_" + ("NFC" if name == "NFC_TYPE2" else name)))
    assert hasattr(Format, name) == available
    if not available:
        with pytest.raises(ValueError, match="unknown format"):
            native.encoded_size(b"\x04", 1, identifier)
        return
    format = getattr(Format, name)
    assert int(format) == identifier
    writer = Writer(format)
    writer.write(b"\x04", b"*")
    (element,) = Reader(writer.bytes(), format)
    assert bytes(element.tag) == b"\x04"
    assert bytes(element.value) == b"*"
    with Document(writer.bytes(), format) as document:
        assert document.encode() == writer.bytes()


def test_fixed_remains_available():
    format = FixedFormat(1, 1)
    writer = Writer(format)
    writer.write(b"\x04", b"*")
    (element,) = Reader(writer.bytes(), format)
    assert bytes(element.value) == b"*"
    assert encoded_size(b"\x04", 1, format) == 3


def test_default_requires_ber():
    if native.HAS_BER:
        assert Writer().format == Format.BER
        assert Reader(b"").format == Format.BER
    else:
        for call in (lambda: Reader(b""), Writer, Document,
                     lambda: encoded_size(b"\x04", 1)):
            with pytest.raises(ValueError, match="format is required when BER is disabled"):
                call()


def test_disabled_emv_reports_unavailability():
    if not native.HAS_EMV:
        for call in (lambda: codec.decode_amount(bytes(6)), lambda: codec.encode_amount(0)):
            with pytest.raises(NotImplementedError, match="EMV is disabled"):
                call()
