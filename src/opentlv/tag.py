# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""The TLV tag type."""

from __future__ import annotations


class Tag:
    """A TLV tag: an arbitrary sequence of raw bytes in wire order.

    A tag owns its bytes and has no length limit; whether the bytes form a
    valid tag is decided by the wire format or standard it is used with.
    Tags compare equal, and order, by their bytes, which is exactly what
    Python's own ``bytes`` comparison already does (unsigned, lexicographic,
    shorter-is-smaller-on-a-shared-prefix), so `Tag` delegates to it instead
    of calling into the native library.
    """

    __slots__ = ("_data",)

    def __init__(self, data: bytes) -> None:
        self._data = bytes(data)

    @property
    def data(self) -> bytes:
        """The tag's raw bytes, in wire order."""
        return self._data

    def __bytes__(self) -> bytes:
        return self._data

    def __len__(self) -> int:
        return len(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Tag):
            return self._data == other._data
        return NotImplemented

    def __lt__(self, other: "Tag") -> bool:
        if isinstance(other, Tag):
            return self._data < other._data
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._data)

    def __str__(self) -> str:
        """Formats the tag as uppercase hexadecimal, for example ``"9F02"``."""
        return self._data.hex().upper()

    def __repr__(self) -> str:
        return f"Tag({self})"
