# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import pytest

from opentlv import (BufferTooShortError, Element, FixedFormat, Format,
                     InvalidTagSizeError, Location, Reader, Tag, Writer,
                     element_encoded_size, encoded_size)


@pytest.mark.parametrize("format", [Format.BER, FixedFormat(1, 1, "big")])
def test_measure_allocate_write_into_exact_caller_storage(format):
    element = Element(Tag(b"\x04"), memoryview(b"abc"))
    required = element_encoded_size(element, format)
    storage = bytearray(required)
    writer = Writer(format, buffer=storage)
    writer.write_element(element)
    assert writer.position == required
    assert writer.remaining == 0
    assert writer.capacity == required
    assert writer.view() == storage == b"\x04\x03abc"
    with pytest.raises(BufferTooShortError) as exc:
        writer.write_element(element)
    assert exc.value.offset == required
    assert exc.value.location == Location("output", "point", required, required)
    assert exc.value.required == required
    assert writer.position == required
    assert storage == b"\x04\x03abc"


def test_borrowed_empty_buffer_never_becomes_a_sizing_query():
    storage = bytearray()
    writer = Writer(buffer=storage)
    with pytest.raises(BufferTooShortError):
        writer.write(b"\x04", b"")
    assert writer.position == len(storage) == 0
    writer.copy_encoded(b"")
    assert writer.position == 0


def test_borrowed_memoryview_capacity_failure_and_retry():
    storage = bytearray(b"\xee" * 6)
    writer = Writer(buffer=memoryview(storage)[1:5])
    with pytest.raises(BufferTooShortError):
        writer.write(b"\x04", b"abc")
    assert storage == b"\xee" * 6
    writer.write(b"\x04", b"ab")
    assert storage == b"\xee\x04\x02ab\xee"


def test_raw_copy_supports_overlap_and_does_not_validate_framing():
    storage = bytearray(b"abcd--")
    writer = Writer(buffer=storage)
    writer.copy_encoded(b"!")
    writer.copy_encoded(memoryview(storage)[:4])
    assert storage == b"!!bcd-"
    with pytest.raises(BufferTooShortError) as exc:
        writer.copy_encoded(b"too long")
    assert exc.value.operation == "copy"
    assert exc.value.offset == 5
    assert writer.position == 5


def test_borrowed_buffer_must_be_writable_and_contiguous():
    with pytest.raises(ValueError):
        Writer(buffer=memoryview(b"immutable"))
    with pytest.raises(ValueError):
        Writer(buffer=memoryview(bytearray(8))[::2])


def test_element_measurement_failure_has_no_destination_capacity():
    element = Element(Tag(b"\x9f\x02"), memoryview(b"abc"))
    with pytest.raises(InvalidTagSizeError) as exc:
        element_encoded_size(element, FixedFormat(1, 1, "big"))
    assert exc.value.available is None
    assert exc.value.tag == b"\x9f\x02"
    assert exc.value.operation == "tag"


def test_write_produces_the_same_bytes_as_the_default_format_example():
    writer = Writer()
    writer.write(Tag(b"\x01"), b"\xaa\xbb")
    writer.write(Tag(b"\x02"), b"")
    assert writer.bytes() == bytes([0x01, 0x02, 0xAA, 0xBB, 0x02, 0x00])


def test_write_accepts_raw_bytes_as_a_tag():
    writer = Writer()
    writer.write(b"\x01", b"\xaa")
    assert writer.bytes() == bytes([0x01, 0x01, 0xAA])


def test_position_and_len_track_bytes_written():
    writer = Writer()
    assert writer.position == 0
    assert len(writer) == 0
    writer.write(Tag(b"\x01"), b"\xaa\xbb")
    assert writer.position == 4
    assert len(writer) == 4


def test_grows_past_the_initial_capacity_without_error():
    writer = Writer()
    value = bytes(500)
    writer.write(Tag(b"\x01"), value)
    # 500 needs BER's 2-byte long-form length (0x82 0x01 0xF4).
    assert writer.bytes() == bytes([0x01, 0x82, 0x01, 0xF4]) + value


def test_write_element_round_trips_a_reader_entry():
    (element,) = list(Reader(bytes([0x01, 0x02, 0xAA, 0xBB])))
    writer = Writer()
    writer.write_element(element)
    assert writer.bytes() == bytes([0x01, 0x02, 0xAA, 0xBB])


def test_fixed_one_byte_tag_rejects_a_multi_byte_tag():
    writer = Writer(FixedFormat(1, 1, "big"))
    with pytest.raises(InvalidTagSizeError):
        writer.write(Tag(b"\x9f\x02"), b"")


def test_writes_other_formats():
    writer = Writer(Format.BER)
    writer.write(Tag(b"\x9f\x02"), b"\xaa")
    reader = Reader(writer.bytes(), Format.BER)
    (element,) = list(reader)
    assert element == Element(Tag(b"\x9f\x02"), memoryview(b"\xaa"))


def test_repr_shows_format_and_position():
    writer = Writer()
    writer.write(Tag(b"\x01"), b"\xaa")
    assert repr(writer) == "Writer(format=<Format.BER: 1>, position=3)"


def test_encoded_size_matches_what_write_produces():
    tag = Tag(b"\x01")
    size = encoded_size(tag, 3)
    writer = Writer()
    writer.write(tag, b"\xaa\xbb\xcc")
    assert size == len(writer)


def test_encoded_size_accepts_raw_bytes_as_a_tag():
    assert encoded_size(b"\x01", 3) == 5
