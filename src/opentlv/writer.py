# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Sequential output into caller-owned storage or an optional growable buffer."""

from __future__ import annotations

from typing import Union

import _opentlv as _native

from opentlv.element import Element
from opentlv.error import BufferTooShortError, _from_native
from opentlv.composed_format import ComposedFormat
from opentlv.fixed_format import FixedFormat
from opentlv.format import Format, _format_specification, _resolve_format
from opentlv.tag import Tag

Value = Union[bytes, bytearray, memoryview]
AnyFormat = Union[Format, FixedFormat, ComposedFormat]

_INITIAL_CAPACITY = 64


class Writer:
    """A sequential writer session over borrowed or growable output storage.

    With ``buffer=storage``, borrows fixed-capacity caller-owned storage.
    Without a buffer, owns a ``bytearray`` that grows as needed. Both modes
    append through one native C Writer, which keeps the position unchanged
    on failure and delegates encoding to Format.

    >>> writer = Writer()
    >>> writer.write(Tag(b"\\x01"), b"\\xaa\\xbb")
    >>> writer.write(Tag(b"\\x02"), b"")
    >>> writer.bytes()
    b'\\x01\\x02\\xaa\\xbb\\x02\\x00'
    """

    __slots__ = ("_buffer", "_capsule", "_format", "_owned")

    def __init__(self, format: AnyFormat | None = None, *,
                 buffer: bytearray | memoryview | None = None) -> None:
        """Borrow a writable contiguous buffer, or allocate a growable one.

        Borrowed storage never grows and cannot be resized while the Writer
        exists. A failed write leaves position unchanged; encoder failures may
        modify bytes after that position. Input tag/value bytes must not overlap
        the destination element. Python wrapper objects may allocate, but the
        borrowed mode never allocates output storage. A Format that cannot
        write is rejected here.
        """
        self._owned = buffer is None
        if buffer is None:
            self._buffer = bytearray(_INITIAL_CAPACITY)
        else:
            view = memoryview(buffer)
            if view.readonly or not view.c_contiguous:
                raise ValueError("buffer must be writable and contiguous")
            self._buffer = view.cast("B")
        self._format = _resolve_format(format)
        try:
            self._capsule = _native.writer_create(self._buffer,
                                                  _format_specification(self._format))
        except _native.Error as native_error:
            raise _from_native(native_error) from None

    @property
    def format(self) -> AnyFormat:
        """The wire format this writer encodes."""
        return self._format

    @property
    def position(self) -> int:
        """The number of bytes written so far."""
        return _native.writer_status(self._capsule)[0]

    def _append(self, operation, *args) -> None:
        try:
            operation(self._capsule, *args)
            return
        except _native.Error as native_error:
            error = _from_native(native_error)
        if not (self._owned and isinstance(error, BufferTooShortError)
                and error.required is not None):
            raise error
        self._grow(self.position + error.required)
        try:
            operation(self._capsule, *args)
        except _native.Error as retry_error:
            raise _from_native(retry_error) from None

    def write(self, tag: Union[Tag, bytes], value: Value) -> None:
        """Appends one element with `tag` and `value`."""
        self._append(_native.writer_write, tag.data if isinstance(tag, Tag) else tag, value)

    def write_element(self, element: Element) -> None:
        """Appends a decoded `Element`, for example one produced by a `Reader`."""
        self.write(element.tag, element.value)

    def copy_encoded(self, encoded: Value) -> None:
        """Copy raw bytes without validation or conversion; overlap is supported.

        A capacity failure preserves position and output bytes. Owned storage
        grows as needed; borrowed storage never grows.
        """
        self._append(_native.writer_copy, encoded)

    def _grow(self, min_capacity: int) -> None:
        capacity = len(self._buffer)
        while capacity < min_capacity:
            capacity *= 2
        buffer = bytearray(capacity)
        try:
            _native.writer_rebind(self._capsule, buffer)
        except _native.Error as native_error:
            raise _from_native(native_error) from None
        self._buffer = buffer

    def preserve(self, decoded, *, element=None) -> None:
        """Append an exact source copy after C checks unchanged semantic content.

        Requires source metadata produced by a Reader. The writer's destination
        Format does not reinterpret preserved bytes. Failure leaves position
        unchanged; borrowed storage never grows.
        """
        if decoded._source is None:
            raise ValueError("preservation requires a Reader-produced source")
        element = decoded.element if element is None else element
        self._append(_native.writer_preserve, decoded._source, element.tag.data, element.value)

    def bytes(self) -> bytes:
        """Returns the bytes written so far, as a new `bytes` object."""
        return bytes(self._buffer[:self.position])

    @property
    def capacity(self) -> int:
        """Current destination capacity in bytes."""
        return len(self._buffer)

    @property
    def remaining(self) -> int:
        """Destination bytes available before resizing or capacity failure."""
        return _native.writer_status(self._capsule)[1]

    def view(self) -> memoryview:
        """Borrow written bytes without copying.

        Owned growth moves output to new storage; an earlier view keeps the
        bytes written before growth.
        """
        return memoryview(self._buffer)[:self.position].toreadonly()

    def __len__(self) -> int:
        return self.position

    def __repr__(self) -> str:
        return f"Writer(format={self._format!r}, position={self.position})"


def write_element(buffer: bytearray | memoryview, element: Element,
                  format: AnyFormat | None = None, *, offset: int = 0) -> int:
    """Encode one `Element` at `offset` in caller storage and return its size.

    Uses no Writer session and never grows `buffer`. A capacity failure
    reports `required`, the exact size from ``element_encoded_size()``, and
    leaves `buffer` unchanged; encoder failures may modify bytes at or after
    `offset`. Element bytes must not overlap the destination.

    >>> storage = bytearray(4)
    >>> write_element(storage, Element(Tag(b"\\x01"), memoryview(b"\\xaa")), offset=1)
    3
    >>> storage
    bytearray(b'\\x00\\x01\\x01\\xaa')
    """
    try:
        return _native.write(buffer, offset, element.tag.data, element.value,
                             _format_specification(format))
    except _native.Error as native_error:
        raise _from_native(native_error) from None


def encoded_size(tag: Union[Tag, bytes], value_length: int,
                 format: AnyFormat | None = None) -> int:
    """Returns the encoded size of an element with `tag` and a value of
    `value_length` bytes in `format`, without writing anything.

    >>> encoded_size(Tag(b"\\x01"), 3)
    5
    """
    tag_bytes = tag.data if isinstance(tag, Tag) else tag
    try:
        return _native.encoded_size(tag_bytes, value_length, _format_specification(format))
    except _native.Error as native_error:
        raise _from_native(native_error) from None


def element_encoded_size(element: Element, format: AnyFormat | None = None) -> int:
    """Measure exact Header + Value + Trailer storage using readable content.

    Does not allocate an output buffer. The caller chooses storage, then writes
    with ``write_element(storage, element, format)`` or
    ``Writer(format, buffer=storage).write_element(element)``.
    """
    try:
        return _native.element_encoded_size(element.tag.data, element.value,
                                            _format_specification(format))
    except _native.Error as native_error:
        raise _from_native(native_error) from None
