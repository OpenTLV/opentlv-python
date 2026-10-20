# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
import pytest
from opentlv import (QueryProgram, OpenTLVError, QueryErrorKind, CodecOperation,
                     CodecCause, CodecViolation, ReaderOperation, WriterOperation,
                     SchemaIssue, SchemaDefinitionKind, Severity, Query, Document,
                     InvalidSyntaxError, LimitError, Location)


@pytest.mark.parametrize("category,value,label", [
    (QueryErrorKind, QueryErrorKind.STATE, "state"),
    (CodecOperation, CodecOperation.MEASURE, "measure"),
    (CodecCause, CodecCause.READER, "reader"),
    (CodecViolation, CodecViolation.UTF8, "utf8"),
    (ReaderOperation, ReaderOperation.HEADER, "header"),
    (WriterOperation, WriterOperation.END, "end"),
    (SchemaIssue, SchemaIssue.MISSING, "missing"),
    (SchemaDefinitionKind, SchemaDefinitionKind.COMPONENT, "component"),
    (Severity, Severity.WARNING, "warning"),
])
def test_canonical_names_and_unknown_values(category, value, label):
    assert value.label == label
    assert category(9876).value == 9876
    assert category(9876).label == "unknown"
    assert category(9876) is category(9876)
    assert category(2 ** 40).label == "unknown"


def test_query_without_reader_preserves_expression_location():
    with pytest.raises(OpenTLVError) as caught:
        QueryProgram("/")
    error = caught.value
    assert error.query["query_kind"] is QueryErrorKind.SYNTAX
    assert error.query["query_kind_name"] == "syntax"
    assert error.location.domain == "expression"
    assert error.location.kind != "unknown"
    assert error.offset == error.location.begin == 1
    # The primary expression span is not repeated as related evidence.
    assert error.query["expression"].kind == "unknown"
    assert error.operation is None
    assert error.severity is Severity.ERROR


@pytest.mark.parametrize("create", [lambda text: Query(text),
                                    lambda text: Document(b"\x5a\x00").find_path(text)])
def test_path_query_parse_failure_is_a_query_syntax_error(create):
    with pytest.raises(InvalidSyntaxError) as caught:
        create("01/")
    error = caught.value
    assert error.query["query_kind"] is QueryErrorKind.SYNTAX
    assert error.location == Location("expression", "span", 3, 3)
    assert error.operation is None and error.tag is None


@pytest.mark.parametrize("text, limit, configured", [
    ("/".join(["5a"] * 66), "path-steps", 65), ("5a" * 513, "path-bytes", 512)])
def test_path_query_limit_names_its_bound(text, limit, configured):
    with pytest.raises(LimitError) as caught:
        Query(text)
    assert caught.value.query["query_kind"] is QueryErrorKind.LIMIT
    assert (caught.value.query["limit"], caught.value.query["configured"]) == (limit, configured)


def test_absent_location_does_not_become_byte_zero():
    execution = QueryProgram("count(//5A)").execution()
    with pytest.raises(OpenTLVError) as caught:
        execution.result()
    assert caught.value.query["query_kind"] is QueryErrorKind.STATE
    assert caught.value.location.kind == "unknown"
    assert caught.value.offset is None


def test_absent_reader_path_is_not_inferred_from_input():
    wire = b"\x5a\x03\x00"
    for _ in range(35):
        wire = bytes([0x70, len(wire)]) + wire
    with pytest.raises(OpenTLVError) as caught:
        QueryProgram("//5A").evaluate(wire)
    assert caught.value.query["query_kind"] is QueryErrorKind.READER
    assert caught.value.path is None
    assert caught.value.path_omitted == 0
