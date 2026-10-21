# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Sequential output into caller-owned storage or an optional growable buffer."""

from __future__ import annotations

from typing import Union

import _opentlv as _native

from opentlv.element import Element
from opentlv.error import BufferTooShortError, _from_native
from opentlv.fixed_format import FixedFormat
from opentlv.format import Format, _resolve_format
from opentlv.tag import Tag

Value = Union[bytes, bytearray, memoryview]
AnyFormat = Union[Format, FixedFormat]

_INITIAL_CAPACITY = 64


class Writer:
    """A sequential writer over borrowed or growable output storage.

    With ``buffer=storage``, borrows fixed-capacity caller-owned storage.
    Without a buffer, owns a ``bytearray`` that grows as needed. Both modes
    keep the position unchanged on failure and delegate encoding to Format.

    >>> writer = Writer()
    >>> writer.write(Tag(b"\\x01"), b"\\xaa\\xbb")
    >>> writer.write(Tag(b"\\x02"), b"")
    >>> writer.bytes()
    b'\\x01\\x02\\xaa\\xbb\\x02\\x00'
    """

    __slots__ = ("_buffer", "_pos", "_format", "_owned")

    def __init__(self, format: AnyFormat | None = None, *,
                 buffer: bytearray | memoryview | None = None) -> None:
        """Borrow a writable contiguous buffer, or allocate a growable one.

        Borrowed storage never grows. A failed write leaves position unchanged;
        encoder failures may modify bytes after that position. Input tag/value
        bytes must not overlap the destination element. Python wrapper objects
        may allocate, but the borrowed mode never allocates output storage.
        """
        self._owned = buffer is None
        if buffer is None:
            self._buffer = bytearray(_INITIAL_CAPACITY)
        else:
            view = memoryview(buffer)
            if view.readonly or not view.c_contiguous:
                raise ValueError("buffer must be writable and contiguous")
            self._buffer = view.cast("B")
        self._pos = 0
        self._format = _resolve_format(format)

    @property
    def format(self) -> AnyFormat:
        """The wire format this writer encodes."""
        return self._format

    @property
    def position(self) -> int:
        """The number of bytes written so far."""
        return self._pos

    def _write_native(self, offset: int, tag_bytes: bytes, value: Value) -> int:
        if isinstance(self._format, FixedFormat):
            return _native.write_fixed(self._buffer, offset, tag_bytes, value,
                                       self._format.tag_size, self._format.length_size,
                                       self._format.big_endian)
        return _native.write(self._buffer, offset, tag_bytes, value, self._format)

    def write(self, tag: Union[Tag, bytes], value: Value) -> None:
        """Appends one element with `tag` and `value`."""
        tag_bytes = tag.data if isinstance(tag, Tag) else tag
        try:
            written = self._write_native(self._pos, tag_bytes, value)
        except _native.Error as native_error:
            error = _from_native(native_error)
            if not (self._owned and isinstance(error, BufferTooShortError)
                    and error.required is not None):
                raise error from None
            self._grow(self._pos + error.required)
            try:
                written = self._write_native(self._pos, tag_bytes, value)
            except _native.Error as retry_error:
                raise _from_native(retry_error) from None
        self._pos += written

    def write_element(self, element: Element) -> None:
        """Appends a decoded `Element`, for example one produced by a `Reader`."""
        self.write(element.tag, element.value)

    def copy_encoded(self, encoded: Value) -> None:
        """Copy raw bytes without validation or conversion; overlap is supported.

        A capacity failure preserves position and output bytes. Owned storage
        grows as needed; borrowed storage never grows.
        """
        try:
            written = _native.copy_encoded(self._buffer, self._pos, encoded)
        except _native.Error as native_error:
            error = _from_native(native_error)
            if not (self._owned and isinstance(error, BufferTooShortError)
                    and error.required is not None):
                raise error from None
            self._grow(self._pos + error.required)
            try:
                written = _native.copy_encoded(self._buffer, self._pos, encoded)
            except _native.Error as retry_error:
                raise _from_native(retry_error) from None
        self._pos += written

    def _grow(self, min_capacity: int) -> None:
        capacity = len(self._buffer)
        while capacity < min_capacity:
            capacity *= 2
        self._buffer.extend(bytes(capacity - len(self._buffer)))

    def preserve(self, decoded, *, element=None) -> None:
        """Append an exact source copy after C checks unchanged semantic content.

        The writer's destination Format does not reinterpret preserved bytes.
        Failure leaves position unchanged; borrowed storage never grows.
        """
        try:
            written = decoded.preserve_into(self._buffer, offset=self._pos, element=element)
        except BufferTooShortError as error:
            if not self._owned or error.required is None:
                raise
            self._grow(self._pos + error.required)
            written = decoded.preserve_into(self._buffer, offset=self._pos, element=element)
        self._pos += written

    def bytes(self) -> bytes:
        """Returns the bytes written so far, as a new `bytes` object."""
        return bytes(self._buffer[:self._pos])

    @property
    def capacity(self) -> int:
        """Current destination capacity in bytes."""
        return len(self._buffer)

    @property
    def remaining(self) -> int:
        """Destination bytes available before resizing or capacity failure."""
        return self.capacity - self._pos

    def view(self) -> memoryview:
        """Borrow written bytes without copying; release before growing owned storage."""
        return memoryview(self._buffer)[:self._pos].toreadonly()

    def __len__(self) -> int:
        return self._pos

    def __repr__(self) -> str:
        return f"Writer(format={self._format!r}, position={self._pos})"


def encoded_size(tag: Union[Tag, bytes], value_length: int,
                 format: AnyFormat | None = None) -> int:
    """Returns the encoded size of an element with `tag` and a value of
    `value_length` bytes in `format`, without writing anything.

    >>> encoded_size(Tag(b"\\x01"), 3)
    5
    """
    format = _resolve_format(format)
    tag_bytes = tag.data if isinstance(tag, Tag) else tag
    try:
        if isinstance(format, FixedFormat):
            return _native.encoded_size_fixed(tag_bytes, value_length, format.tag_size,
                                              format.length_size, format.big_endian)
        return _native.encoded_size(tag_bytes, value_length, format)
    except _native.Error as native_error:
        raise _from_native(native_error) from None


def element_encoded_size(element: Element, format: AnyFormat | None = None) -> int:
    """Measure exact Header + Value + Trailer storage using readable content.

    Does not allocate an output buffer. The caller chooses storage, then writes
    with ``Writer(format, buffer=storage).write_element(element)``.
    """
    format = _resolve_format(format)
    try:
        if isinstance(format, FixedFormat):
            return _native.element_encoded_size_fixed(
                element.tag.data, element.value, format.tag_size,
                format.length_size, format.big_endian)
        return _native.element_encoded_size(element.tag.data, element.value, format)
    except _native.Error as native_error:
        raise _from_native(native_error) from None
