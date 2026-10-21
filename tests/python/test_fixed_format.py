# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import pytest

from opentlv import Element, FixedFormat, InvalidLengthError, Reader, Tag, Writer, encoded_size


def test_rejects_invalid_configurations():
    with pytest.raises(ValueError):
        FixedFormat(0, 1)
    with pytest.raises(ValueError):
        FixedFormat(1, 0)
    with pytest.raises(ValueError):
        FixedFormat(1, 9)
    with pytest.raises(ValueError):
        FixedFormat(1, 1, "middle")


def test_defaults_to_one_byte_tag_and_length_big_endian():
    format = FixedFormat(1, 1)
    assert format.tag_size == 1
    assert format.length_size == 1
    assert format.big_endian is True


def test_two_byte_tag_one_byte_length_round_trips():
    format = FixedFormat(2, 1)
    writer = Writer(format)
    writer.write(Tag(b"\x01\x02"), b"\xaa\xbb\xcc")
    encoded = writer.bytes()
    assert encoded == b"\x01\x02\x03\xaa\xbb\xcc"

    (element,) = list(Reader(encoded, format))
    assert element == Element(Tag(b"\x01\x02"), memoryview(b"\xaa\xbb\xcc"))


def test_little_endian_length_field():
    format = FixedFormat(1, 2, "little")
    writer = Writer(format)
    writer.write(Tag(b"\x01"), b"\xaa\xbb\xcc")
    assert writer.bytes() == b"\x01\x03\x00\xaa\xbb\xcc"


def test_value_too_long_for_the_length_width_is_rejected():
    format = FixedFormat(1, 1)
    writer = Writer(format)
    with pytest.raises(InvalidLengthError):
        writer.write(Tag(b"\x01"), bytes(256))


def test_encoded_size_matches_written_size():
    format = FixedFormat(2, 1)
    assert encoded_size(Tag(b"\x01\x02"), 3, format) == 6


def test_equality_and_repr():
    assert FixedFormat(1, 1) == FixedFormat(1, 1, "big")
    assert FixedFormat(1, 1) != FixedFormat(2, 1)
    assert "FixedFormat" in repr(FixedFormat(1, 1))
