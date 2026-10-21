# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""The decoded TLV element type."""

from __future__ import annotations

from opentlv.tag import Tag


class Element:
    """A decoded TLV element: a tag, raw length bytes and a value.

    `length` and `value` are ``memoryview`` objects onto storage retained by the
    Reader. Bytes input is borrowed; other inputs are snapshotted. Views keep
    their storage alive independently of the Reader. Equality compares tag and
    value, ignoring raw length encoding.
    """

    __slots__ = ("_tag", "_length", "_value")

    def __init__(self, tag: Tag, value: memoryview, length: memoryview = memoryview(b"")) -> None:
        self._tag = tag
        self._value = value
        self._length = length

    @property
    def tag(self) -> Tag:
        """The element's tag."""
        return self._tag

    @property
    def length(self) -> memoryview:
        """Original encoded length bytes, borrowed from the input buffer."""
        return self._length

    @property
    def value(self) -> memoryview:
        """The element's value, as a zero-copy view onto the input buffer."""
        return self._value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Element):
            return self._tag == other._tag and self._value == other._value
        return NotImplemented

    def __repr__(self) -> str:
        return f"Element(tag={self._tag!r}, value={bytes(self._value)!r})"
