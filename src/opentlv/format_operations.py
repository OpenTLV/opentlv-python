# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Canonical Format operations shared by builtin, fixed and composed formats."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

import _opentlv as _native

from opentlv.error import _from_native
from opentlv.tag import Tag

Value = Union[bytes, bytearray, memoryview]


@dataclass(frozen=True)
class Encoding:
    """Logical framing sizes of one element (`tlv_encoding_t`)."""

    header: int
    value: int
    trailer: int
    total: int


def _call(function, *args):
    try:
        return function(*args)
    except _native.Error as error:
        raise _from_native(error) from None


class FormatOperations:
    """Operations of the C `tlv_format_t` contract, independent of Reader and Writer.

    Failures raise the matching `OpenTLVError` with the Format's own detail:
    `operation` ("decode", "measure" or "encode"), `region`, `offset`,
    `required` and the known tag, length and value offsets. Decode offsets are
    relative to the input; measure and encode offsets to the would-be output.
    """

    __slots__ = ()

    def _native_format(self):
        raise NotImplementedError

    @property
    def can_read(self) -> bool:
        """Whether this Format can decode (`tlv_format_can_read()`)."""
        return _call(_native.format_capabilities, self._native_format())[0]

    @property
    def can_write(self) -> bool:
        """Whether this Format can measure and encode (`tlv_format_can_write()`)."""
        return _call(_native.format_capabilities, self._native_format())[1]

    def decode(self, data: Value):
        """Decode one complete element at the start of `data` (`tlv_format_decode()`).

        Returns `Decoded`; ``len(result.encoded)`` is the consumed byte count
        and trailing bytes are not read. Empty input raises `EndError`. Bytes
        are retained without copying; other buffers are snapshotted.
        """
        from opentlv.cursor import _decoded
        data = data if isinstance(data, bytes) else bytes(memoryview(data))
        return _decoded(data, _call(_native.format_decode, self._native_format(), data))

    def measure(self, tag: Union[Tag, bytes], value: Value) -> Encoding:
        """Measure the header, value and trailer of one element (`tlv_format_measure()`)."""
        tag_bytes = tag.data if isinstance(tag, Tag) else tag
        return Encoding(*_call(_native.format_measure, self._native_format(), tag_bytes, value))

    def encode(self, tag: Union[Tag, bytes], value: Value) -> bytes:
        """Encode one element into new bytes of its measured size (`tlv_format_encode()`)."""
        tag_bytes = tag.data if isinstance(tag, Tag) else tag
        return _call(_native.format_encode, self._native_format(), tag_bytes, value)
