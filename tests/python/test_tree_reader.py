# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import gc
import pytest
from opentlv import (Reader, TreeReader, Format, FixedFormat, NeedMoreDataError,
                     TruncatedError, LimitError, InvalidArgError, InvalidSyntaxError)
from opentlv import Query, Visit


def test_incremental_reader_owns_old_views_and_preserves_offsets():
    data = b"\x04\x01\x2a\x04\x01\x2b"
    reader = Reader(data[:2], final_input=False)
    with pytest.raises(NeedMoreDataError):
        next(reader)
    assert not reader.at_end
    reader.set_input(data[:4])
    first = reader.read_source()
    assert first.layout.value == (2, 1)
    reader.set_input(data[3:4], discard=3)
    with pytest.raises(NeedMoreDataError) as error:
        next(reader)
    assert error.value.offset == 4
    assert reader.offset == 3
    reader.set_input(data[3:], final_input=True)
    assert bytes(next(reader).value) == b"\x2b"
    assert reader.at_end
    del reader
    gc.collect()
    assert bytes(first.encoded) == data[:3]


def test_complete_parent_and_limit_recovery():
    data = b"\x30\x02\x04\x00\x04\x00"
    tree = TreeReader(data[:3], final_input=False, frame_capacity=0, max_depth=0, max_elements=2)
    with pytest.raises(NeedMoreDataError):
        next(tree)
    assert tree.offset == 0
    tree.set_input(data, final_input=True)
    assert next(tree).constructed
    with pytest.raises(LimitError):
        next(tree)
    tree.skip_subtree()
    assert next(tree).offset == 4
    assert tree.at_end


def test_tree_preorder_and_rebinding():
    data = b"\x30\x04\x04\x00\x04\x00\x04\x01\x2a"
    tree = TreeReader(data[:6], final_input=False)
    for offset, depth in [(0, 0), (2, 1), (4, 1)]:
        item = next(tree)
        assert (item.offset, item.depth) == (offset, depth)
    with pytest.raises(NeedMoreDataError):
        next(tree)
    tree.set_input(data[6:], discard=6, final_input=True)
    assert next(tree).offset == 6
    assert list(tree) == []


def test_malformed_child_diagnostic_and_snapshot_ownership():
    data = bytearray(b"\x30\x02\x04\x01")
    tree = TreeReader(data, final_input=False)
    data[:] = b"\x00" * len(data)
    assert next(tree).element.tag.data == b"\x30"
    with pytest.raises(TruncatedError) as error:
        next(tree)
    assert error.value.offset == 4
    assert tree.offset == 2


def test_fixed_and_rejected_window_leave_original_cursor_usable():
    reader = Reader(b"\x01\x00", FixedFormat(1, 1), final_input=False)
    with pytest.raises(InvalidArgError):
        reader.set_input(b"\x02\x00")
    assert reader.offset == 0
    assert next(reader).tag.data == b"\x01"
    reader.set_input(b"", discard=2, final_input=True)
    assert reader.at_end


def test_visitor_stop_exceptions_reentry_and_resume():
    reader = Reader(b"\x04\x00\x05\x00", final_input=False)
    reader.visit(lambda element: Visit.STOP)
    assert reader.offset == 2
    with pytest.raises(RuntimeError):
        reader.visit(lambda element: next(reader))
    assert reader.offset == 4
    with pytest.raises(NeedMoreDataError):
        reader.visit(lambda element: None)
    reader.set_input(b"", discard=4, final_input=True)
    reader.visit(lambda element: pytest.fail("no callbacks after EOF"))


def test_query_continuation_owns_query_and_callback_values():
    data = b"\x30\x04\x04\x00\x04\x00\x30\x02\x04\x00"
    tree = TreeReader(data[:6], final_input=False)
    matcher = Query("30/04").matcher()
    offsets = []
    retained = []

    def match(element, depth, offset):
        retained.append(element)
        offsets.append(offset)
        assert depth == 1
        return Visit.STOP if len(offsets) == 1 else Visit.CONTINUE

    matcher.visit(tree, match)
    with pytest.raises(NeedMoreDataError):
        matcher.visit(tree, match)
    tree.set_input(data[6:], discard=6, final_input=True)
    matcher.visit(tree, match)
    assert offsets == [2, 4, 8]
    del tree, matcher
    gc.collect()
    assert [bytes(element.value) for element in retained] == [b"", b"", b""]
    with pytest.raises(InvalidSyntaxError) as error:
        Query("30/")
    assert error.value.offset == 3


def test_immutable_bytes_remain_zero_copy_and_tree_visitor_can_skip():
    data = b"\x30\x02\x04\x00\x04\x01\x2a"
    item = next(TreeReader(data))
    assert item.decoded.encoded.obj is data
    tree = TreeReader(data)
    tree.visit(lambda element, depth, offset: Visit.STOP)
    tree.skip_subtree()
    assert bytes(next(tree).element.value) == b"\x2a"
    assert tree.at_end


def test_reader_field_diagnostics_retain_source_coordinates():
    reader = Reader(b"\x04\x03\x2a")
    with pytest.raises(TruncatedError) as error:
        next(reader)
    assert error.value.tag_offset == 0
    assert error.value.length_offset == 1
    assert error.value.value_offset == 2
    assert error.value.enclosing_end == 3
def test_preservation_retains_source_and_rejects_content_changes():
    from dataclasses import replace
    from opentlv import Reader, Writer, Element, Tag, InvalidArgError, BufferTooShortError
    wire = bytes.fromhex("0481012A")
    reader = Reader(wire, final_input=False)
    decoded = reader.read_source()
    reader.set_input(b"", discard=4, final_input=True)
    del reader
    assert decoded.preserve() == wire
    changed = replace(decoded, element=Element(Tag(b"\x04"), memoryview(b"\x2b")))
    with pytest.raises(InvalidArgError):
        changed.preserve()
    output = bytearray(b"!!")
    with pytest.raises(BufferTooShortError) as failed:
        decoded.preserve_into(output)
    assert output == b"!!"
    assert failed.value.required == 4
    writer = Writer()
    writer.copy_encoded(b"prefix")
    writer.preserve(decoded)
    assert writer.bytes() == b"prefix" + wire
