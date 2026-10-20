# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import _opentlv as _native
import pytest

from opentlv import Format, TruncatedError, Element, InvalidLengthError, OpenTLVError, Reader, Tag


def test_iterates_entries_with_the_default_format():
    data = bytes([0x01, 0x02, 0xAA, 0xBB, 0x02, 0x00])
    elements = list(Reader(data))
    assert elements == [
        Element(Tag(b"\x01"), memoryview(b"\xaa\xbb")),
        Element(Tag(b"\x02"), memoryview(b"")),
    ]


def test_value_is_a_zero_copy_view_onto_the_input():
    data = bytearray([0x01, 0x02, 0xAA, 0xBB])
    (element,) = list(Reader(data))
    assert element.value.obj is data or bytes(element.value.obj) == bytes(data)
    assert bytes(element.value) == b"\xaa\xbb"


def test_accepts_any_buffer_protocol_object():
    payload = bytes([0x01, 0x01, 0x42])
    for data in (payload, bytearray(payload), memoryview(payload)):
        (element,) = list(Reader(data))
        assert bytes(element.value) == b"\x42"


def test_rejects_non_buffer_input():
    with pytest.raises(TypeError):
        list(Reader("not bytes"))


def test_empty_input_yields_no_entries():
    reader = Reader(b"")
    assert reader.at_end is True
    assert list(reader) == []


def test_position_and_at_end_track_progress():
    reader = Reader(bytes([0x01, 0x01, 0x42, 0x02, 0x00]))
    assert reader.position == 0
    assert reader.at_end is False
    next(reader)
    assert reader.position == 3
    assert reader.at_end is False
    next(reader)
    assert reader.position == 5
    assert reader.at_end is True
    with pytest.raises(StopIteration):
        next(reader)


def test_truncated_value_raises_truncated_error_with_diagnostics():
    reader = Reader(bytes([0x01, 0x05, 0xAA]))
    with pytest.raises(TruncatedError) as excinfo:
        next(reader)
    error = excinfo.value
    assert error.code == _native.RESULT_TRUNCATED
    assert error.operation == "value"
    assert error.offset == 2
    assert isinstance(error, OpenTLVError)


def test_invalid_length_form_raises_invalid_length_error():
    reader = Reader(bytes([0x01, 0xFF]))
    with pytest.raises(InvalidLengthError):
        next(reader)


def test_stops_after_the_first_error_instead_of_retrying():
    reader = Reader(bytes([0x01, 0x05, 0xAA]))
    with pytest.raises(TruncatedError):
        next(reader)
    with pytest.raises(StopIteration):
        next(reader)
    assert reader.at_end is False


def test_is_reusable_as_a_plain_iterator():
    reader = Reader(bytes([0x01, 0x00]))
    assert iter(reader) is reader


def test_element_borrows_raw_length_from_immutable_snapshot():
    data = bytearray([1, 0x81, 1, 0xAA])
    element = next(Reader(data))
    assert bytes(element.length) == b"\x81\x01"
    assert element.length.obj == bytes(data)
    data[:] = b"\x00" * len(data)
    assert bytes(element.length) == b"\x81\x01"
    assert bytes(element.value) == b"\xaa"


def test_large_declared_size_and_raw_length_survive_reader_error():
    data = bytes([4, 0x85, 1, 0, 0, 0, 0]) + bytes(127)
    with pytest.raises(TruncatedError) as error:
        next(Reader(data, Format.BER))
    assert error.value.declared_length == 4294967296
    assert error.value.available == 127
    assert error.value.raw_length == bytes([0x85, 1, 0, 0, 0, 0])
def test_single_read_returns_source_without_consuming_trailing_input():
    from opentlv import read, EndError
    decoded = read(b"\x01\x00\xff")
    assert bytes(decoded.encoded) == b"\x01\x00"
    with pytest.raises(EndError):
        read(b"")
