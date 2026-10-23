# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Sequential Reader over the canonical C cursor."""
import _opentlv as _native
from opentlv.cursor import Decoded, _Cursor, _decoded
from opentlv.element import Element
from opentlv.error import EndError, NeedMoreDataError, OpenTLVError, _from_native
from opentlv.format import _format_specification
from opentlv.tag import Tag


class Reader(_Cursor):
    """Iterate Elements using the C Reader cursor.

    Bytes are retained without copying; other buffers are snapshotted. Views
    retain storage after Reader deletion or input replacement. final_input=False
    enables incremental input. NeedMoreDataError permits set_input() and retry.
    Other errors stop convenience iteration; read_source() permits explicit retry.
    """
    __slots__ = ("_failed",)

    def __init__(self, data, format=None, *, final_input=True):
        super().__init__(data, format, final_input=final_input)
        self._failed = False

    def read_source(self) -> Decoded:
        """Pull content and Layout in one decode, or raise a diagnostic/StopIteration."""
        return self._pull().decoded

    def read_element(self) -> Element:
        """Pull the next Element without source metadata, or raise StopIteration.

        Skips the Layout and source that iteration and read_source() build, so
        Element.length is empty and the result cannot be preserved. The value
        is a view of retained input, as for iteration.
        """
        try:
            result = _native.cursor_read(self._capsule)
        except _native.Error as error:
            raise _from_native(error) from None
        if result is None:
            raise StopIteration
        tag, start, size = result
        return Element(Tag(tag), memoryview(self._data)[start:start + size])

    def __iter__(self):
        return self

    def visit(self, callback) -> None:
        """C Visitor processing; callback(element) returns Visit or None.

        Callback values are owned snapshots. STOP consumes the current element;
        subsequent visits resume without replay. Callback exceptions propagate.
        """
        self._visit(callback, False)

    def __next__(self):
        if self._failed:
            raise StopIteration
        try:
            return self.read_source().element
        except NeedMoreDataError:
            raise
        except OpenTLVError:
            self._failed = True
            raise


def _snapshot(data) -> bytes:
    return data if isinstance(data, bytes) else bytes(memoryview(data))


def read(data, format=None) -> Decoded:
    """Read one complete Element and Layout through C; trailing bytes are unread.

    Returns Decoded; len(result.encoded) is the consumed byte count.
    Empty input raises EndError rather than iterator StopIteration.
    """
    data = _snapshot(data)
    try:
        result = _native.read_source(data, _format_specification(format))
    except _native.Error as error:
        raise _from_native(error) from None
    if result is None:
        raise EndError(_native.RESULT_END)
    return _decoded(data, result)


def read_element(data, format=None) -> tuple[Element, int]:
    """Read one Element without source metadata; trailing bytes are unread.

    Returns the Element and the consumed byte count. Element.length is empty.
    Bytes are retained without copying; other buffers are snapshotted. Empty
    input raises EndError.
    """
    data = _snapshot(data)
    try:
        result = _native.read(data, _format_specification(format))
    except _native.Error as error:
        raise _from_native(error) from None
    if result is None:
        raise EndError(_native.RESULT_END)
    tag, start, size, consumed = result
    return Element(Tag(tag), memoryview(data)[start:start + size]), consumed
