# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Runtime-configurable fixed-width TLV format."""

from __future__ import annotations


class FixedFormat:
    """A runtime-configurable fixed-width TLV format: independent tag width,
    length width (1 to 8 bytes) and length byte order.

    Equivalent to the C `tlv_fixed_format_t` and `tlv_fixed_format_init()`. A
    one-byte tag and a one-byte big-endian length is `FixedFormat(1, 1)`.

    >>> format = FixedFormat(2, 1)
    >>> writer = Writer(format)
    >>> writer.write(Tag(b"\\x01\\x02"), b"\\xaa\\xbb\\xcc")
    >>> writer.bytes()
    b'\\x01\\x02\\x03\\xaa\\xbb\\xcc'
    >>> [(e.tag.data, bytes(e.value)) for e in Reader(writer.bytes(), format)]
    [(b'\\x01\\x02', b'\\xaa\\xbb\\xcc')]
    """

    __slots__ = ("tag_size", "length_size", "big_endian")

    def __init__(self, tag_size: int, length_size: int, byte_order: str = "big") -> None:
        if tag_size < 1:
            raise ValueError("tag_size must be at least 1")
        if not 1 <= length_size <= 8:
            raise ValueError("length_size must be between 1 and 8")
        if byte_order not in ("big", "little"):
            raise ValueError("byte_order must be 'big' or 'little'")
        self.tag_size = tag_size
        self.length_size = length_size
        self.big_endian = byte_order == "big"

    def __repr__(self) -> str:
        order = "big" if self.big_endian else "little"
        return (f"FixedFormat(tag_size={self.tag_size}, length_size={self.length_size}, "
                f"byte_order={order!r})")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FixedFormat):
            return NotImplemented
        return (self.tag_size, self.length_size, self.big_endian) == (
            other.tag_size, other.length_size, other.big_endian)

    def __hash__(self) -> int:
        return hash((self.tag_size, self.length_size, self.big_endian))
