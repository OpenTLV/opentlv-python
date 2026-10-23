# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

from dataclasses import replace

import _opentlv as _native
import pytest

from opentlv import (BufferTooShortError, Element, EndError, FixedFormat, InvalidArgError,
                     NeedMoreDataError, Reader, Tag, TreeReader, TruncatedError, Writer,
                     element_encoded_size, read_element, write_element)


def test_session_streams_into_fixed_storage_and_preserves_selected_elements():
    # The second element uses a non-minimal BER length; preservation keeps it.
    data = bytes([0x01, 0x01, 0xAA, 0x02, 0x81, 0x02, 0xBB, 0xCC, 0x03, 0x00])
    storage = bytearray(16)
    writer = Writer(buffer=storage)
    reader = Reader(data)
    remaining = []
    while not reader.at_end:
        decoded = reader.read_source()
        if decoded.element.tag == Tag(b"\x02"):
            writer.preserve(decoded)
        else:
            writer.write_element(decoded.element)
        remaining.append(writer.remaining)
    assert remaining == [13, 8, 6]
    assert writer.view() == data
    assert storage[len(data):] == bytes(6)


def test_session_preservation_failures_keep_position_and_output():
    decoded = Reader(bytes([0x04, 0x81, 0x01, 0x2A])).read_source()
    storage = bytearray(b"!!!!")
    writer = Writer(buffer=storage)
    writer.copy_encoded(b"?")
    with pytest.raises(BufferTooShortError) as exc:
        writer.preserve(decoded)
    assert exc.value.operation == "preserve"
    assert (exc.value.required, exc.value.available, exc.value.offset) == (4, 3, 1)
    changed = replace(decoded, element=Element(Tag(b"\x04"), memoryview(b"\x2b")))
    with pytest.raises(InvalidArgError):
        writer.preserve(changed)
    assert writer.position == 1
    assert storage == b"?!!!"
    with pytest.raises(ValueError, match="Reader-produced source"):
        writer.preserve(replace(decoded, _source=None))


def test_owned_growth_moves_output_and_keeps_earlier_views():
    writer = Writer()
    writer.write(b"\x01", b"\xaa")
    before = writer.view()
    writer.copy_encoded(bytes(100))
    writer.preserve(Reader(bytes([0x04, 0x81, 0x01, 0x2A])).read_source())
    assert writer.capacity == 128
    assert before == b"\x01\x01\xaa"
    assert writer.bytes() == b"\x01\x01\xaa" + bytes(100) + b"\x04\x81\x01\x2a"
    assert writer.remaining == writer.capacity - writer.position


def test_borrowed_storage_is_pinned_while_the_session_exists():
    storage = bytearray(4)
    writer = Writer(buffer=storage)
    with pytest.raises(BufferError):
        storage.extend(b"x")
    del writer
    storage.extend(b"x")
    assert len(storage) == 5


def test_write_element_encodes_one_element_at_an_offset_in_caller_storage():
    element = Element(Tag(b"\x04"), memoryview(b"abc"))
    storage = bytearray(b"\xee" * 7)
    assert write_element(storage, element, offset=2) == 5
    assert storage == b"\xee\xee\x04\x03abc"
    with pytest.raises(BufferTooShortError) as exc:
        write_element(storage, element, offset=3)
    assert exc.value.required == element_encoded_size(element) == 5
    assert (exc.value.available, exc.value.offset) == (4, 3)
    assert storage == b"\xee\xee\x04\x03abc"
    assert write_element(bytearray(4), Element(Tag(b"\x04"), memoryview(b"ab")),
                         FixedFormat(1, 1, "big")) == 4
    with pytest.raises(ValueError, match="offset"):
        write_element(storage, element, offset=8)
    with pytest.raises(TypeError):
        write_element(b"immutable", element)


def test_read_element_pulls_without_source_metadata():
    data = bytes([0x01, 0x81, 0x01, 0xAA, 0x02, 0x00, 0x03, 0x01, 0xCC])
    reader = Reader(data)
    first = reader.read_element()
    assert first == Element(Tag(b"\x01"), memoryview(b"\xaa"))
    assert first.value.obj is data
    assert bytes(first.length) == b""
    assert bytes(reader.read_source().element.length) == b"\x00"
    assert reader.read_element() == Element(Tag(b"\x03"), memoryview(b"\xcc"))
    assert reader.at_end
    with pytest.raises(StopIteration):
        reader.read_element()


def test_read_element_reports_the_same_diagnostics_and_resumes_incremental_input():
    reader = Reader(bytes([0x01, 0x05, 0xAA]))
    with pytest.raises(TruncatedError) as excinfo:
        reader.read_element()
    assert (excinfo.value.operation, excinfo.value.offset) == ("value", 2)
    assert reader.position == 0
    data = b"\x04\x01\x2a\x04\x01\x2b"
    reader = Reader(data[:2], final_input=False)
    with pytest.raises(NeedMoreDataError):
        reader.read_element()
    reader.set_input(data[:4])
    assert bytes(reader.read_element().value) == b"\x2a"
    reader.set_input(data[3:], discard=3, final_input=True)
    second = reader.read_element()
    assert bytes(second.value) == b"\x2b"
    assert second.value.obj == data[3:]
    assert reader.at_end


def test_tree_reader_has_no_source_free_pull():
    with pytest.raises(ValueError, match="sequential Reader"):
        _native.cursor_read(TreeReader(b"\x04\x00")._capsule)


def test_single_read_element_returns_consumed_size_and_snapshots_mutable_input():
    data = bytearray([0x01, 0x81, 0x01, 0xAA, 0xFF])
    element, consumed = read_element(data)
    assert element == Element(Tag(b"\x01"), memoryview(b"\xaa"))
    assert consumed == 4
    data[3] = 0
    assert bytes(element.value) == b"\xaa"
    with pytest.raises(EndError):
        read_element(b"")
    with pytest.raises(TruncatedError) as excinfo:
        read_element(b"\x01\x05\xaa")
    assert excinfo.value.offset == 2
