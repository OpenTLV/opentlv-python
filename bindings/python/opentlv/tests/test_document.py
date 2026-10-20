# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import pytest

from opentlv import Document, TruncatedError, Format, Node, Tag, Writer


def test_pipeline_materializes_matched_current_subtree_without_repull():
    from opentlv import DocumentBuilder, TreeReader, Query, NeedMoreDataError
    wire = bytes.fromhex("01003005310304012A0400")
    reader = TreeReader(wire[:3], final_input=False)
    matcher = Query("30/31").matcher()
    assert not matcher.matches(next(reader).element.tag, 0)
    with pytest.raises(NeedMoreDataError):
        next(reader)
    reader.set_input(wire[2:], discard=2, final_input=True)
    while True:
        item = next(reader)
        if matcher.matches(item.element.tag, item.depth):
            break
    assert item.offset == 4
    with DocumentBuilder(reader, current_subtree=True) as builder:
        document = builder.consume()
    document.first.first_child.value = b"\x07\x08"
    assert document.encode() == bytes.fromhex("310404020708")
    assert next(reader).offset == 9


@pytest.mark.parametrize("invalidate", ["input", "skip", "visit", "query", "eof"])
def test_current_subtree_rejects_invalidated_selection(invalidate):
    from opentlv import DocumentBuilder, TreeReader, Query, InvalidArgError
    wire = bytes.fromhex("300304012A")
    reader = TreeReader(wire)
    with pytest.raises(InvalidArgError):
        DocumentBuilder(reader, current_subtree=True)
    next(reader)
    if invalidate == "input":
        reader.set_input(wire, final_input=True)
    elif invalidate == "skip":
        reader.skip_subtree()
    elif invalidate == "visit":
        reader.visit(lambda *_: None)
    elif invalidate == "query":
        Query("30/04").matcher().visit(reader, lambda *_: None)
    else:
        list(reader)
        with pytest.raises(StopIteration):
            next(reader)
    with pytest.raises(InvalidArgError):
        DocumentBuilder(reader, current_subtree=True)


def test_parses_and_iterates_top_level_nodes():
    data = bytes([0x01, 0x02, 0xAA, 0xBB, 0x02, 0x00])
    doc = Document(data)
    assert len(doc) == 2
    nodes = list(doc)
    assert len(nodes) == 2
    assert nodes[0].tag == Tag(b"\x01")
    assert nodes[0].value == b"\xaa\xbb"
    assert nodes[0].is_constructed is False
    assert nodes[1].value == b""


def test_empty_document_has_no_nodes():
    doc = Document()
    assert len(doc) == 0
    assert doc.first is None
    assert list(doc) == []


def test_set_value_and_encode():
    doc = Document(bytes([0x01, 0x02, 0xAA, 0xBB]))
    doc.first.value = b"\xcc"
    assert doc.encode() == bytes([0x01, 0x01, 0xCC])
    assert doc.encoded_size == len(doc.encode())


def test_insert_appends_by_default():
    doc = Document(bytes([0x01, 0x00]))
    node = doc.insert(Tag(b"\x02"), b"\x99")
    assert list(doc)[-1] == node
    assert node.value == b"\x99"


def test_insert_before_an_existing_sibling():
    doc = Document(bytes([0x02, 0x00]))
    existing = doc.first
    doc.insert(Tag(b"\x01"), b"", before=existing)
    tags = [node.tag for node in doc]
    assert tags == [Tag(b"\x01"), Tag(b"\x02")]


def test_erase_removes_a_node_and_its_descendants():
    doc = Document(bytes([0x01, 0x00, 0x02, 0x00]))
    first, second = list(doc)
    first.erase()
    assert len(doc) == 1
    assert list(doc) == [second]


def test_erase_via_document_insert_result_round_trips():
    doc = Document()
    node = doc.insert(Tag(b"\x01"), b"\xaa")
    assert doc.encode() == bytes([0x01, 0x01, 0xAA])
    node.erase()
    assert doc.encode() == b""


def test_nested_ber_navigation():
    inner = Writer(Format.BER)
    inner.write(Tag(b"\x81"), b"\xAA")
    outer = Writer(Format.BER)
    outer.write(Tag(b"\xA0"), inner.bytes())

    doc = Document(outer.bytes(), Format.BER)
    top = doc.first
    assert top.is_constructed is True
    assert top.value == b""
    child = top.first_child
    assert child.tag == Tag(b"\x81")
    assert child.value == b"\xAA"
    assert child.parent == top
    assert list(top) == [child]


def test_find_and_find_path():
    inner = Writer(Format.BER)
    inner.write(Tag(b"\x81"), b"\xAA")
    outer = Writer(Format.BER)
    outer.write(Tag(b"\xA0"), inner.bytes())
    doc = Document(outer.bytes(), Format.BER)

    top = doc.find(Tag(b"\xA0"))
    assert top == doc.first
    child = doc.find(Tag(b"\x81"), parent=top)
    assert child == top.first_child
    assert doc.find_path("A0/81") == child
    assert doc.find(Tag(b"\x99")) is None
    assert doc.find_path("99") is None


def test_next_same_tag_skips_other_tags():
    doc = Document(bytes([0x01, 0x00, 0x02, 0x00, 0x01, 0x00]))
    first, second, third = list(doc)
    assert first.next_same_tag() == third
    assert second.next_same_tag() is None


def test_insert_a_constructed_value_from_raw_nested_encoding():
    grandchild = Writer(Format.BER)
    grandchild.write(Tag(b"\x82"), b"\x01")
    doc = Document(format=Format.BER)
    node = doc.insert(Tag(b"\xA1"), grandchild.bytes())
    assert node.is_constructed is True
    assert node.first_child.tag == Tag(b"\x82")


def test_node_equality_and_hash():
    doc = Document(bytes([0x01, 0x00, 0x02, 0x00]))
    first, second = list(doc)
    assert first == doc.first
    assert first != second
    assert first != "not a node"
    assert hash(first) == hash(doc.first)


def test_node_encode_and_encoded_size():
    doc = Document(bytes([0x01, 0x02, 0xAA, 0xBB]))
    node = doc.first
    assert node.encode() == bytes([0x01, 0x02, 0xAA, 0xBB])
    assert node.encoded_size == 4


def test_close_invalidates_the_document():
    with Document(bytes([0x01, 0x00])) as doc:
        assert len(doc) == 1
    with pytest.raises(ValueError):
        len(doc)


def test_repr_shows_count_and_tag():
    doc = Document(bytes([0x01, 0x00, 0x02, 0x00]))
    assert repr(doc) == "Document(count=2)"
    assert "Tag(01)" in repr(doc.first)
    assert "primitive" in repr(doc.first)


def test_document_parse_reports_truncated_input():
    with pytest.raises(TruncatedError):
        Document(bytes([0x01, 0x05, 0xAA]))


def test_document_accepts_bytearray_and_memoryview():
    for data in (bytearray([0x01, 0x00]), memoryview(bytes([0x01, 0x00]))):
        doc = Document(data)
        assert len(doc) == 1


def test_isinstance_node():
    doc = Document(bytes([0x01, 0x00]))
    assert isinstance(doc.first, Node)


def test_closed_document_rejects_retained_nodes():
    doc = Document(b"\x01\x00")
    node = doc.first
    doc.close()
    for operation in (lambda: node.tag, lambda: node.value, lambda: node.parent,
                      lambda: node.first_child, lambda: node.next, node.encode,
                      node.erase, lambda: setattr(node, "value", b"")):
        with pytest.raises(ValueError):
            operation()


def test_erasing_invalidates_aliases_and_descendants_only():
    doc = Document(bytes.fromhex("A0038101AA0200"))
    parent = doc.first
    alias = doc.first
    child = parent.first_child
    sibling = parent.next
    child_hash = hash(child)
    parent.erase()
    assert hash(child) == child_hash
    assert alias == parent
    for node in (parent, alias, child):
        with pytest.raises(ValueError):
            node.encode()
    assert sibling.tag == Tag(b"\x02")
    replacement = doc.insert(b"\xA0", bytes.fromhex("8101BB"))
    assert replacement != parent
    assert replacement.first_child != child


def test_replacing_children_keeps_parent_and_unrelated_handles_valid():
    doc = Document(bytes.fromhex("A0038101AA0200"))
    parent = doc.first
    alias = doc.first
    child = parent.first_child
    sibling = parent.next
    with pytest.raises(TruncatedError):
        parent.value = bytes.fromhex("8102")
    assert child.value == b"\xaa"
    parent.value = bytes.fromhex("8101BB")
    with pytest.raises(ValueError):
        child.value
    assert alias.first_child.value == b"\xbb"
    assert sibling.tag == Tag(b"\x02")


def test_descendant_keeps_ancestor_lifetime_without_parent_wrapper():
    import gc
    doc = Document(bytes.fromhex("A0038101AA"))
    child = doc.first.first_child
    gc.collect()
    doc.first.erase()
    with pytest.raises(ValueError):
        child.tag


def test_foreign_and_stale_nodes_rejected_before_native_access():
    doc = Document(b"\x01\x00")
    foreign = Document(b"\x01\x00").first
    with pytest.raises(ValueError):
        doc.find(b"\x01", parent=foreign)
    with pytest.raises(ValueError):
        doc.insert(b"\x02", before=foreign)
    stale = doc.first
    stale.erase()
    with pytest.raises(ValueError):
        doc.insert(b"\x02", before=stale)
    with pytest.raises(TypeError):
        Node(doc, 1)


def test_builder_resumes_and_excludes_cursor_mutations():
    from opentlv import DocumentBuilder, TreeReader, NeedMoreDataError, Query
    reader = TreeReader(b"\x01\x00", final_input=False)
    with DocumentBuilder(reader) as builder:
        for operation in (lambda: next(reader), reader.skip_subtree,
                          lambda: reader.visit(lambda *args: None),
                          lambda: Query("01").matcher().visit(reader, lambda *args: None)):
            with pytest.raises(RuntimeError):
                operation()
        with pytest.raises(NeedMoreDataError):
            builder.consume()
        assert reader.consumed == 2
        reader.set_input(b"\x02\x01\x2a", discard=2, final_input=True)
        document = builder.consume()
        assert document.encode() == b"\x01\x00\x02\x01\x2a"
        with pytest.raises(ValueError):
            builder.consume()
    assert reader.at_end


def test_builder_keeps_format_alive_and_leaves_following_sibling_unread():
    from opentlv import DocumentBuilder, TreeReader
    import gc
    reader = TreeReader(bytes.fromhex("300304012A0402"))
    with DocumentBuilder(reader, next_subtree=True) as builder:
        document = builder.consume()
    with pytest.raises(TruncatedError):
        next(reader)
    del builder, reader
    gc.collect()
    assert document.encode() == bytes.fromhex("300304012A")
    document.first.value = bytes.fromhex("04012B")
    assert document.encode() == bytes.fromhex("300304012B")


def test_builder_abandonment_and_terminal_failure_release_reader():
    from opentlv import DocumentBuilder, TreeReader
    reader = TreeReader(b"\x01\x00")
    builder = DocumentBuilder(reader)
    builder.close()
    assert next(reader).element.tag == Tag(b"\x01")
    reader = TreeReader(b"\x01\x02")
    builder = DocumentBuilder(reader)
    with pytest.raises(TruncatedError):
        builder.consume()
    with pytest.raises(TruncatedError):
        next(reader)


def test_document_and_node_destination_encoding_are_delegated_to_c():
    document = Document(bytes.fromhex("300304012A"), Format.BER)
    expected = bytes.fromhex("308004012A0000")
    assert document.encoded_size_as(Format.CER) == len(expected)
    assert document.first.encoded_size_as(Format.CER) == len(expected)
    assert document.encode(Format.CER) == expected
    assert document.first.encode(Format.CER) == expected
    assert document.encode() == bytes.fromhex("300304012A")


@pytest.mark.parametrize("operation", ["node_erase", "node_set_value"])
def test_interrupt_after_native_mutation_cannot_leave_live_stale_handles(monkeypatch, operation):
    import _opentlv
    doc = Document(bytes.fromhex("300304012A"))
    parent = doc.first
    child = parent.first_child
    native = getattr(_opentlv, operation)

    def interrupted(*args):
        native(*args)
        raise KeyboardInterrupt

    monkeypatch.setattr(_opentlv, operation, interrupted)
    with pytest.raises(KeyboardInterrupt):
        if operation == "node_erase":
            parent.erase()
        else:
            parent.value = b""
    with pytest.raises(ValueError):
        child.value
