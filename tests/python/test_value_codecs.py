# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import pytest

from opentlv import OpenTLVError


@pytest.mark.parametrize("codec,value,wire", [
    ("UINT8", 255, "ff"), ("UINT16_BE", 0x0102, "0102"), ("UINT16_LE", 0x0102, "0201"),
    ("UINT32_BE", 0x01020304, "01020304"), ("UINT32_LE", 0x01020304, "04030201"),
    ("INT64_MINIMAL_BE", 0, "00"), ("INT64_MINIMAL_BE", -129, "ff7f"),
    ("INT64_MINIMAL_BE", 2**63 - 1, "7fffffffffffffff"), ("BYTES", b"", ""),
    ("BYTES", b"\x00\xff", "00ff")])
def test_static_value_codecs_use_c(codec, value, wire):
    from opentlv import ValueCodec
    codec = ValueCodec[codec]
    expected = bytes.fromhex(wire)
    assert codec.encode(value) == expected
    assert codec.decode(expected) == value
    assert codec.encoded_size(value) == len(expected)
    output = bytearray(b"!" * (len(expected) + 1))
    assert codec.encode_into(value, output) == len(expected)
    assert output == expected + b"!"
    if expected:
        short = bytearray(b"!" * (len(expected) - 1))
        with pytest.raises(OpenTLVError):
            codec.encode_into(value, short)
        assert short == b"!" * len(short)


def test_static_value_codecs_reject_lengths_and_representations():
    from opentlv import InvalidValueError, ValueCodec
    with pytest.raises(InvalidValueError) as failure:
        ValueCodec.UINT16_BE.decode(b"\x01")
    assert failure.value.codec_detail["reason_name"] == "length"
    assert failure.value.codec_detail["operation_name"] == "decode"
    with pytest.raises(InvalidValueError) as failure:
        ValueCodec.INT64_MINIMAL_BE.decode(b"\x00\x01")
    assert failure.value.codec_detail["reason_name"] == "canonical"
    with pytest.raises(OverflowError):
        ValueCodec.UINT8.encode(256)
    with pytest.raises(OverflowError):
        ValueCodec.UINT32_LE.encode(-1)
    with pytest.raises(OverflowError):
        ValueCodec.INT64_MINIMAL_BE.encode(2**63)
    with pytest.raises(TypeError):
        ValueCodec.BYTES.encode("text")
    output = bytearray(b"abcd")
    with pytest.raises(ValueError, match="overlap"):
        ValueCodec.BYTES.encode_into(memoryview(output)[:2], output)


def test_ipv4_codecs_return_addresses_and_copy_list_entries():
    from ipaddress import IPv4Address
    from opentlv import InvalidValueError, ValueCodec
    assert ValueCodec.IPV4.decode(bytes.fromhex("c0000201")) == IPv4Address("192.0.2.1")
    assert ValueCodec.IPV4.encode("192.0.2.1") == bytes.fromhex("c0000201")
    assert ValueCodec.IPV4.encode(IPv4Address("10.0.0.1")) == bytes.fromhex("0a000001")
    wire = bytes.fromhex("c0000201c0000201c6336401")
    addresses = ValueCodec.IPV4_LIST.decode(bytearray(wire))
    assert addresses == (IPv4Address("192.0.2.1"),) * 2 + (IPv4Address("198.51.100.1"),)
    assert ValueCodec.IPV4_LIST.encode(addresses) == wire
    assert ValueCodec.IPV4_LIST.encoded_size(["192.0.2.1"]) == 4
    assert ValueCodec.IPV4_LIST.decode(b"") == ()
    assert ValueCodec.IPV4_LIST.encode([]) == b""
    with pytest.raises(InvalidValueError):
        ValueCodec.IPV4.decode(b"\x01\x02\x03")
    with pytest.raises(InvalidValueError):
        ValueCodec.IPV4_LIST.decode(b"\x01\x02\x03\x04\x05")


def test_text_codec_validates_alphabet_width_and_padding():
    from opentlv import InvalidArgError, InvalidValueError, TextAlphabet, TextCodec
    assert TextCodec().decode(b"Hello, world") == "Hello, world"
    assert TextCodec().encode("") == b""
    padded = TextCodec(width=6, zero_padding=True)
    assert padded.encode("abc") == b"abc\x00\x00\x00"
    assert padded.decode(b"abc\x00\x00\x00") == "abc"
    assert padded.encoded_size("a") == 6
    assert TextCodec(width=3).decode(b"abc") == "abc"
    with pytest.raises(InvalidValueError):
        TextCodec(width=3).encode("ab")
    alnum = TextCodec(TextAlphabet.ASCII_ALNUM)
    assert alnum.encode("A1b2") == b"A1b2"
    with pytest.raises(InvalidValueError) as failure:
        alnum.decode(b"A b")
    assert failure.value.codec_detail["reason_name"] == "text"
    with pytest.raises(InvalidValueError):
        TextCodec().encode("café")
    with pytest.raises(InvalidValueError):
        padded.decode(b"a\x00c\x00\x00\x00")
    with pytest.raises(InvalidArgError):
        TextCodec(alphabet=7).encode("a")
    with pytest.raises(TypeError):
        TextCodec().encode(b"bytes")


def test_digits_codec_keeps_leading_zeros_and_f_padding():
    from opentlv import DigitsCodec, InvalidValueError
    assert DigitsCodec().encode("0123") == bytes.fromhex("0123")
    assert DigitsCodec().encode("012") == bytes.fromhex("012f")
    assert DigitsCodec().decode(bytes.fromhex("012f")) == "012"
    assert DigitsCodec().encode("") == b""
    assert DigitsCodec().decode(b"") == ""
    fixed = DigitsCodec(width=4)
    assert fixed.encode("12") == bytes.fromhex("12ffffff")
    assert fixed.decode(bytes.fromhex("12ffffff")) == "12"
    assert fixed.encoded_size("1") == 4
    output = bytearray(3)
    with pytest.raises(OpenTLVError):
        fixed.encode_into("1", output)
    assert output == bytearray(3)
    with pytest.raises(InvalidValueError) as failure:
        DigitsCodec().decode(bytes.fromhex("1a"))
    assert failure.value.codec_detail["reason_name"] == "digit"
    with pytest.raises(InvalidValueError):
        DigitsCodec().encode("12a")
    with pytest.raises(InvalidValueError):
        DigitsCodec(width=1).encode("123")


def _amount_codec(**options):
    from opentlv import (Reader, StructureCodec, StructureRule, StructureSchema, Tag,
                         ValueCodec)
    schema = StructureSchema([StructureRule(Tag(b"\x5a"), min_occurs=1, max_occurs=1,
                                            min_length=2, max_length=2)])

    def decode(data):
        (element,) = Reader(data)
        return ValueCodec.UINT16_BE.decode(bytes(element.value))

    def encode(value):
        return b"\x5a\x02" + ValueCodec.UINT16_BE.encode(value)
    return StructureCodec(**{"schema": schema, "decode": decode, "encode": encode, **options})


def test_structure_codec_validates_before_and_after_python_callbacks():
    from opentlv import SchemaError, TruncatedError
    codec = _amount_codec()
    assert codec.decode(bytes.fromhex("5a020102")) == 0x0102
    assert codec.encode(0x0102) == bytes.fromhex("5a020102")
    assert codec.encoded_size(1) == 4
    output = bytearray(b"!" * 5)
    assert codec.encode_into(1, output) == 4
    assert output == bytes.fromhex("5a020001") + b"!"
    with pytest.raises(SchemaError) as failure:
        codec.decode(bytes.fromhex("5a0101"))
    detail = failure.value.codec_detail
    assert detail["operation_name"] == "decode" and detail["cause_name"] == "schema"
    assert detail["schema"].length.actual == 1
    with pytest.raises(TruncatedError) as failure:
        codec.decode(bytes.fromhex("5a0201"))
    assert failure.value.codec_detail["cause_name"] == "reader"
    checked = _amount_codec(schema=codec.schema.check())
    assert checked.decode(bytes.fromhex("5a020102")) == 0x0102


def test_structure_codec_validates_encoded_output_and_reports_output_locations():
    from opentlv import BufferTooShortError, SchemaError
    calls = []
    codec = _amount_codec(encode=lambda value: calls.append(value) or b"\x5a\x01\x00")
    with pytest.raises(SchemaError) as failure:
        codec.encode(1)
    assert failure.value.codec_detail["operation_name"] == "encode"
    assert failure.value.location.domain == "output"
    assert calls == [1]
    output = bytearray(b"!" * 8)
    with pytest.raises(SchemaError):
        codec.encode_into(1, output)
    assert output == b"!" * 8
    short = bytearray(b"!" * 3)
    with pytest.raises(BufferTooShortError):
        _amount_codec().encode_into(1, short)
    assert short == b"!" * 3


def test_structure_codec_propagates_callbacks_and_reports_unsupported_directions():
    from opentlv import StructureCodec, UnsupportedError
    sentinel = LookupError("decode failed")

    def fail(data):
        raise sentinel
    with pytest.raises(LookupError) as caught:
        StructureCodec(decode=fail).decode(b"\x5a\x00")
    assert caught.value is sentinel
    with pytest.raises(TypeError):
        StructureCodec(encode=lambda value: 5).encode(1)
    assert StructureCodec(decode=lambda data: data).decode(b"") == b""
    with pytest.raises(UnsupportedError):
        StructureCodec(encode=bytes).decode(b"\x5a\x00")
    with pytest.raises(UnsupportedError):
        StructureCodec(decode=bytes).encode(b"\x5a\x00")
    with pytest.raises(TypeError):
        StructureCodec(schema=object())
    with pytest.raises(TypeError):
        StructureCodec(decode=1)
    with pytest.raises(ValueError):
        StructureCodec(decode=bytes, max_depth=-1).decode(b"")


def test_structure_codec_applies_its_format_and_limits():
    from opentlv import FixedFormat, LimitError, StructureCodec
    fixed = StructureCodec(FixedFormat(1, 1), decode=len,
                           encode=lambda value: bytes([1, len(value)]) + value)
    assert fixed.decode(b"\x01\x02ab\x02\x00") == 6
    assert fixed.encode(b"ab") == b"\x01\x02ab"
    with pytest.raises(LimitError):
        StructureCodec(decode=len, max_elements=1).decode(b"\x5a\x00\x5a\x00")
