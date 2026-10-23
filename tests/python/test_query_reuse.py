# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Reusable Query programs, plans, executions and visitor-based results."""
import ctypes

import pytest

from opentlv import (CallbackError, Document, FixedFormat, InvalidStateError, InvalidSyntaxError,
                     InvalidTagError, InvalidValueError, LimitError, Query, QueryCodecProvider,
                     QueryProgram, QueryProvider, TreeReader, TruncatedError, UnsupportedError,
                     Visit, VisitorError)
from opentlv.codec import NumberCodec, NumberEncoding

WIRE = bytes.fromhex("70065a01015001025a0103")


def test_v1_query_formats_canonically_and_visits_a_buffer_without_a_reader():
    query = Query("70/5a")
    assert query.format() == str(query) == "70/5A"
    assert repr(query) == "Query('70/5A')"
    wire = bytes.fromhex("70065a01015a0102")
    matches = []
    query.visit_buffer(wire, lambda item, depth, offset: matches.append((bytes(item.value), depth, offset)))
    assert matches == [(b"\x01", 1, 2), (b"\x02", 1, 5)]
    matches.clear()
    query.visit_buffer(bytearray(wire), lambda item, depth, offset: matches.append(offset) or Visit.STOP)
    assert matches == [2]
    with pytest.raises(TruncatedError):
        query.visit_buffer(wire[:-1], lambda *args: None)
    with pytest.raises(LimitError):
        query.visit_buffer(wire, lambda *args: None, max_elements=2)
    with pytest.raises(VisitorError):
        query.visit_buffer(wire, lambda *args: Visit.ERROR)
    sentinel = LookupError("visitor failed")
    def fail(*args):
        raise sentinel
    with pytest.raises(LookupError) as caught:
        query.visit_buffer(wire, fail)
    assert caught.value is sentinel
    flat = []
    Query("0102").visit_buffer(bytes.fromhex("01020001aa0300000001020000"), lambda item, depth, offset:
                               flat.append(offset), FixedFormat(2, 2))
    assert flat == [0, 9]


def test_static_names_compile_directly_to_the_checked_image():
    static = QueryProgram("//demo:leaf", names={"demo:leaf": b"\x5a"})
    checked = QueryProgram("//demo:leaf", resolve=lambda namespace, name: b"\x5a")
    assert static.image() == checked.image()
    assert dict(static.info) == dict(checked.info)
    assert static.evaluate(WIRE)[0].offset == 2
    with pytest.raises(InvalidTagError):
        QueryProgram("//demo:missing", names={"demo:leaf": b"\x5a"})
    with pytest.raises(LimitError):
        QueryProgram("//5A", max_text=3)


def test_native_plan_opens_without_frontend_and_reports_plan_info():
    program = QueryProgram("count(//5A[num(.) > $minimum])", variables={"minimum": int})
    plan_info = program.plan_info
    assert plan_info["scratch_size"] == plan_info["optimized_states"] == 0
    assert plan_info["program_size"] == program.info["program_size"]
    assert plan_info["variables"] == program.info["variables"] == (("minimum", 2),)
    plan = QueryProgram.open_plan(program.image())
    assert dict(plan.info) == dict(plan.plan_info) == dict(plan_info)
    assert plan.format() == "count(//5A[num(.) > $minimum])"
    assert plan.image() == program.image()
    assert plan.evaluate(bytes.fromhex("5a01055a0101"), bindings={"minimum": 2}) == 1
    with pytest.raises(InvalidValueError) as missing:
        plan.evaluate(bytes.fromhex("5a0105"))
    assert missing.value.query["query_kind_name"] == "binding"
    corrupt = bytearray(program.image())
    corrupt[0] ^= 1
    for image in (bytes(corrupt), program.image()[:-1]):
        with pytest.raises(InvalidValueError) as invalid:
            QueryProgram.open_plan(image)
        assert invalid.value.query["query_kind_name"] == "image"
    with pytest.raises(TypeError):
        QueryProgram.open_plan(program.image(), names={})
    decode = lambda value, metadata: value[0] * 10
    provided = QueryProgram("num(//5A)", providers={"num": QueryProvider(101, decode)})
    opened = QueryProgram.open_plan(provided.image(), providers={"num": QueryProvider(101, decode)})
    assert opened.evaluate(bytes.fromhex("5a0103")) == 30
    for providers in (None, {"num": QueryProvider(9, decode)}):
        with pytest.raises(UnsupportedError):
            QueryProgram.open_plan(provided.image(), providers=providers).evaluate(b"\x5a\x01\x03")


def test_execution_resets_in_place_and_keeps_its_workspace():
    program = QueryProgram("count(//5A[num(.) > $minimum])", variables={"minimum": int})
    size, alignment = program.workspace_size()
    storage = bytearray(size + alignment)
    start = (-ctypes.addressof(ctypes.c_char.from_buffer(storage))) % alignment
    execution = program.execution(workspace=memoryview(storage)[start:start + size])
    capsule = execution._capsule
    execution.bind("minimum", 2)
    execution.visit(TreeReader(bytes.fromhex("5a01055a0101")), lambda match: None)
    assert execution.result() == 1
    execution.reset()
    assert execution._capsule is capsule
    assert execution.info["elements"] == 0 and not execution.info["finished"]
    with pytest.raises(InvalidValueError):
        execution.visit(TreeReader(bytes.fromhex("5a0105")), lambda match: None)
    execution.reset()
    execution.bind("minimum", 0)
    execution.visit(TreeReader(bytes.fromhex("5a01055a0101")), lambda match: None)
    assert execution.result() == 2
    document = Document(bytes.fromhex("5a0103"))
    execution.reset()
    execution.bind("minimum", 0).evaluate_document(document)
    assert execution.result() == 1
    execution.reset()
    document.first.value = b"\x04"
    document.close()


def test_codec_provider_decodes_values_without_python_callbacks():
    little = QueryCodecProvider(105, NumberCodec(NumberEncoding.LITTLE_ENDIAN))
    program = QueryProgram("num(//5A)", providers={"num": little})
    assert program.evaluate(bytes.fromhex("5a020102")) == 0x0201
    assert QueryProgram.load(program.image(), providers={"num": little}).evaluate(
        bytes.fromhex("5a020201")) == 0x0102
    assert QueryProgram("count(//5A[num(.) = 513])", providers={"num": little}).evaluate(
        bytes.fromhex("5a0201025a0102")) == 1
    execution = program.execution().evaluate_document(Document(bytes.fromhex("5a020300")))
    assert execution.result() == 3
    with pytest.raises(InvalidValueError) as overflow:
        program.evaluate(bytes.fromhex("5a08ffffffffffffffff"))
    assert overflow.value.query["query_kind_name"] == "codec"
    assert overflow.value.codec_detail["reason_name"] == "range"
    bcd = QueryCodecProvider(106, NumberCodec(NumberEncoding.BCD, digits=4))
    decimal = QueryProgram("bcd(//5A)", providers={"bcd": bcd})
    assert decimal.evaluate(bytes.fromhex("5a021234")) == 1234
    with pytest.raises(InvalidValueError) as digit:
        decimal.evaluate(bytes.fromhex("5a021a34"))
    assert digit.value.codec_detail["reason_name"] == "digit"
    with pytest.raises(CallbackError):
        QueryProgram("text(//5A)", providers={"text": little}).evaluate(bytes.fromhex("5a0101"))
    with pytest.raises(ValueError):
        QueryCodecProvider(0, NumberCodec())
    with pytest.raises(TypeError):
        QueryCodecProvider(107, lambda value, metadata: 0)


def test_document_results_visit_resume_and_reject_mutation():
    document = Document(bytes.fromhex("70095a01015a01025a0103"))
    execution = QueryProgram("//5A").execution()
    with pytest.raises(ValueError, match="evaluate_document"):
        execution.visit_document(lambda node: None)
    execution.evaluate_document(document)
    seen = []
    execution.visit_document(lambda node: seen.append(bytes(node.value)) or Visit.STOP)
    assert bytes(execution.next().value) == b"\x02"
    execution.visit_document(lambda node: seen.append(node))
    assert seen[0] == b"\x01" and len(seen) == 2 and bytes(seen[1].value) == b"\x03"
    assert seen[1].parent == document.first
    execution.visit_document(lambda node: pytest.fail("results are exhausted"))
    guarded = QueryProgram("//5A").execution().evaluate_document(document)
    def mutate(node):
        with pytest.raises(InvalidStateError):
            node.erase()
        with pytest.raises(InvalidStateError):
            document.close()
    guarded.visit_document(mutate)
    with pytest.raises(VisitorError):
        QueryProgram("//5A").execution().evaluate_document(document).visit_document(
            lambda node: Visit.ERROR)
    sentinel = LookupError("visitor failed")
    def fail(node):
        raise sentinel
    with pytest.raises(LookupError) as caught:
        QueryProgram("//5A").execution().evaluate_document(document).visit_document(fail)
    assert caught.value is sentinel
    document.first.first_child.erase()
    assert len(document) == 3


def test_document_value_snapshot_is_measured_by_c_only_when_needed():
    wire = bytes.fromhex("70065a01015a0102")
    document = Document(wire)
    program = QueryProgram("value(//70)")
    assert program.info["constructed_values_required"] == 1
    assert program.execution().evaluate_document(document).result() == wire[2:]
    assert program.execution().evaluate_document(document, value_capacity=8).result() == wire[2:]
    with pytest.raises(LimitError):
        program.execution().evaluate_document(document, value_capacity=3)
    document.first.first_child.value = b"\x01\x02\x03"
    assert document.select(program) == bytes.fromhex("5a030102035a0102")
    assert QueryProgram("count(//5A)").info["constructed_values_required"] == 0
    assert document.select(QueryProgram("count(//5A)"), value_capacity=0) == 2


def test_document_visit_calls_back_for_path_matches_in_document_order():
    document = Document(bytes.fromhex("70065a01015a010270035a0103"))
    found = []
    document.visit("70/5a", lambda node: found.append(node))
    assert [bytes(node.value) for node in found] == [b"\x01", b"\x02", b"\x03"]
    assert found[2].parent == document.first.next
    stopped = []
    document.visit(Query("70/5A"), lambda node: stopped.append(node) or Visit.STOP)
    assert stopped == found[:1]
    document.visit("99", lambda node: pytest.fail("no node matches"))

    def mutate(node):
        with pytest.raises(InvalidStateError):
            node.value = b"\x09"
        with pytest.raises(InvalidStateError):
            document.insert(b"\x01")
    document.visit("70/5A", mutate)
    with pytest.raises(VisitorError):
        document.visit("70/5A", lambda node: Visit.ERROR)
    sentinel = LookupError("visitor failed")

    def fail(node):
        raise sentinel
    with pytest.raises(LookupError) as caught:
        document.visit("70/5A", fail)
    assert caught.value is sentinel
    with pytest.raises(InvalidSyntaxError):
        document.visit("70/5", lambda node: None)
    found[0].value = b"\x09"
    assert document.encode() == bytes.fromhex("70065a01095a010270035a0103")
    document.close()
    with pytest.raises(ValueError, match="closed"):
        document.visit("70", lambda node: None)
