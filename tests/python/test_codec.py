# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import _opentlv as _native
import pytest

from opentlv import codec, OpenTLVError


def test_decode_amount_matches_the_emv_format_n12_example():
    assert codec.decode_amount(bytes.fromhex("000000012345")) == 12345


def test_encode_amount_matches_the_emv_format_n12_example():
    assert codec.encode_amount(12345) == bytes.fromhex("000000012345")


def test_amounts_round_trip():
    for value in (0, 1, 999999999999):
        assert codec.decode_amount(codec.encode_amount(value)) == value


def test_decode_amount_rejects_the_wrong_length():
    with pytest.raises(OpenTLVError) as excinfo:
        codec.decode_amount(b"\x00\x00\x01")
    assert isinstance(excinfo.value.code, int)
    assert str(excinfo.value)


def test_encode_amount_rejects_a_value_that_does_not_fit():
    with pytest.raises(OpenTLVError):
        codec.encode_amount(10**13)


@pytest.mark.parametrize("encoding,width,digits,value,wire", [
    (0, 2, 0, 258, "0102"), (1, 2, 0, 258, "0201"),
    (2, 3, 6, 12345, "012345"), (0, 0, 0, 0, "00"),
    (0, 8, 0, 2**64 - 1, "FFFFFFFFFFFFFFFF")])
def test_configured_number_codec_uses_c(encoding, width, digits, value, wire):
    from opentlv import NumberCodec, NumberEncoding, OpenTLVError
    codec = NumberCodec(NumberEncoding(encoding), width, digits)
    expected = bytes.fromhex(wire)
    assert codec.encode(value) == expected
    assert codec.decode(expected) == value
    assert codec.encoded_size(value) == len(expected)
    output = bytearray(b"!" * (len(expected) + 1))
    assert codec.encode_into(value, output) == len(expected)
    assert output == expected + b"!"
    short = bytearray(b"!" * (len(expected) - 1))
    with pytest.raises(OpenTLVError):
        codec.encode_into(value, short)
    assert short == b"!" * len(short)


def test_number_codec_rejects_overflow_invalid_digits_and_bcd():
    from opentlv import NumberCodec, NumberEncoding, OpenTLVError
    with pytest.raises(OpenTLVError):
        NumberCodec(width=1).encode(256)
    with pytest.raises(OverflowError):
        NumberCodec().encode(-1)
    with pytest.raises(OverflowError):
        NumberCodec(digits=-1).encode(0)
    with pytest.raises(OpenTLVError):
        NumberCodec(NumberEncoding.BCD, 1, 2).decode(b"\xFA")


def test_codec_diagnostic_uses_shared_status_and_operation():
    from opentlv import NumberCodec, InvalidArgError, SchemaError, BufferTooShortError
    with pytest.raises(SchemaError) as failure:
        codec.decode_amount(b"bad")
    assert failure.value.code == _native.RESULT_SCHEMA
    assert failure.value.codec_detail["operation"] == 0
    assert failure.value.codec_detail["reported"] == _native.RESULT_SCHEMA
    assert failure.value.codec_detail["cause"] == 2
    assert failure.value.codec_detail["schema"].length.actual == 3
    with pytest.raises(InvalidArgError) as failure:
        NumberCodec(width=9).encode(1)
    assert failure.value.codec_detail["operation"] == 2
    with pytest.raises(BufferTooShortError) as failure:
        NumberCodec(width=2).encode_into(1, bytearray(1))
    assert failure.value.codec_detail["operation"] == 1
