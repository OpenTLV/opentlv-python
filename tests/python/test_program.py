# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
import _opentlv as _native
from opentlv import TruncatedError
import gc
import pytest
from opentlv import (QueryProgram, TreeReader, Visit, Document, InvalidArgError, InvalidStateError,
                     NeedMoreDataError, LimitError, BufferTooShortError, QueryProvider,
                     InvalidValueError, CallbackError, QueryRule, QuerySchema, SchemaError, UnsupportedError)
from opentlv import (QueryTagAdapter, QueryDefinitionResolver, Definition, DefinitionRegistry,
                     FixedFormat, Query, query_emv_resolve, Location)

WIRE = bytes.fromhex("70065a01015001025a0103")


def test_v1_resumable_matcher_rebind_reset_and_emv_names():
    matcher = Query("70/5A").matcher()
    assert not matcher.matches(b"\x70", 0)
    with pytest.raises(InvalidArgError):
        matcher.rebind(Query("70/50"))
    matcher.rebind(Query("70/5a"))
    gc.collect()
    assert matcher.matches(b"\x5a", 1)
    matcher.reset()
    assert not matcher.matches(b"\x5a", 1)
    reader = TreeReader(bytes.fromhex("70035a0101"), final_input=False)
    matches = []
    matcher.visit(reader, lambda item, depth, offset: matches.append(bytes(item.value)) or Visit.STOP)
    matcher.rebind(Query("70/5A"))
    with pytest.raises(NeedMoreDataError):
        matcher.visit(reader, lambda *args: None)
    reader.set_input(bytes.fromhex("70035a010170035a0102"), final_input=True)
    matcher.visit(reader, lambda item, depth, offset: matches.append(bytes(item.value)))
    assert matches == [b"\x01", b"\x02"]
    import _opentlv
    if _opentlv.HAS_EMV:
        assert query_emv_resolve("emv", "PAN") == b"\x5a"
        assert QueryProgram("count(//emv:PAN)", resolve=query_emv_resolve).evaluate(b"\x5a\0") == 1


def test_query_tag_adapter_dynamic_resolver_fixed_format_and_owned_image():
    format = FixedFormat(2, 2, "little")
    seen = []
    tags = QueryTagAdapter(301, class_of=lambda raw: 7, number_of=lambda raw: raw[0])
    def resolve(namespace, name):
        seen.append((namespace, name))
        return b"\x5a\0" if (namespace, name) == ("demo", "leaf") else None
    program = QueryProgram("//demo:leaf[class()=7 and number()=90]", format=format,
                           resolve=resolve, tags=tags)
    wire = bytes.fromhex("5a00010007")
    format.tag_size = 3  # Compilation snapshots the configured Format.
    assert bytes(program.evaluate(wire)[0].element.value) == b"\x07"
    assert seen == [("demo", "leaf"), ("demo", "leaf")]
    loaded = QueryProgram.load(program.image(), format=FixedFormat(2, 2, "little"),
                               resolve=resolve, tags=tags)
    with pytest.raises(InvalidValueError):
        QueryProgram.load(program.image(), format=FixedFormat(2, 2, "little"), resolve=resolve,
                          tags=QueryTagAdapter(302, tags.class_of, tags.number_of))
    document = Document(wire, FixedFormat(2, 2, "little"))
    assert document.encode() == wire
    execution = loaded.execution()
    execution.evaluate_document(document)
    match, ordinal = execution.next_ordinal()
    assert ordinal == 0 and match.element.tag.data == b"\x5a\0"
    document.close()
    assert bytes(match.element.value) == b"\x07"
    schema = QuerySchema([QueryRule(QueryProgram("//5A00", format=FixedFormat(2, 2, "little")),
                                    QueryProgram("num(.)=7", format=FixedFormat(2, 2, "little")))])
    schema.validate_buffer(wire)


def test_query_resolver_drift_definition_ambiguity_and_callback_errors():
    calls = []
    def changing(namespace, name):
        calls.append(name)
        return b"\x5a" if len(calls) == 1 else b"\x5b"
    with pytest.raises(InvalidValueError):
        QueryProgram("//named", resolve=changing)
    marker = ValueError("resolver exception")
    def throwing(*args):
        raise marker
    with pytest.raises(ValueError) as failure:
        QueryProgram("//named", resolve=throwing)
    assert failure.value is marker
    registry = DefinitionRegistry([Definition(b"\x5a", "leaf")])
    definitions = QueryDefinitionResolver({"a": registry, "b": registry})
    assert definitions("a", "leaf") == b"\x5a"
    with pytest.raises(InvalidArgError):
        definitions("", "leaf")
    p = QueryProgram("count(//a:leaf)", resolve=definitions)
    del registry, definitions
    gc.collect()
    assert p.evaluate(bytes.fromhex("5a00")) == 1
    bad = QueryProgram("class(//5A)", tags=QueryTagAdapter(303, class_of=throwing))
    with pytest.raises(ValueError) as failure:
        bad.evaluate(bytes.fromhex("5a00"))
    assert failure.value is marker
    with pytest.raises(UnsupportedError):
        QueryProgram("number(//5A)", tags=QueryTagAdapter(304, class_of=lambda raw: 1))


def test_query_schema_buffer_document_owned_diagnostics_and_limits():
    context = QueryProgram("//5A")
    schema = QuerySchema([QueryRule(context, QueryProgram("num(.) = 1"), "one")])
    good = bytes.fromhex("70035a0101")
    bad = bytearray.fromhex("70035a0102")
    schema.validate_buffer(good)
    schema.validate_document(Document(good))
    QuerySchema([QueryRule(QueryProgram("//5B"), QueryProgram("1 = 0"))]).validate_buffer(bad)
    with pytest.raises(SchemaError) as caught:
        schema.validate_buffer(bad)
    detail = caught.value.schema
    assert caught.value.rule == 0
    # The Schema part carries only Schema detail; common evidence is the error's own.
    assert sorted(detail) == ["field", "kind", "kind_name", "tag"]
    assert detail["kind_name"] == "assertion"
    assert detail["tag"] == b"\x5a" and caught.value.path == (b"\x70",)
    assert caught.value.location == Location("input", "point", 2, 2) and detail["field"] == "one"
    assert caught.value.expected == "contextual Query assertion true"
    document = Document(bad)
    with pytest.raises(SchemaError) as document_failure:
        schema.validate_document(document)
    assert document_failure.value.location.kind == "unknown"
    document.close()
    bad[:] = b"\0" * len(bad)
    del schema, context
    gc.collect()
    assert document_failure.value.path == (b"\x70",)
    assert detail["tag"] == b"\x5a" and detail["field"] == "one"
    schema = QuerySchema([QueryRule(QueryProgram("//5A"), QueryProgram("1 = 1"))])
    with pytest.raises(LimitError) as limit:
        schema.validate_buffer(good, max_contexts=0)
    assert limit.value.query["limit"] == "schema-contexts"
    assert limit.value.schema is None
    with pytest.raises(LimitError):
        schema.validate_buffer(good, max_work=1)
    with pytest.raises(InvalidValueError):
        QuerySchema([QueryRule(QueryProgram("//5A"), QueryProgram("count(.)"))]).validate_buffer(good)
    reverse = QuerySchema([QueryRule(QueryProgram("//5A[2]"),
                                    QueryProgram("exists(preceding::5A)"))])
    siblings = bytes.fromhex("70065a01015a0102")
    with pytest.raises(UnsupportedError):
        reverse.validate_buffer(siblings)
    reverse.validate_document(Document(siblings))
    empty_root = QueryProgram("value(//70)").execution(max_depth=0)
    empty_root.evaluate_document(Document(b"\x70\0"))
    assert empty_root.result() == b""


def test_query_schema_provider_lifetime_exception_reentry_and_document_guards():
    document = Document(bytes.fromhex("70035a0101"))
    node = document.first.first_child
    actions = []
    def decode(value, metadata):
        assert metadata.element.tag.data == b"\x5a"
        for action in actions:
            with pytest.raises(InvalidStateError):
                action()
        return value[0]
    providers = {"num": QueryProvider(201, decode)}
    assertion = QueryProgram("num(.) = 1", providers=providers)
    schema = QuerySchema([QueryRule(QueryProgram("//5A"), assertion)])
    del assertion, providers
    gc.collect()
    actions.extend([document.close, node.erase, lambda: setattr(node, "value", b"x"),
                    lambda: schema.validate_document(document)])
    schema.validate_document(document)
    assert bytes(node.value) == b"\x01"
    actions.clear()
    schema.validate_buffer(bytes.fromhex("5a0101"))
    sentinel = ValueError("schema provider failure")
    def fail(value, metadata):
        raise sentinel
    failed = QuerySchema([QueryRule(QueryProgram("//5A"),
                                    QueryProgram("num(.) = 1", providers={"num": QueryProvider(202, fail)}))])
    with pytest.raises(ValueError) as caught:
        failed.validate_document(document)
    assert caught.value is sentinel
    document.close()


def test_custom_conversion_provider_lifetime_images_and_backends():
    calls = []
    def decode(value, metadata):
        calls.append((value, metadata))
        return value[0] * 10
    providers = {"num": QueryProvider(101, decode)}
    program = QueryProgram("num(//5A)", providers=providers)
    providers.clear()
    gc.collect()
    assert program.evaluate(bytes.fromhex("5a0103")) == 30
    assert calls[-1][1].offset == 0
    assert calls[-1][1].element.tag.data == b"\x5a"
    loaded = QueryProgram.load(program.image(), providers={"num": QueryProvider(101, decode)})
    assert loaded.evaluate(bytes.fromhex("5a0104")) == 40
    with pytest.raises(InvalidValueError):
        QueryProgram.load(program.image())
    execution = program.execution()
    document = Document(bytes.fromhex("5a0102"))
    execution.evaluate_document(document)
    assert execution.result() == 20


def test_custom_text_provider_has_exact_bounded_result_scratch():
    provider = QueryProvider(102, lambda value, metadata: "a\0b", max_result_bytes=3)
    assert QueryProgram("text(//5A)", providers={"text": provider}).evaluate(b"\x5a\0") == "a\0b"
    short = QueryProvider(102, provider.decode, max_result_bytes=2)
    with pytest.raises(BufferTooShortError) as error:
        QueryProgram("text(//5A)", providers={"text": short}).evaluate(b"\x5a\0")
    assert error.value.codec_detail["reported"] == _native.RESULT_BUFFER_TOO_SHORT
    assert error.value.codec_detail["operation"] == 0


def test_provider_exception_and_execution_reentry_are_preserved():
    execution = None
    def decode(value, metadata):
        execution.reset()
        return 1
    program = QueryProgram("num(//5A)", providers={"num": QueryProvider(103, decode)})
    execution = program.execution()
    reader = TreeReader(b"\x5a\0")
    with pytest.raises(InvalidStateError) as error:
        execution.visit(reader, lambda match: None)
    assert error.value.query["query_kind"] == 12
    execution.reset()
    def failure(value, metadata):
        raise LookupError("provider failed")
    with pytest.raises(LookupError, match="provider failed"):
        QueryProgram("num(//5A)", providers={"num": QueryProvider(104, failure)}).evaluate(b"\x5a\0")


def test_completed_document_edits_preserve_short_selection_and_overlap():
    wire = bytes.fromhex("70065a01015a01025a0103")
    document = Document(wire)
    old_node = document.first.first_child
    execution = QueryProgram("//5A").execution().evaluate_document(document)
    with pytest.raises(BufferTooShortError) as failure:
        execution.edit_document("replace", value=b"\x09", target_capacity=2)
    assert failure.value.applied == 0 and document.encode() == wire
    assert failure.value.query["query_kind_name"] == "storage"
    assert execution.edit_document("replace", value=b"\x09", target_capacity=3) == 3
    with pytest.raises(ValueError, match="no longer valid"):
        old_node.value
    assert document.encode() == bytes.fromhex("70065a01095a01095a0109")
    with pytest.raises(InvalidStateError):
        execution.next()
    execution.reset()
    execution.evaluate_document(document)
    assert execution.edit_document("insert_after", tag=b"\x5b", value=b"\x04") == 3
    assert QueryProgram("count(//5B)").execution().evaluate_document(document).result() == 3
    ancestor = QueryProgram("//70 | //5A").execution().evaluate_document(document)
    assert ancestor.edit_document("remove") == 2
    assert document.encode() == b"\x5b\x01\x04"


def test_invalid_constructed_query_replacement_is_atomic():
    wire = bytes.fromhex("70035a0101")
    document = Document(wire)
    execution = QueryProgram("//70").execution().evaluate_document(document)
    with pytest.raises(TruncatedError) as failure:
        execution.edit_document("replace", value=b"\x5a")
    assert failure.value.applied == 0 and document.encode() == wire
    # The Reader detail of the rejected children survives the edit.
    assert failure.value.query["query_kind_name"] == "reader"
    assert failure.value.location.domain == "input"
    execution.reset()
    execution.evaluate_document(document)
    assert execution.edit_document("replace", value=b"\x5a\x00") == 1


def test_full_language_variables_scalar_and_image_roundtrip():
    program = QueryProgram("count(//5A[@len >= $minimum])", variables={"minimum": int})
    assert program.info["variables"] == (("minimum", 2),)
    assert program.evaluate(WIRE, bindings={"minimum": 1}) == 2
    loaded = QueryProgram.load(program.image(), variables={"minimum": int})
    assert loaded.format() == program.format()
    assert loaded.evaluate(WIRE, bindings={"minimum": 2}) == 0
    with pytest.raises(InvalidValueError) as error:
        QueryProgram.load(program.image()[:-1], variables={"minimum": int})
    assert error.value.query is not None
    assert "instructions" in program.info
    assert program.explain()


def test_typed_bytes_strings_and_scoped_names_are_copied():
    names = {"fixture:leaf": bytes.fromhex("5a")}
    program = QueryProgram("//fixture:leaf[contains(value(), $needle)]",
                           names=names, variables={"needle": bytes})
    names.clear()
    assert [match.offset for match in program.evaluate(WIRE, bindings={"needle": b"\x03"})] == [8]
    assert QueryProgram("text(x'610062')").evaluate(WIRE) == "a\0b"
    assert QueryProgram("value(//5A[1])").evaluate(bytes.fromhex("5a020001")) == b"\0\x01"


def test_stop_pull_resume_and_owned_results_survive_reset():
    execution = QueryProgram("//5A").execution(retained=False)
    reader = TreeReader(WIRE)
    first = execution.next(reader)
    assert first.offset == 2
    assert not execution.info["finished"]
    assert execution.next(reader).offset == 8
    with pytest.raises(StopIteration):
        execution.next(reader)
    assert execution.info["full_validation"]
    execution.reset()
    gc.collect()
    assert bytes(first.element.value) == b"\x01"


def test_incremental_retention_pins_replaced_input_and_propagates_status():
    execution = QueryProgram("(//5A)[last()]").execution()
    reader = TreeReader(WIRE[:8], final_input=False)
    with pytest.raises(NeedMoreDataError):
        execution.visit(reader, lambda match: Visit.CONTINUE)
    reader.set_input(WIRE, final_input=True)
    gc.collect()
    assert execution.next(reader).offset == 8
    with pytest.raises(StopIteration):
        execution.next(reader)


def test_callback_exception_reentry_terminal_failure_and_reset():
    execution = QueryProgram("//5A").execution(retained=False)
    def callback(match):
        execution.reset()
    with pytest.raises(InvalidStateError) as error:
        execution.visit(TreeReader(WIRE), callback)
    assert error.value.query["query_kind"] == 12
    assert execution.info["invalid"]
    execution.reset()
    assert execution.exists(TreeReader(WIRE))
    assert execution.info["full_validation"]


def test_unfinished_result_reports_state_and_reset_recovers():
    from opentlv import TreeEvent, TreeEventKind
    execution = QueryProgram("count(//5A)").execution()
    with pytest.raises(InvalidStateError) as error:
        execution.result()
    assert error.value.query["query_kind"] == 12
    with pytest.raises(InvalidValueError) as malformed:
        execution.feed(TreeEvent(TreeEventKind.END, None, 0))
    assert malformed.value.query["query_kind"] == 5
    with pytest.raises(InvalidStateError) as retried:
        execution.finish()
    assert retried.value.query["query_kind"] == 12
    execution.reset()
    execution.finish()
    assert execution.result() == 0


def test_explicit_short_workspace_candidate_limit_and_early_coverage():
    program = QueryProgram("//5A")
    with pytest.raises(BufferTooShortError):
        program.execution(workspace=bytearray(1))
    execution = program.execution(max_nodes=1)
    with pytest.raises(LimitError) as error:
        execution.visit(TreeReader(WIRE), lambda match: None)
    assert error.value.query["limit"] == "candidates"
    assert execution.info["invalid"]
    execution = program.execution(retained=False)
    broken = TreeReader(bytes.fromhex("5a005002"))
    assert execution.exists(broken, early_return=True)
    assert not execution.info["full_validation"]
    with pytest.raises(Exception) as error:
        execution.exists(broken)
    assert error.value.query["query_kind"] == 7


def test_document_source_locations_support_global_axes_and_edit_invalidation():
    wire = bytearray.fromhex("50005701aa")
    program = QueryProgram("//50/following::57[@offset = 2 and @hlen = 2]")
    with Document(wire, retain_source_locations=True) as document:
        wire[:] = b"\x00" * len(wire)
        selected = document.select(program)
        assert len(selected) == 1
        assert selected[0].value == b"\xaa"
        selected[0].value = b"\xbb"
        with pytest.raises(InvalidValueError):
            document.select(program)
    with Document(bytes.fromhex("50005701aa")) as document:
        with pytest.raises(InvalidValueError):
            document.select(program)


def test_document_reverse_axis_revision_context_and_close_guards():
    document = Document(WIRE)
    execution = QueryProgram("//50[preceding-sibling::5A]").execution()
    execution.evaluate_document(document)
    assert execution.next().tag.data == b"\x50"
    with pytest.raises(StopIteration):
        execution.next()
    execution.reset()
    execution.evaluate_document(document)
    document.insert(b"\x5a", b"x")
    with pytest.raises(InvalidStateError):
        execution.next()
    scalar = QueryProgram("count(//5A)").execution()
    scalar.evaluate_document(document)
    assert scalar.result() == 3
    document.close()
    with pytest.raises(ReferenceError):
        scalar.result()


def test_canonical_feed_source_lifetime_and_exact_external_workspace():
    program = QueryProgram("count(//5A[@offset >= 2 and @hlen = 2])")
    size, alignment = program.workspace_size(max_depth=4, max_nodes=20)
    import ctypes
    storage = bytearray(size + alignment)
    address = ctypes.addressof(ctypes.c_char.from_buffer(storage))
    start = (-address) % alignment
    workspace = memoryview(storage)[start:start + size]
    execution = program.execution(max_depth=4, max_nodes=20, workspace=workspace)
    reader = TreeReader(WIRE)
    while True:
        try:
            event = reader.next_event()
        except StopIteration:
            break
        assert execution.feed(event) is None
    del event, reader
    gc.collect()
    execution.finish()
    assert execution.result() == 2
    with pytest.raises(BufferTooShortError):
        program.execution(max_depth=4, max_nodes=20, workspace=workspace[:-1])


def test_document_select_owns_checked_handles_and_scalar_values():
    document = Document(WIRE)
    assert document.select(QueryProgram("count(//5A)")) == 2
    nodes = document.select(QueryProgram("//5A"))
    assert len({node.identity for node in nodes}) == 2
    assert bytes(nodes[0].value) == b"\x01"


def test_query_schema_deep_diagnostic_retains_omitted_count():
    schema = QuerySchema([QueryRule(QueryProgram("//5A"), QueryProgram("1 = 0"))])
    wire = b"\x5a\x00"
    for level in range(35):
        wire = bytes([0x70 if level == 34 else 0x30, len(wire)]) + wire
    with pytest.raises(SchemaError) as caught:
        schema.validate_buffer(wire)
    assert caught.value.schema["kind_name"] == "assertion"
    assert caught.value.path == (b"\x70",) + (b"\x30",) * 31
    assert caught.value.path_omitted == 3


def test_invalid_successful_provider_output_is_callback_failure():
    program = QueryProgram("num(//5A)", providers={
        "num": QueryProvider(104, lambda value, metadata: "wrong type", max_result_bytes=32)})
    with pytest.raises(CallbackError) as failed:
        program.evaluate(bytes.fromhex("5a0103"))
    assert failed.value.code == _native.RESULT_CALLBACK
    assert failed.value.query["query_kind"] == 13
    assert failed.value.codec_detail["reported"] == 0
