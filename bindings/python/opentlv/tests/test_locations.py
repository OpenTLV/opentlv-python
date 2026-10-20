# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import pytest

from opentlv import InvalidSyntaxError, Location, Query, SchemaError, StructureRule, StructureSchema


@pytest.mark.parametrize("text, begin, end", [("GG", 0, 1), ("01/", 3, 3), ("", 0, 0)])
def test_path_syntax_has_expression_evidence_including_empty_eof(text, begin, end):
    with pytest.raises(InvalidSyntaxError) as failed:
        Query(text)
    assert failed.value.location == Location("expression", "span", begin, end)


def test_missing_content_at_zero_has_a_known_scope_boundary():
    schema = StructureSchema([StructureRule(b"\x01", min_occurs=1)])
    with pytest.raises(SchemaError) as failed:
        schema.validate(b"")
    assert failed.value.location == Location("input", "scope_end", 0, 0)
