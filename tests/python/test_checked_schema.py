# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Structural schemas checked once and reused for validation."""
import pytest

from opentlv import (CheckedStructureSchema, FixedFormat, InvalidSchemaError, SchemaError,
                     StructureRule, StructureSchema)


def test_checked_schema_reuses_one_owned_definition_check():
    rule = StructureRule(b"\x01", min_occurs=1, max_occurs=1, max_length=2)
    schema = StructureSchema([rule, StructureRule(b"\x30", children=StructureSchema(
        [StructureRule(b"\x04", min_occurs=1)]))])
    checked = schema.check()
    assert isinstance(checked, CheckedStructureSchema)
    for data in (bytes.fromhex("0100"), bytes.fromhex("0101aa30020400")):
        checked.validate(data)
        schema.validate(data)
    for data in (b"", bytes.fromhex("0103000000"), bytes.fromhex("01003000")):
        with pytest.raises(SchemaError) as unchecked:
            schema.validate(data)
        with pytest.raises(SchemaError) as prepared:
            checked.validate(data)
        assert (prepared.value.kind, prepared.value.offset) == (unchecked.value.kind,
                                                                unchecked.value.offset)
    data = bytes.fromhex("0100010003000200")
    assert checked.validate_diagnostics(data) == schema.validate_diagnostics(data)
    assert checked.validate_diagnostics(data, capacity=0).total_count == 3
    rule.max_length = 0
    schema.rules.clear()
    del rule
    checked.validate(bytes.fromhex("0101aa"))
    with pytest.raises(SchemaError):
        schema.validate(bytes.fromhex("0101aa"))
    with pytest.raises(TypeError):
        CheckedStructureSchema()


def test_checked_schema_rejects_invalid_definitions_once():
    duplicate = StructureSchema([StructureRule(b"\x04"), StructureRule(b"\x04")])
    for check in (duplicate.check, duplicate.check_definition):
        with pytest.raises(InvalidSchemaError) as failure:
            check()
        assert failure.value.kind == "definition"
        assert failure.value.definition_index == 1
        assert failure.value.offset is None
    StructureSchema([StructureRule(b"\x04")]).check_definition()
    reversed_child = StructureSchema([StructureRule(b"\x04", min_length=2, max_length=1)])
    with pytest.raises(InvalidSchemaError):
        StructureSchema([StructureRule(b"\x30", children=reversed_child)]).check()



def test_checked_schema_uses_the_format_given_per_call():
    checked = StructureSchema([StructureRule(b"\x01\x02", max_length=1)]).check()
    checked.validate(bytes.fromhex("0102000101"), FixedFormat(2, 2))
    with pytest.raises(SchemaError):
        checked.validate(bytes.fromhex("010200020101"), FixedFormat(2, 2))
    report = checked.validate_diagnostics(bytes.fromhex("010200020101"), FixedFormat(2, 2))
    assert report.diagnostics[0].length.actual == 2
