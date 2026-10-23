# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import pytest

from opentlv import (BufferTooShortError, Document, InvalidSchemaError, InvalidSyntaxError,
                     OpenTLVError, Query, QueryErrorKind, QueryProgram, QueryRule, QuerySchema,
                     Reader, SchemaError, SourceLocation, TruncatedError, ValueCodec,
                     ValueConstraint, ValueConstraintKind)


def test_value_constraint_validates_decoded_values_through_c():
    ValueConstraint().validate(-2**63)
    percent = ValueConstraint.range(0, 100)
    percent.validate(100)
    with pytest.raises(SchemaError):
        percent.validate(ValueCodec.INT64_MINIMAL_BE.decode(b"\xff"))
    assert percent.name(5) is None
    color = ValueConstraint.allowed({0: "red", 1: None, 2: "blue"})
    color.validate(2)
    assert (color.name(0), color.name(1), color.name(3)) == ("red", None, None)
    with pytest.raises(SchemaError):
        color.validate(3)
    unnamed = ValueConstraint.allowed([2**63 - 1, -2**63])
    unnamed.validate(-2**63)
    assert unnamed.name(-2**63) is None and unnamed.kind is ValueConstraintKind.ALLOWED_VALUES
    assert ValueConstraint(2, allowed_values=[7]) == ValueConstraint.allowed((7,))


def test_value_constraint_definitions_are_checked_on_construction():
    with pytest.raises(InvalidSchemaError):
        ValueConstraint.range(1, 0)
    with pytest.raises(ValueError):
        ValueConstraint(3)
    with pytest.raises(ValueError):
        ValueConstraint.allowed({0: "nul\0"})
    with pytest.raises(ValueError):
        ValueConstraint(2, allowed_values=(0, 1), allowed_value_names=("one",))
    with pytest.raises(TypeError):
        ValueConstraint.allowed({0: b"red"})
    with pytest.raises(OverflowError):
        ValueConstraint.range(0, 2**63)


def test_revision_counts_successful_edits_only():
    doc = Document(bytes.fromhex("A0038101AA0200"))
    assert doc.revision == 0
    parent = doc.first
    parent.first_child.value = b"\xbb"
    doc.insert(b"\x03", b"\x01")
    with pytest.raises(TruncatedError):
        parent.value = bytes.fromhex("8102")
    assert doc.revision == 2
    parent.next.erase()
    assert doc.revision == 3 and doc.encode() == bytes.fromhex("A0038101BB030101")


def test_source_location_reports_original_coordinates_until_edited():
    wire = bytes.fromhex("3006040101040102")
    doc = Document(wire, retain_source_locations=True)
    parent = doc.first
    first, second = list(parent)
    assert parent.source_location == SourceLocation(0, 2)
    assert (first.source_location, second.source_location) == (
        SourceLocation(2, 2), SourceLocation(5, 2))
    first.value = b"\x01\x02\x03"
    # The edited node and its ancestors lose their coordinates; siblings keep theirs.
    assert first.source_location == SourceLocation(None, None)
    assert parent.source_location == SourceLocation(None, None)
    assert second.source_location == SourceLocation(5, 2)
    assert parent.insert(b"\x05").source_location == SourceLocation(None, None)
    assert Document(wire).first.source_location == SourceLocation(None, None)


def test_core_identity_detects_retired_nodes_after_address_reuse():
    doc = Document(bytes.fromhex("A0038101AA"))
    parent = doc.first
    child = parent.first_child
    identity = child.identity
    for value in range(16):
        # Each replacement retires the old child; its allocation may be reused.
        parent.value = bytes([0x81, 0x01, value])
        with pytest.raises(ValueError, match="no longer valid"):
            child.value
    current = parent.first_child
    assert current.identity != identity and current.value == b"\x0f"
    assert hash(child) == hash(identity) and child != current
    # Edits that retire no node leave every handle valid.
    sibling = doc.insert(b"\x02")
    current.value = b"\x01"
    assert parent.first_child == current and sibling.identity not in (identity, current.identity)


def test_preserve_into_reports_required_and_available_capacity():
    wire = bytes.fromhex("0481012A")
    decoded = Reader(wire).read_source()
    output = bytearray(b"!!!!!!")
    with pytest.raises(BufferTooShortError) as failed:
        decoded.preserve_into(output, offset=3)
    assert output == b"!!!!!!"
    assert (failed.value.required, failed.value.available) == (4, 3)
    assert failed.value.operation == "preserve" and failed.value.offset == 3
    assert decoded.preserve_into(output, offset=2) == 4
    assert output == b"!!" + wire


@pytest.mark.parametrize("create", [lambda text: Query(text),
                                    lambda text: Document(b"\x5a\x00").find_path(text)])
@pytest.mark.parametrize("text, begin", [("5a\x0001", 2), ("5a/é", 3)])
def test_path_query_text_is_parsed_with_its_explicit_length(create, text, begin):
    with pytest.raises(InvalidSyntaxError) as caught:
        create(text)
    assert caught.value.query["query_kind"] is QueryErrorKind.SYNTAX
    assert caught.value.location.domain == "expression"
    assert caught.value.location.begin == begin


def test_diagnostic_path_text_is_formatted_by_c():
    schema = QuerySchema([QueryRule(QueryProgram("//5A"), QueryProgram("1 = 0"))])
    with pytest.raises(SchemaError) as caught:
        schema.validate_buffer(bytes.fromhex("70025a00"))
    assert caught.value.path == (b"\x70",) and caught.value.path_text == "70"
    wire = b"\x5a\x00"
    for level in range(35):
        wire = bytes([0x70 if level == 34 else 0x30, len(wire)]) + wire
    with pytest.raises(SchemaError) as caught:
        schema.validate_buffer(wire)
    assert caught.value.path_omitted == 3
    # Core marks the omitted outer tags.
    assert caught.value.path_text == "70" + " > 30" * 31 + " > ..."
    with pytest.raises(OpenTLVError) as caught:
        QueryProgram("count(//5A)").execution().result()
    assert caught.value.path is None and caught.value.path_text is None
