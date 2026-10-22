# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Formats composed from Core field encodings or a packed header."""

from __future__ import annotations

from typing import Iterable, Union
import weakref

import _opentlv as _native

from opentlv.field import (ConstructedBit, EscapedLength, FixedIdentifier, FixedLength,
                           PackedField, VariableIdentifier, VariableLength, _big_endian,
                           _unsigned)
from opentlv.format_operations import FormatOperations, _call
from opentlv.tag import Tag

Identifier = Union[FixedIdentifier, VariableIdentifier]
Length = Union[FixedLength, VariableLength, EscapedLength]

_ELEMENT_ORDERS = {"tlv": False, "ltv": True}
_LENGTH_SCOPES = {"value": False, "tag_and_value": True}
# Native specification kinds, matching compose.c.
_FIELDS, _PACKED = 0, 1


class ComposedFormat(FormatOperations):
    """A Format composed through the generic C composition mechanisms.

    Create one with `Format.fields()`, `Format.variable()`, `Format.escaped()`
    or `Format.packed()`, then use it anywhere a builtin Format is accepted:
    `Reader`, `TreeReader`, `Writer`, `TreeWriter`, `Document`, `Query` and
    schemas. The native descriptor owns its configuration and identifier
    tables. Equal configurations return the same object while it is alive, so
    a Query compiled with one is compatible with a Document parsed with another.
    """

    __slots__ = ("_owner", "_description", "__weakref__")

    def __init__(self) -> None:
        raise TypeError("compose with Format.fields(), Format.variable(), Format.escaped() "
                        "or Format.packed()")

    def _native_format(self):
        return self._owner

    def __repr__(self) -> str:
        return self._description


# Native owners are shared by equal specifications; see ComposedFormat.
_formats: "weakref.WeakValueDictionary[tuple, ComposedFormat]" = weakref.WeakValueDictionary()


def _compose(specification: tuple, description: str) -> ComposedFormat:
    format = _formats.get(specification)
    if format is None:
        format = object.__new__(ComposedFormat)
        format._owner = _call(_native.format_compose, specification)
        format._description = description
        _formats[specification] = format
    return format


def _choice(name: str, value: str, choices: dict) -> bool:
    if value not in choices:
        raise ValueError(f"{name} must be one of {', '.join(map(repr, choices))}")
    return choices[value]


def _require(name: str, value, types) -> None:
    if not isinstance(value, types):
        expected = " or ".join(kind.__name__ for kind in types)
        raise TypeError(f"{name} must be {expected}")


def _describe(name: str, **arguments) -> str:
    shown = ", ".join(f"{key}={value!r}" for key, value in arguments.items()
                      if value is not None and value != ())
    return f"Format.{name}({shown})"


def _fields(name, tag, length, element_order, length_scope, tag_only, constructed):
    _require("tag", tag, (FixedIdentifier, VariableIdentifier))
    _require("length", length, (FixedLength, VariableLength, EscapedLength))
    if constructed is not None:
        _require("constructed", constructed, (ConstructedBit,))
    tags = tuple(bytes(item.data if isinstance(item, Tag) else memoryview(item))
                 for item in tag_only)
    specification = (_FIELDS, tag._native(), length._native(),
                     _choice("element_order", element_order, _ELEMENT_ORDERS),
                     _choice("length_scope", length_scope, _LENGTH_SCOPES), tags,
                     None if constructed is None else constructed._native())
    return _compose(specification, _describe(
        name, tag=tag, length=length, element_order=element_order, length_scope=length_scope,
        tag_only=tuple(Tag(item) for item in tags), constructed=constructed))


def fields(tag: Identifier, length: Length, *, element_order: str = "tlv",
           length_scope: str = "value", tag_only: Iterable[Union[Tag, bytes]] = (),
           constructed: ConstructedBit | None = None) -> ComposedFormat:
    """Compose a definite Format from one identifier and one length encoding.

    `element_order` is "tlv" or "ltv"; `length_scope` is "value" or
    "tag_and_value", where the count also covers the identifier's wire bytes.
    Identifiers in `tag_only` omit Length and Value and require an empty Value;
    they need TLV order and value scope. `constructed` classifies nesting;
    without it every Value is opaque.

    The C composition follows from the encodings: fixed identifier and fixed
    length use `tlv_fixed_format_init()` or, with `tag_only`,
    `tlv_tagged_binary_format_init()`; variable identifier and variable length
    use `tlv_variable_format_init()` or `tlv_variable_fields_init()` with
    `tlv_tagged_fields_format_init()`; a fixed identifier with an escaped
    length uses `tlv_escaped_format_init()`. Other pairs compose the field
    primitives through `tlv_fields_format_init()` or
    `tlv_tagged_fields_format_init()`. Invalid configuration raises
    `InvalidArgError`.

    >>> format = Format.fields(FixedIdentifier(1), FixedLength(2), element_order="ltv")
    >>> format.encode(b"\\x07", b"\\xaa")
    b'\\x00\\x01\\x07\\xaa'
    """
    return _fields("fields", tag, length, element_order, length_scope, tag_only, constructed)


def variable(tag: VariableIdentifier, length: VariableLength, *, element_order: str = "tlv",
             length_scope: str = "value", tag_only: Iterable[Union[Tag, bytes]] = (),
             constructed: ConstructedBit | None = None) -> ComposedFormat:
    """Compose a variable-width identifier and count Format, as `tlv_variable_format_t`.

    Options are those of `Format.fields()`. EMV element framing, for example:

    >>> format = Format.variable(
    ...     VariableIdentifier(0x1F, 0x1F, 0x80, 0x7F, 2,
    ...                        IdentifierPolicy(b"\\x00", reject_zero_first_payload=True)),
    ...     VariableLength(0x80, 0x7F, policy=LengthPolicy(max_long_octets=2, max_value=65535)),
    ...     constructed=ConstructedBit(0, 0x20, 0x20))
    """
    _require("tag", tag, (VariableIdentifier,))
    _require("length", length, (VariableLength,))
    return _fields("variable", tag, length, element_order, length_scope, tag_only, constructed)


def escaped(tag: FixedIdentifier, length: EscapedLength, *, element_order: str = "tlv",
            length_scope: str = "value", tag_only: Iterable[Union[Tag, bytes]] = (),
            constructed: ConstructedBit | None = None) -> ComposedFormat:
    """Compose fixed identifiers with escape-prefixed counts, as `tlv_escaped_format_t`.

    Options are those of `Format.fields()`. A one-byte identifier with an
    inline count below 0xFF, or 0xFF and a two-byte big-endian count:

    >>> format = Format.escaped(FixedIdentifier(1), EscapedLength(0xFF, 2))
    """
    _require("tag", tag, (FixedIdentifier,))
    _require("length", length, (EscapedLength,))
    return _fields("escaped", tag, length, element_order, length_scope, tag_only, constructed)


def packed(*, header_size: int, tag: PackedField, length: PackedField, byte_order: str = "big",
           tag_size: int | None = None, length_scope: str = "value",
           constructed: ConstructedBit | None = None) -> ComposedFormat:
    """Compose a definite packed Tag/Length header, as `tlv_packed_layout_t`.

    Both fields share one `header_size`-byte header integer in `byte_order`;
    their bits must not overlap and unused bits are zeroed on encode. Decoded
    Tags are the field value as `tag_size` big-endian bytes, by default the
    fewest bytes holding `tag.bit_width` bits. The binding owns the canonical
    identifier table Core borrows, so tag fields are limited to 16 bits.
    Configuration is checked with `tlv_packed_layout_validate()`.

    LLDP TLV framing, a 7-bit type above a 9-bit length:

    >>> format = Format.packed(header_size=2, tag=PackedField(9, 7), length=PackedField(0, 9))
    """
    _require("tag", tag, (PackedField,))
    _require("length", length, (PackedField,))
    if constructed is not None:
        _require("constructed", constructed, (ConstructedBit,))
    if tag_size is None:
        tag_size = max(1, (_unsigned("tag.bit_width", tag.bit_width) + 7) // 8)
    specification = (_PACKED, _unsigned("header_size", header_size), tag._native(),
                     length._native(), _big_endian(byte_order), _unsigned("tag_size", tag_size),
                     _choice("length_scope", length_scope, _LENGTH_SCOPES),
                     None if constructed is None else constructed._native())
    return _compose(specification, _describe(
        "packed", header_size=header_size, tag=tag, length=length, byte_order=byte_order,
        tag_size=tag_size, length_scope=length_scope, constructed=constructed))
