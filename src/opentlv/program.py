# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Immutable full-language C Query programs and independent bounded executions."""
from dataclasses import dataclass
from types import MappingProxyType
import _opentlv as _native
from opentlv.cursor import TreeReader, Visit
from opentlv.element import Element
from opentlv.diagnostic import QueryErrorKind
from opentlv.error import _from_native, EndError, InvalidStateError
from opentlv.format import _resolve_format, _format_specification
from opentlv.fixed_format import FixedFormat
from opentlv.tag import Tag


def _call(function, *args):
    try:
        return function(*args)
    except _native.Error as error:
        raise _from_native(error) from None


@dataclass(frozen=True)
class QueryProvider:
    """One closed conversion provider with a stable nonzero uint32 capability ID.

    ``decode(value, metadata)`` receives copied Value bytes and optional
    owned ``QueryMatch`` metadata. Return int for num/bcd/date or str for
    text. String results are copied into explicitly bounded native scratch.
    Callback exceptions propagate; callback work and Python allocations lie
    outside the C engine's allocation and work contracts.
    """
    id: int
    decode: object
    max_result_bytes: int = 0

    def __post_init__(self):
        if type(self.id) is not int or not 0 < self.id <= 0xffffffff:
            raise ValueError("provider ID must be nonzero uint32")
        if not callable(self.decode):
            raise TypeError("provider decoder must be callable")
        if type(self.max_result_bytes) is not int or self.max_result_bytes < 0:
            raise ValueError("nonnegative result capacity required")


@dataclass(frozen=True)
class QueryTagAdapter:
    """Explicit semantic Tag decomposition; callbacks receive copied raw bytes.

    The nonzero uint32 ID identifies image compatibility. Each optional
    callback returns a signed int64; omitted capabilities fail in the C compiler.
    """
    id: int
    class_of: object = None
    number_of: object = None

    def __post_init__(self):
        if type(self.id) is not int or not 0 < self.id <= 0xffffffff:
            raise ValueError("tag adapter ID must be nonzero uint32")
        if any(value is not None and not callable(value) for value in (self.class_of, self.number_of)):
            raise TypeError("Tag decomposition callbacks must be callable or None")


def query_emv_resolve(namespace, name):
    """Resolve canonical EMV symbols through the native base dictionary."""
    return _call(_native.query_emv_resolve, namespace, name)


class QueryDefinitionResolver:
    """Owned named Definition registries resolved by the canonical C adapter."""
    def __init__(self, scopes):
        from opentlv.definition import DefinitionRegistry
        records = []
        for namespace, registry in scopes.items():
            if not isinstance(namespace, str) or "\0" in namespace:
                raise ValueError("NUL-free namespace required")
            if not isinstance(registry, DefinitionRegistry):
                raise TypeError("DefinitionRegistry required")
            records.append((namespace, tuple((item.tag.data, item.name) for item in registry.definitions)))
        self._scopes = tuple(records)

    def __call__(self, namespace, name):
        """Resolve one spelling; native ambiguity and unknown-tag errors propagate."""
        return _call(_native.query_definition_resolve, self._scopes, namespace, name)


@dataclass(frozen=True)
class QueryMatch:
    """Owned event snapshot; copied bytes remain valid after reset/input replacement."""
    element: Element
    depth: int
    offset: int
    constructed: bool


def _match(raw):
    kind, tag, value, depth, offset = raw
    return QueryMatch(Element(Tag(tag), memoryview(value)), depth, offset, kind == 0)


class QueryProgram:
    """Full compiled language, independent of the V1 path Query matcher.

    C owns syntax, types, optimizer and evaluation. Owning Python storage and
    copied results allocate; the C compiler/VM remain allocation-free. Names
    map scoped spellings to raw Tag bytes and are copied during compilation.
    Builtin Format, generic NUM/BCD/TEXT and ASN.1 tag/DATE capabilities are
    explicit through ``format``. Internal images are version-limited.
    """
    __slots__ = ("_capsule", "_format", "_declarations", "_names", "_options")

    def __init__(self, text, *, format=None, variables=None, names=None, **options):
        if not isinstance(text, str):
            raise TypeError("Query text must be str")
        self._initialize(text.encode("utf-8"), format, variables, names, options, False)

    def _initialize(self, data, format, variables, names, options, image):
        self._format = _resolve_format(format)
        if isinstance(self._format, FixedFormat):
            self._format = FixedFormat(self._format.tag_size, self._format.length_size,
                                       "big" if self._format.big_endian else "little")
        kinds = {int: 2, bytes: 3, str: 4}
        self._declarations = {name: kinds[kind] for name, kind in (variables or {}).items()}
        if any(not isinstance(name, str) or "\0" in name for name in self._declarations):
            raise ValueError("variable names must be NUL-free str")
        self._names = {name: bytes(tag.data if isinstance(tag, Tag) else tag)
                       for name, tag in (names or {}).items()}
        allowed = {"max_text", "max_tokens", "max_nesting", "max_states", "max_pattern",
                   "max_resolved_tag", "optimize", "providers", "tags", "resolve"}
        if options.keys() - allowed:
            raise TypeError(f"unknown compile options: {options.keys() - allowed}")
        self._options = dict(options)
        if "tags" in self._options:
            tags = self._options["tags"]
            if not isinstance(tags, QueryTagAdapter):
                raise TypeError("QueryTagAdapter required")
            self._options["tags"] = (tags.id, tags.class_of, tags.number_of)
        if "resolve" in self._options and not callable(self._options["resolve"]):
            raise TypeError("resolve(namespace, name) must be callable")
        if "resolve" in self._options and names:
            raise ValueError("use either names or resolve")
        if "providers" in self._options:
            selectors = {"num": 0, "bcd": 1, "text": 2, "date": 3}
            providers = self._options["providers"]
            if any(name not in selectors or not isinstance(provider, QueryProvider)
                   for name, provider in providers.items()):
                raise TypeError("providers map num/bcd/text/date to QueryProvider")
            self._options["providers"] = {
                selectors[name]: (provider.id, provider.max_result_bytes,
                                  lambda value, metadata, decode=provider.decode:
                                  decode(value, None if metadata is None else _match(metadata)))
                for name, provider in providers.items()}
        self._capsule = _call(_native.program_create, data, _format_specification(self._format),
                              self._declarations, self._names, self._options, image)

    @classmethod
    def load(cls, image, *, format=None, variables=None, names=None, **options):
        """Validate and own a copy of a same-release image with original compile options."""
        result = cls.__new__(cls)
        result._initialize(bytes(image), format, variables, names, options, True)
        return result

    @property
    def info(self):
        """Immutable whole-expression requirements and referenced variable types."""
        info = _call(_native.program_info, self._capsule)
        info["variables"] = tuple(info["variables"])
        return MappingProxyType(info)

    def format(self):
        """Canonical language spelling from C."""
        return _call(_native.program_render, self._capsule, 0)

    def explain(self):
        """Implementation-specific C plan details."""
        return _call(_native.program_render, self._capsule, 1)

    def image(self):
        """Copy release-specific native-layout bytes; no persistent compatibility promise."""
        return _call(_native.program_render, self._capsule, 2)

    def execution(self, *, max_depth=64, max_nodes=1024, max_work=10000000,
                  retained=True, workspace=None):
        """Create separate S0/S1 or retained S0-S2/D state with explicit resource bounds.

        ``workspace`` pins a contiguous writable aligned caller buffer; short or
        misaligned buffers fail through C. No backend fallback occurs.
        """
        return QueryExecution(self, max_depth, max_nodes, max_work, retained, workspace)

    def workspace_size(self, *, max_depth=64, max_nodes=1024, retained=True):
        """Return exact native (bytes, alignment) for an explicit caller workspace."""
        return _call(_native.execution_size, self._capsule, max_depth, max_nodes, retained)

    def evaluate(self, data, *, bindings=None, **limits):
        """Evaluate complete input, returning owned scalar or ordered owned event snapshots."""
        execution = self.execution(**limits)
        for name, value in (bindings or {}).items():
            execution.bind(name, value)
        reader = TreeReader(data, self._format, max_depth=execution._limits[0],
                            frame_capacity=execution._limits[0], max_elements=execution._limits[1])
        matches = []
        execution.visit(reader, matches.append)
        return matches if self.info["result_kind"] == 0 else execution.result()


@dataclass(frozen=True)
class QueryRule:
    """Select contexts and require a boolean assertion relative to each one."""
    context: QueryProgram
    assertion: QueryProgram
    name: str = ""

    def __post_init__(self):
        if not isinstance(self.context, QueryProgram) or not isinstance(self.assertion, QueryProgram):
            raise TypeError("compiled Query programs required")
        if not isinstance(self.name, str) or "\0" in self.name:
            raise ValueError("NUL-free rule name required")


class QuerySchema:
    """Owning contextual Schema composition over the canonical C validator.

    Programs and providers remain alive while the Schema owns its rules.
    Rules must have compatible native environments. An empty
    context selection succeeds; rules execute in order with explicit bounds.
    """
    def __init__(self, rules, *, format=None):
        self._busy = False
        self.rules = tuple(rules)
        if any(not isinstance(rule, QueryRule) for rule in self.rules):
            raise TypeError("QueryRule entries required")
        if any(rule.context._capsule is None or rule.assertion._capsule is None for rule in self.rules):
            raise ReferenceError("Query program has been closed")
        self._native_rules = tuple((rule.context._capsule, rule.assertion._capsule, rule.name)
                                   for rule in self.rules)
        self._format = _resolve_format(format if format is not None else
                                       self.rules[0].context._format if self.rules else None)

    def _validate(self, input, *, max_depth=64, max_nodes=1024, max_work=10000000,
                  max_contexts=None, value_capacity=None):
        if self._busy:
            error = InvalidStateError(_native.RESULT_INVALID_STATE)
            error.query = {"query_kind": QueryErrorKind.STATE}
            raise error
        self._busy = True
        try:
            _call(_native.query_schema, self._native_rules, input, _format_specification(self._format),
                  max_depth, max_nodes, max_work, max_nodes if max_contexts is None else max_contexts,
                  -1 if value_capacity is None else value_capacity)
        finally:
            self._busy = False

    def validate_buffer(self, input, **limits):
        """Validate complete immutable input; D-only rules fail before traversal."""
        self._validate(bytes(input), **limits)

    def validate_document(self, document, **limits):
        """Validate the immutable Document revision, including D rules."""
        if document._capsule is None:
            raise ReferenceError("Query Document has been closed")
        document._query_active += 1
        try:
            self._validate(document._capsule, **limits)
        finally:
            document._query_active -= 1


class QueryExecution:
    """Independent continuation; pins program, typed bindings and every input window.

    STOP and NEED_MORE_DATA preserve continuation. Exceptions propagate only
    after returning through C; a visitor error invalidates state until reset.
    Tree callback/pull results and scalars are owned copies. Document pulls
    return checked Nodes and reject edits or destruction before native access.
    """
    __slots__ = ("_program", "_capsule", "_limits", "_retained", "_workspace", "_document")

    def __init__(self, program, depth, nodes, work, retained, workspace):
        self._program = program
        self._limits = (depth, nodes, work)
        self._retained = retained
        self._workspace = workspace
        self._document = None
        self.reset()

    def _check(self):
        if self._document is not None and self._document._capsule is None:
            raise ReferenceError("Query Document has been closed")

    def reset(self):
        """Discard continuation, borrowed windows, bindings and Document snapshot."""
        if hasattr(self, "_capsule"):
            _call(_native.execution_info, self._capsule)  # Reject callback reentry.
        self._capsule = _call(_native.execution_create, self._program._capsule,
                              *self._limits, self._retained, self._workspace)
        self._document = None

    def bind(self, name, value):
        """Bind an integer, bytes or UTF-8 string before input; no interpolation."""
        self._check()
        if not isinstance(name, str) or "\0" in name:
            raise ValueError("binding names must be NUL-free str")
        kind = {int: 2, bytes: 3, str: 4}.get(type(value))
        if kind is None:
            raise TypeError("binding must be int, bytes or str")
        _call(_native.execution_bind, self._capsule, name, kind,
              value.encode("utf-8") if kind == 4 else value)
        return self

    def context(self, ordinal):
        """Set a relative traversal context before consuming input."""
        self._check()
        _call(_native.execution_control, self._capsule, 0, ordinal)
        return self

    def pruning(self, enabled=True):
        """Explicitly permit proven pruning; skipped content has partial coverage."""
        self._check()
        _call(_native.execution_control, self._capsule, 1, int(enabled))
        return self

    @property
    def info(self):
        """Counters and full/partial structural-validation coverage."""
        self._check()
        return MappingProxyType(_call(_native.execution_info, self._capsule))

    def visit(self, reader, callback):
        """Visit owned snapshots; return Visit.CONTINUE/STOP/ERROR or None."""
        self._check()
        if not isinstance(reader, TreeReader):
            raise TypeError("TreeReader required")
        _call(_native.execution_visit, self._capsule, reader._capsule,
              lambda raw: callback(_match(raw)), 0)

    def feed(self, event):
        """Feed a complete canonical TreeEvent, pinning its bytes and original Source.

        Immediate S0/S1 selection returns an owned QueryMatch; retained execution
        publishes only after finish(). Failed structural feeds invalidate state.
        """
        self._check()
        item = event.item
        raw = _call(_native.execution_feed, self._capsule, int(event.kind),
                    item.element.tag.data if item else b"",
                    bytes(item.element.value) if item else b"", event.depth, event.offset,
                    item.decoded._source if item else None, event.skipped)
        return None if raw is None else _match(raw)

    def finish(self):
        """Require balanced final events and finalize retained evaluation."""
        self._check()
        _call(_native.execution_finish, self._capsule)

    def exists(self, reader, *, early_return=False):
        """Drain input by default; early success requires inspecting partial coverage."""
        self._check()
        if not isinstance(reader, TreeReader):
            raise TypeError("TreeReader required")
        return _call(_native.execution_visit, self._capsule, reader._capsule,
                     None, 2 if early_return else 1)

    def evaluate_document(self, document, *, context=None, value_capacity=None):
        """Finalize against an immutable Document revision with explicit Value storage."""
        self._check()
        if document._capsule is None:
            raise ReferenceError("Query Document has been closed")
        capacity = document.encoded_size if value_capacity is None else value_capacity
        document._query_active += 1
        try:
            _call(_native.execution_document, self._capsule, document._capsule,
                  document._node_ptr(context), capacity)
        finally:
            document._query_active -= 1
        self._document = document
        return self

    def result(self):
        """Return an owned finalized scalar; node results use next()."""
        self._check()
        return _call(_native.execution_result, self._capsule)

    def edit_document(self, kind, *, tag=b"", value=b"", target_capacity=None):
        """Edit a finalized selection: remove, replace or insert_after.

        C resolves ancestor overlap and prevalidates framing before mutation.
        Return the applied count; errors expose ``applied`` for partial commits.
        Short target capacity preserves the selection for a retry. Edits
        invalidate prior Document results and checked erased Nodes.
        """
        self._check()
        if self._document is None:
            raise ValueError("evaluate_document must precede editing")
        self._document._assert_mutable()
        kinds = {"remove": 0, "replace": 1, "insert_after": 2}
        if kind not in kinds:
            raise ValueError("remove, replace or insert_after required")
        capacity = self._limits[1] if target_capacity is None else target_capacity
        tag_data = bytes(tag.data if isinstance(tag, Tag) else tag)
        value_data = bytes(value)
        previous_generation = self._document._query_generation
        previous_lifetimes = self._document._lifetimes
        replacement_lifetimes = type(previous_lifetimes)()
        self._document._query_generation += 1
        self._document._lifetimes = replacement_lifetimes
        self._document._query_active += 1
        applied = None
        try:
            applied = _call(_native.execution_edit, self._capsule, kinds[kind],
                            tag_data, value_data, capacity)
            return applied
        except Exception as error:
            applied = getattr(error, "applied", None)
            raise
        finally:
            self._document._query_active -= 1
            # Invalidate before entering C, including the signal-delivery window
            # after a native mutation. Restore handles only with a known zero count.
            if applied == 0:
                self._document._query_generation = previous_generation
                self._document._lifetimes = previous_lifetimes

    def next(self, reader=None):
        """Pull one match; TLV_END becomes StopIteration, not NEED_MORE_DATA."""
        self._check()
        try:
            if reader is not None:
                if self._program.info["result_kind"] != 0:
                    raise TypeError("node Query required")
                selected = []
                self.visit(reader, lambda match: (selected.append(match), Visit.STOP)[1])
                if not selected:
                    raise StopIteration
                return selected[0]
            raw = _call(_native.execution_next, self._capsule)
            return self._document._wrap(raw) if self._document is not None else _match(raw)
        except EndError:
            raise StopIteration from None

    def __iter__(self):
        return self

    def next_ordinal(self):
        """Pull (owned QueryMatch, preorder ordinal) from a completed retained result.

        The ordinal identifies a context in this traversal/revision, independently
        of source offsets and Document node identities. Exhaustion raises StopIteration.
        """
        self._check()
        if self._document is not None:
            self._document._query_active += 1
        try:
            raw, ordinal = _call(_native.execution_next_ordinal, self._capsule)
            return _match(raw), ordinal
        except EndError:
            raise StopIteration from None
        finally:
            if self._document is not None:
                self._document._query_active -= 1

    def __next__(self):
        return self.next()
