# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import pytest

from opentlv import (
    Format,
    Kind,
    LengthRule,
    LengthSchema,
    SchemaError,
    InvalidSchemaError,
    StructureRule,
    StructureSchema,
    Tag,
    Writer,
)


def test_length_schema_validates_within_bounds():
    tag = Tag(b"\x01")
    schema = LengthSchema([LengthRule(tag, 2, 4)])
    schema.validate_length(tag, 2)
    schema.validate_length(tag, 4)
    with pytest.raises(SchemaError):
        schema.validate_length(tag, 1)
    with pytest.raises(SchemaError):
        schema.validate_length(tag, 5)


def test_length_schema_rejects_an_unknown_tag():
    schema = LengthSchema([LengthRule(Tag(b"\x01"), 0, 4)])
    with pytest.raises(SchemaError):
        schema.validate_length(Tag(b"\x99"), 1)


def test_length_schema_exact_requires_one_length():
    tag = Tag(b"\x01")
    schema = LengthSchema([LengthRule.exact(tag, 3)])
    schema.validate_length(tag, 3)
    with pytest.raises(SchemaError):
        schema.validate_length(tag, 4)


def test_length_schema_find_and_len():
    tag = Tag(b"\x01")
    schema = LengthSchema([LengthRule(tag, 2, 4)])
    assert len(schema) == 1
    rule = schema.find(tag)
    assert rule.min_length == 2
    assert rule.max_length == 4
    assert schema.find(Tag(b"\x99")) is None


def test_length_schema_earlier_rule_wins_for_a_repeated_tag():
    tag = Tag(b"\x01")
    schema = LengthSchema([LengthRule(tag, 1, 1), LengthRule(tag, 9, 9)])
    assert schema.find(tag).min_length == 1


def test_length_constraints_use_native_endpoint_and_multiple_semantics():
    tag = Tag(b"\x01")
    schema = LengthSchema([LengthRule(tag, 2, 8, flags=1, length_multiple=2)])
    schema.validate_length(tag, 2)
    schema.validate_length(tag, 8)
    with pytest.raises(SchemaError):
        schema.validate_length(tag, 4)
    schema = LengthSchema([LengthRule(tag, 0, 8, length_multiple=3)])
    schema.validate_length(tag, 0)
    schema.validate_length(tag, 6)
    with pytest.raises(SchemaError):
        schema.validate_length(tag, 8)


def test_length_schema_rejects_sizes_outside_native_range():
    schema = LengthSchema([LengthRule(b"\x01")])
    with pytest.raises(OverflowError):
        schema.validate_length(b"\x01", -1)
    with pytest.raises(OverflowError):
        schema.validate_length(b"\x01", 1 << 100)


def test_structure_schema_accepts_a_present_required_field():
    schema = StructureSchema([StructureRule(Tag(b"\x01"), min_occurs=1, max_occurs=1)])
    schema.validate(bytes([0x01, 0x00]))


def test_structure_schema_reports_a_missing_required_field():
    schema = StructureSchema([StructureRule(Tag(b"\x01"), min_occurs=1, max_occurs=1)])
    with pytest.raises(SchemaError) as excinfo:
        schema.validate(b"")
    assert excinfo.value.offset == 0
    assert excinfo.value.kind == "missing"
    assert excinfo.value.location.kind == "scope_end"


def test_structure_schema_rejects_an_unknown_tag_by_default():
    schema = StructureSchema([StructureRule(Tag(b"\x01"), min_occurs=0)])
    with pytest.raises(SchemaError):
        schema.validate(bytes([0x02, 0x00]))


def test_structure_schema_allow_unknown_accepts_it():
    schema = StructureSchema([StructureRule(Tag(b"\x01"), min_occurs=0)], allow_unknown=True)
    schema.validate(bytes([0x02, 0x00]))


def test_structure_schema_rejects_excess_occurrences():
    schema = StructureSchema([StructureRule(Tag(b"\x01"), min_occurs=0, max_occurs=1)])
    with pytest.raises(SchemaError):
        schema.validate(bytes([0x01, 0x00, 0x01, 0x00]))


def test_structure_schema_enforces_length_bounds():
    schema = StructureSchema([StructureRule(Tag(b"\x01"), min_length=2, max_length=2)])
    with pytest.raises(SchemaError):
        schema.validate(bytes([0x01, 0x01, 0xAA]))


def test_structure_schema_validates_nested_children_in_ber():
    inner_tag = Tag(b"\x81")
    outer_tag = Tag(b"\xA0")
    child_schema = StructureSchema(
        [StructureRule(inner_tag, min_occurs=1, max_occurs=1, kind=Kind.PRIMITIVE)])
    outer_schema = StructureSchema(
        [StructureRule(outer_tag, min_occurs=1, max_occurs=1, children=child_schema)])

    inner_writer = Writer(Format.BER)
    inner_writer.write(inner_tag, b"\xAA")
    outer_writer = Writer(Format.BER)
    outer_writer.write(outer_tag, inner_writer.bytes())

    outer_schema.validate(outer_writer.bytes(), format=Format.BER)

    empty_outer = Writer(Format.BER)
    empty_outer.write(outer_tag, b"")
    with pytest.raises(SchemaError):
        outer_schema.validate(empty_outer.bytes(), format=Format.BER)


def test_structure_rule_setting_children_implies_constructed_kind():
    child_schema = StructureSchema([StructureRule(Tag(b"\x81"))])
    rule = StructureRule(Tag(b"\xA0"), children=child_schema)
    assert rule.kind == Kind.CONSTRUCTED


def test_structure_schema_len():
    schema = StructureSchema([StructureRule(Tag(b"\x01")), StructureRule(Tag(b"\x02"))])
    assert len(schema) == 2
def test_native_sequence_and_alternative_group_constraints():
    from opentlv import SchemaOrder, StructureGroup
    sequence = StructureSchema([StructureRule(b"\x01"), StructureRule(b"\x02")],
                               order=SchemaOrder.SEQUENCE)
    sequence.validate(bytes.fromhex("01000200"))
    with pytest.raises(SchemaError) as failure:
        sequence.validate(bytes.fromhex("02000100"))
    assert failure.value.offset == 2
    choice = StructureSchema([StructureRule(b"\x01", group=7), StructureRule(b"\x02", group=7)],
                             groups=[StructureGroup(7, 1, 1)])
    choice.validate(bytes.fromhex("0200"))
    with pytest.raises(SchemaError):
        choice.validate(b"")
    with pytest.raises(SchemaError):
        choice.validate(bytes.fromhex("01000200"))


def test_structural_length_policies_and_invalid_group_are_native():
    schema = StructureSchema([StructureRule(b"\x04", min_length=2, max_length=8,
                                           flags=1, length_multiple=2)])
    schema.validate(bytes.fromhex("04020000"))
    with pytest.raises(SchemaError):
        schema.validate(bytes.fromhex("040400000000"))
    schema = StructureSchema([StructureRule(b"\x04", group=7)])
    with pytest.raises(InvalidSchemaError):
        schema.validate(bytes.fromhex("0400"))
def test_bounded_schema_reports_copy_paths_and_count_omitted_issues():
    from opentlv import UnknownPolicy, TruncatedError
    schema = StructureSchema([StructureRule(b"\x01", min_occurs=1)])
    report = schema.validate_diagnostics(bytes.fromhex("0200"), capacity=1)
    assert report.total_count == 2
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].path == ()
    assert report.diagnostics[0].tag.data in (b"\x01", b"\x02")
    assert schema.validate_diagnostics(bytes.fromhex("0200"), capacity=0).total_count == 2
    allowed = schema.validate_diagnostics(bytes.fromhex("0200"), unknown=UnknownPolicy.ALLOW)
    assert allowed.total_count == 1
    assert allowed.diagnostics[0].kind_name == "missing"
    assert allowed.diagnostics[0].offset == 2
    assert allowed.diagnostics[0].location.kind == "scope_end"
    with pytest.raises(TruncatedError):
        schema.validate_diagnostics(bytes.fromhex("0201"))


def test_nested_report_owns_input_backed_tags():
    schema = StructureSchema([StructureRule(b"\x30", children=StructureSchema([
        StructureRule(b"\x04", min_length=2)]))])
    data = bytearray.fromhex("300304012A")
    report = schema.validate_diagnostics(data)
    data[:] = b"\x00" * len(data)
    del schema
    issue = report.diagnostics[0]
    assert issue.kind_name == "length"
    assert issue.tag == Tag(b"\x04")
    assert issue.path == (Tag(b"\x30"),)
    assert issue.offset == 2


def test_detailed_schema_report_owns_names_paths_and_expected_actual():
    from opentlv import SchemaBounds
    schema = StructureSchema([StructureRule(b"\x30", children=StructureSchema([
        StructureRule(b"\x04", min_length=2, max_length=8, length_multiple=2,
                      flags=1, name="payload-?")]))])
    data = bytearray.fromhex("300304012A")
    report = schema.validate_diagnostics(data)
    data[:] = b"\x00" * len(data)
    del schema
    assert report.total_count == 1
    issue = report.diagnostics[0]
    assert issue.kind_name == "length"
    assert issue.tag == Tag(b"\x04")
    assert issue.path == (Tag(b"\x30"),)
    assert issue.offset == 2
    assert issue.field == "payload-?"
    assert issue.length == SchemaBounds(2, 8, 1)
    assert issue.length_multiple == 2 and issue.length_flags == 1
    assert issue.occurrences is None and issue.form is None


def test_detailed_schema_group_bounds_capacity_and_wire_errors():
    from opentlv import SchemaBounds, StructureGroup, TruncatedError
    schema = StructureSchema([StructureRule(b"\x04", group=7)],
                             groups=[StructureGroup(7, 1, 1, name="choice")])
    issue = schema.validate_diagnostics(b"").diagnostics[0]
    assert issue.is_group and issue.field == "choice"
    assert issue.occurrences == SchemaBounds(1, 1, 0)
    assert issue.offset == 0
    assert issue.location.kind == "scope_end"
    duplicate = schema.validate_diagnostics(bytes.fromhex("04000400")).diagnostics[0]
    assert duplicate.occurrences == SchemaBounds(1, 1, 2)
    assert duplicate.offset == 2
    report = schema.validate_diagnostics(bytes.fromhex("0500"), capacity=0)
    assert report.total_count == 2 and report.diagnostics == ()
    assert len(schema.validate_diagnostics(bytes.fromhex("0500"), capacity=1).diagnostics) == 1
    with pytest.raises(TruncatedError):
        schema.validate_diagnostics(bytes.fromhex("0401"))
    with pytest.raises(ValueError):
        schema.validate_diagnostics(b"", capacity=-1)
    invalid = StructureSchema([StructureRule(b"\x04", name="bad\x00name")])
    with pytest.raises(ValueError):
        invalid.validate_diagnostics(b"")


def test_detailed_schema_form_is_reported_by_c():
    schema = StructureSchema([StructureRule(b"\x04", kind=Kind.CONSTRUCTED)])
    diagnostic = schema.validate_diagnostics(bytes.fromhex("0400")).diagnostics[0]
    assert diagnostic.form == (Kind.CONSTRUCTED, False)
    assert diagnostic.length is None


def test_schema_fixed_format_validation_and_reports():
    from opentlv import FixedFormat
    format = FixedFormat(2, 2, "little")
    schema = StructureSchema([StructureRule(b"\x00\x04", min_length=2)])
    schema.validate(bytes.fromhex("000402000102"), format)
    data = bytes.fromhex("000401002A")
    with pytest.raises(SchemaError):
        schema.validate(data, format)
    assert schema.validate_diagnostics(data, format).total_count == 1
    assert schema.validate_diagnostics(data, format).diagnostics[0].length.actual == 1


def test_deep_report_retains_outer_path_and_omitted_count():
    schema = StructureSchema([StructureRule(b"\x04", min_length=1)])
    wire = b"\x04\x00"
    for level in range(35):
        tag = b"\x70" if level == 34 else b"\x30"
        schema = StructureSchema([StructureRule(tag, children=schema)])
        wire = tag + bytes([len(wire)]) + wire
    issue = schema.validate_diagnostics(wire, max_depth=40).diagnostics[0]
    del schema, wire
    assert len(issue.path) == 32
    assert issue.path[0] == Tag(b"\x70")
    assert issue.path[1:] == (Tag(b"\x30"),) * 31
    assert issue.path_omitted == 3
    assert issue.tag == Tag(b"\x04")


def test_invalid_definition_is_independent_of_input():
    invalid_child = StructureSchema([StructureRule(b"\x04", min_length=2, max_length=1)])
    schema = StructureSchema([StructureRule(b"\x30", children=invalid_child)])
    for data in (b"", b"\x30"):
        with pytest.raises(InvalidSchemaError) as failure:
            schema.validate(data)
        assert failure.value.offset is None
        assert failure.value.kind == "definition"
        with pytest.raises(InvalidSchemaError) as failure:
            schema.validate_diagnostics(data)
        assert failure.value.offset is None
