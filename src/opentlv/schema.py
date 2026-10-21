# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Length schemas and structural schemas for validating TLV data."""

from __future__ import annotations
from opentlv.location import Location
from opentlv.diagnostic import Severity, SchemaIssue, SchemaDefinitionKind

import enum
import struct
from dataclasses import dataclass
from typing import Iterable, Optional, Union

import _opentlv as _native

from opentlv.error import _from_native
from opentlv.format import Format, _resolve_format
from opentlv.tag import Tag

UNRESTRICTED = 2**(8 * struct.calcsize("P")) - 1
"""Sentinel for an unrestricted upper bound, matching the C library's `SIZE_MAX`."""


class LengthRule:
    """Length rule for one tag of a `LengthSchema`.

    Bounds are inclusive; equal bounds specify an exact length.
    """

    __slots__ = ("tag", "min_length", "max_length", "flags", "length_multiple")

    def __init__(self, tag: Union[Tag, bytes], min_length: int = 0,
                 max_length: int = UNRESTRICTED, *, flags: int = 0,
                 length_multiple: int = 0) -> None:
        self.tag = tag if isinstance(tag, Tag) else Tag(tag)
        self.min_length = min_length
        self.max_length = max_length
        self.flags = flags
        self.length_multiple = length_multiple

    def _to_native(self):
        return (self.tag.data, self.min_length, self.max_length, self.flags, self.length_multiple)

    @staticmethod
    def exact(tag: Union[Tag, bytes], length: int) -> "LengthRule":
        """Creates a rule permitting exactly `length` bytes."""
        return LengthRule(tag, length, length)

    def __repr__(self) -> str:
        return f"LengthRule({self.tag!r}, {self.min_length}, {self.max_length})"


class LengthSchema:
    """A table of per-tag value-length rules.

    Lookup and validation delegate to C, including endpoint-only lengths
    (flags=1) and length_multiple constraints. Earlier rules win for a repeated tag.

    >>> tag = Tag(b"\\x01")
    >>> schema = LengthSchema([LengthRule(tag, 2, 4)])
    >>> schema.validate_length(tag, 3)
    >>> schema.validate_length(tag, 5)
    Traceback (most recent call last):
        ...
    opentlv.error.SchemaError: schema constraint violated
    """

    __slots__ = ("_rules",)

    def __init__(self, rules: Iterable[LengthRule] = ()) -> None:
        self._rules = tuple(rules)

    def __len__(self) -> int:
        return len(self._rules)

    def find(self, tag: Union[Tag, bytes]) -> Optional[LengthRule]:
        """Returns the rule for `tag`, or `None` if the schema does not know it."""
        tag_bytes = tag.data if isinstance(tag, Tag) else bytes(tag)
        try:
            index = _native.length_schema(tuple(rule._to_native() for rule in self._rules),
                                          tag_bytes, None)
        except _native.Error as error:
            raise _from_native(error) from None
        return None if index is None else self._rules[index]

    def validate_length(self, tag: Union[Tag, bytes], length: int) -> None:
        """Checks that a value of `length` bytes is permitted for `tag`.

        Raises `SchemaError` if the schema has no rule for `tag`, or
        `SchemaError` if `length` is out of the rule's bounds.
        Raises `InvalidSchemaError` for reversed bounds.
        """
        tag_bytes = tag.data if isinstance(tag, Tag) else bytes(tag)
        try:
            _native.length_schema(tuple(rule._to_native() for rule in self._rules),
                                  tag_bytes, length)
        except _native.Error as error:
            raise _from_native(error) from None


class Kind(enum.IntEnum):
    """Expected form of a value described by a `StructureRule`."""

    ANY = 0
    """The element may be primitive or constructed."""

    PRIMITIVE = 1
    """The element must be primitive."""

    CONSTRUCTED = 2
    """The element must be constructed."""


class StructureRule:
    """Structural rule for one tag within a single parent scope of a `StructureSchema`.

    A new rule is optional (0 to unrestricted occurrences), accepts any
    length and any `Kind`, and leaves its children unrestricted; pass
    keyword arguments to refine it.

    >>> rule = StructureRule(Tag(b"\\x84"), min_length=5, max_length=16,
    ...                       min_occurs=1, max_occurs=1, kind=Kind.PRIMITIVE)
    """

    __slots__ = ("tag", "min_length", "max_length", "min_occurs", "max_occurs", "kind", "children", "flags", "length_multiple", "group", "name")

    def __init__(self, tag: Union[Tag, bytes], *, min_length: int = 0,
                 max_length: int = UNRESTRICTED, min_occurs: int = 0,
                 max_occurs: int = UNRESTRICTED, kind: Kind = Kind.ANY,
                 children: Optional["StructureSchema"] = None, flags: int = 0,
                 length_multiple: int = 0, group: int = 0, name: str | None = None) -> None:
        self.tag = tag if isinstance(tag, Tag) else Tag(tag)
        self.min_length = min_length
        self.max_length = max_length
        self.min_occurs = min_occurs
        self.max_occurs = max_occurs
        self.kind = Kind.CONSTRUCTED if children is not None else kind
        self.children = children
        self.flags = flags
        self.length_multiple = length_multiple
        self.group = group
        self.name = name

    def _to_native(self):
        children = self.children._to_native() if self.children is not None else None
        return (self.tag.data, self.min_length, self.max_length, self.min_occurs,
                self.max_occurs, int(self.kind), children, self.flags, self.length_multiple, self.group, self.name)

    def __repr__(self) -> str:
        return (f"StructureRule({self.tag!r}, min_length={self.min_length}, "
                f"max_length={self.max_length}, min_occurs={self.min_occurs}, "
                f"max_occurs={self.max_occurs}, kind={self.kind!r})")


class SchemaOrder(enum.IntEnum):
    """Ordering of matched elements, enforced by C."""
    ANY = 0
    SEQUENCE = 1


class UnknownPolicy(enum.IntEnum):
    """Unknown-tag policy for report-based validation."""
    BY_SCHEMA = 0
    ALLOW = 1
    REJECT = 2


@dataclass(frozen=True)
class SchemaBounds:
    """Inclusive expected bounds and observed value reported by C."""
    minimum: int
    maximum: int
    actual: int


@dataclass(frozen=True)
class SchemaDiagnostic:
    """Owned C diagnostic; path retains outermost scopes, tag is separate.

    path_omitted counts innermost scopes beyond the native path capacity.
    """
    code: int
    severity: Severity
    kind: SchemaIssue
    kind_name: str
    tag: Tag
    path: tuple[Tag, ...]
    offset: int | None
    field: str | None
    is_group: bool
    occurrences: SchemaBounds | None
    length: SchemaBounds | None
    form: tuple[Kind, bool] | None
    length_multiple: int
    length_flags: int
    path_omitted: int = 0
    location: Location = Location()
    definition_kind: SchemaDefinitionKind = SchemaDefinitionKind.UNKNOWN
    definition_index: int = 0


def _diagnostic_from_native(item) -> SchemaDiagnostic:
    """Copy the canonical native Schema diagnostic into its public projection."""
    (code, severity, kind, name, tag, path, offset, field, group,
     occurs, length, form, multiple, flags, path_omitted, location, definition_kind, definition_index) = item
    return SchemaDiagnostic(code, Severity(severity), SchemaIssue(kind), name, Tag(tag),
        tuple(Tag(t) for t in path), offset, field, bool(group),
        SchemaBounds(*occurs) if occurs is not None else None,
        SchemaBounds(*length) if length is not None else None,
        (Kind(form[0]), bool(form[1])) if form is not None else None,
        multiple, flags, path_omitted, Location(**location), SchemaDefinitionKind(definition_kind), definition_index)


@dataclass(frozen=True)
class SchemaDiagnosticReport:
    """Total violations and the bounded prefix of detailed diagnostics."""
    total_count: int
    diagnostics: tuple[SchemaDiagnostic, ...]


class StructureGroup:
    """Occurrence bounds across every rule assigned to one nonzero group ID."""
    __slots__ = ("id", "min_occurs", "max_occurs", "name")

    def __init__(self, id: int, min_occurs=0, max_occurs=UNRESTRICTED, *, name: str | None = None):
        self.id = id
        self.name = name
        self.min_occurs = min_occurs
        self.max_occurs = max_occurs


def _schema_format(format):
    from opentlv.fixed_format import FixedFormat
    format = _resolve_format(format)
    if isinstance(format, FixedFormat):
        return (format.tag_size, format.length_size, format.big_endian)
    return format


class StructureSchema:
    """A structural schema: per-tag length, kind, occurrence and membership
    rules for one parent scope, with optional nested schemas for children.

    `validate()` runs the C library's validator; values are never decoded.
    Tags must be unique among `rules`; a duplicate is reported by
    `validate()` as a `SchemaError`. Unknown tags are rejected unless
    `allow_unknown` is `True`.

    >>> tag = Tag(b"\\x01")
    >>> schema = StructureSchema([StructureRule(tag, min_occurs=1, max_occurs=1)])
    >>> schema.validate(bytes([0x01, 0x00]))
    >>> schema.validate(b"")
    Traceback (most recent call last):
        ...
    opentlv.error.SchemaError: schema constraint violated
    """

    __slots__ = ("rules", "allow_unknown", "order", "groups")

    def __init__(self, rules: Iterable[StructureRule] = (), allow_unknown: bool = False, *,
                 order: SchemaOrder = SchemaOrder.ANY, groups: Iterable[StructureGroup] = ()) -> None:
        self.rules = list(rules)
        self.allow_unknown = allow_unknown
        self.order = order
        self.groups = tuple(groups)

    def _to_native(self):
        return (self.allow_unknown, [rule._to_native() for rule in self.rules], int(self.order),
                tuple((group.id, group.min_occurs, group.max_occurs, group.name) for group in self.groups))

    def validate(self, data, format: Format | None = None, max_depth: int = 32,
                 max_elements: int = 100_000) -> None:
        """Validates framing, nesting, lengths, occurrence counts and child
        membership of `data` against this schema.

        Which tags are constructed is decided by `format`: BER, CER and DER
        nest by their constructed bit, while Fixed formats have no nesting, so every value is opaque. `max_depth` and
        `max_elements` bound traversal the same way `Reader` does not need
        to, since validation may recurse into nested elements.

        Raises `SchemaError` with `kind="missing"` for an absent required field,
        `SchemaError` for other rule violations including length constraints,
        `InvalidSchemaError` for an invalid definition, or a reading error
        such as `LimitError`.
        """
        format = _schema_format(format)
        try:
            _native.structure_validate(data, format, self._to_native(), max_depth, max_elements)
        except _native.Error as native_error:
            raise _from_native(native_error) from None

    def validate_diagnostics(self, data, format=None, *, capacity=64,
                             unknown=UnknownPolicy.BY_SCHEMA,
                             max_depth=32, max_elements=100_000) -> SchemaDiagnosticReport:
        """Collect expected/actual details from C, with owned tags and field names.

        Zero capacity counts only. Wire/configuration errors raise instead of
        returning a partial report. No traversal or validation occurs in Python.
        """
        try:
            count, items = _native.structure_validate(data, _schema_format(format),
                self._to_native(), max_depth, max_elements, capacity, int(unknown))
        except _native.Error as error:
            raise _from_native(error) from None
        return SchemaDiagnosticReport(count, tuple(_diagnostic_from_native(item) for item in items))

    def __len__(self) -> int:
        return len(self.rules)

    def __repr__(self) -> str:
        return f"StructureSchema(rules={self.rules!r}, allow_unknown={self.allow_unknown})"
