# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import gc
import pytest
from opentlv import (TreeWriter, Element, Tag, Format, BufferTooShortError,
                     CallbackError, InvalidArgError, InvalidStateError, InvalidValueError, LimitError)


def test_tree_writer_retains_tags_and_only_exposes_finalized_output():
    writer = TreeWriter(32)
    tag = bytearray(b"\x30")
    writer.begin(tag)
    tag[:] = b"\x01"
    del tag
    gc.collect()
    writer.write(Element(Tag(b"\x04"), memoryview(b"\x2a")))
    assert writer.bytes() == b""
    with pytest.raises(InvalidStateError):
        writer.finish()
    writer.end()
    assert writer.finish() == b"\x30\x03\x04\x01\x2a"


def test_cer_closing_and_item_limit_preserve_finalized_bytes():
    writer = TreeWriter(32, Format.CER, max_elements=2)
    writer.begin(b"\x30")
    writer.write(Element(Tag(b"\x04"), memoryview(b"\x2a")))
    writer.end()
    expected = b"\x30\x80\x04\x01\x2a\x00\x00"
    assert writer.finish() == expected
    with pytest.raises(LimitError):
        writer.begin(b"\x30")
    assert writer.bytes() == expected


def test_scratch_exhaustion_leaves_parent_open():
    writer = TreeWriter(32, scratch_capacity=0)
    writer.begin(b"\x30")
    writer.write(Element(Tag(b"\x04"), memoryview(b"\x2a")))
    with pytest.raises(BufferTooShortError):
        writer.end()
    with pytest.raises(InvalidStateError):
        writer.finish()
    assert writer.bytes() == b""


def measurement_items():
    yield Element(Tag(b"\x30"), memoryview(b"ignored")), 0, True
    yield Element(Tag(b"\x04"), memoryview(b"\x2a")), 1, False
    yield Element(Tag(b"\x30"), memoryview(b"")), 1, True


@pytest.mark.parametrize("format, expected", [
    (Format.BER, "300504012A3000"),
    (Format.CER, "308004012A308000000000"),
])
def test_measurement_stages_exact_encoding_with_empty_parents(format, expected):
    encoded = TreeWriter.measure(measurement_items(), 32, format)
    assert encoded == bytes.fromhex(expected)


def test_measurement_exposes_workspace_requirements_and_validates_source():
    with pytest.raises(BufferTooShortError) as failed:
        TreeWriter.measure(measurement_items(), 32, scratch_capacity=0)
    assert failed.value.required_scratch == 5
    assert failed.value.required_data == 0
    with pytest.raises(BufferTooShortError) as failed:
        TreeWriter.measure(measurement_items(), 2)
    assert failed.value.required_data == 3
    with pytest.raises(CallbackError):
        TreeWriter.measure([(Element(Tag(b"\x04"), memoryview(b"")), 1, False)], 32)
    with pytest.raises(BufferTooShortError):
        TreeWriter.measure(measurement_items(), 32, frame_capacity=0)


def test_measurement_propagates_source_exception_after_native_return():
    def broken():
        yield next(measurement_items())
        raise RuntimeError("source failed")
    with pytest.raises(RuntimeError, match="source failed"):
        TreeWriter.measure(broken(), 32)
    assert TreeWriter.measure([], 0) == b""


def test_canonical_events_roundtrip_and_skipped_rejection():
    from opentlv import TreeReader, TreeEventKind
    data = bytes.fromhex("300704012A30020400")
    reader = TreeReader(data)
    writer = TreeWriter(64)
    kinds = []
    while not reader.at_end:
        event = reader.next_event()
        kinds.append(event.kind)
        writer.write_event(event)
    assert kinds == [TreeEventKind.BEGIN, TreeEventKind.ELEMENT, TreeEventKind.BEGIN,
                     TreeEventKind.ELEMENT, TreeEventKind.END, TreeEventKind.END]
    assert writer.finish() == data
    reader = TreeReader(data)
    writer = TreeWriter(64)
    writer.write_event(reader.next_event())
    reader.skip_subtree()
    end = reader.next_event()
    assert end.kind == TreeEventKind.END and end.skipped and end.item is None
    with pytest.raises(InvalidValueError):
        writer.write_event(end)


def test_event_parent_payload_survives_input_replacement():
    from opentlv import TreeReader, TreeEventKind
    reader = TreeReader(bytes.fromhex("30020400"), final_input=False)
    begin = reader.next_event()
    writer = TreeWriter(32)
    writer.write_event(begin)
    reader.set_input(bytes.fromhex("0400"), discard=2, final_input=True)
    del begin
    gc.collect()
    writer.write_event(reader.next_event())
    end = reader.next_event()
    assert end.kind == TreeEventKind.END and end.item is None
    writer.write_event(end)
    assert writer.finish() == bytes.fromhex("30020400")


def test_event_measurement_and_bounded_tags():
    from opentlv import TreeReader
    data = bytes.fromhex("30020400")
    reader = TreeReader(data)
    events = []
    while not reader.at_end:
        events.append(reader.next_event())
    assert TreeWriter.measure_events(events, 32) == data
    with pytest.raises(InvalidValueError):
        TreeWriter.measure_events(events[:-1], 32)
    writer = TreeWriter(32)
    writer.set_tag_capacity(0)
    with pytest.raises(BufferTooShortError):
        writer.write_event(events[0])
    writer.set_tag_capacity(1)
    for event in events:
        writer.write_event(event)
    assert writer.finish() == data
    writer.set_tag_capacity(None)
