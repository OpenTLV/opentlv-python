# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Ownership and source projections of canonical C Reader cursors."""
from dataclasses import dataclass, field
from enum import IntEnum
import _opentlv as _native
from opentlv.element import Element
from opentlv.error import _from_native
from opentlv.fixed_format import FixedFormat
from opentlv.format import _resolve_format
from opentlv.tag import Tag


class Visit(IntEnum):
    """Visitor control; None also means CONTINUE in Python callbacks."""
    CONTINUE = 0
    STOP = 1
    ERROR = 2


@dataclass(frozen=True)
class Layout:
    """Source-relative (offset, size) ranges; absent fields are None."""
    header: tuple[int, int] | None
    tag: tuple[int, int] | None
    length: tuple[int, int] | None
    value: tuple[int, int] | None
    trailer: tuple[int, int] | None


@dataclass(frozen=True)
class Decoded:
    """Semantic Element and immutable original encoding with its Layout."""
    element: Element
    encoded: memoryview
    layout: Layout
    _source: object = field(default=None, repr=False, compare=False)

    def preserve_into(self, output, *, offset=0, element=None) -> int:
        """Copy original bytes through C after checking unchanged semantic content.

        Requires source metadata produced by a Reader. Insufficient capacity
        leaves output unchanged and reports the required size in the exception.
        """
        if self._source is None:
            raise ValueError("preservation requires a Reader-produced source")
        element = self.element if element is None else element
        try:
            return _native.source_preserve(self._source, output, offset,
                                           element.tag.data, element.value)
        except _native.Error as error:
            raise _from_native(error) from None

    def preserve(self, *, element=None) -> bytes:
        """Return an exact encoded copy, rejecting semantic changes through C."""
        output = bytearray(len(self.encoded))
        self.preserve_into(output, element=element)
        return bytes(output)


@dataclass(frozen=True)
class TreeItem:
    """Complete preorder item; views retain their backing bytes independently."""
    decoded: Decoded
    depth: int
    offset: int
    constructed: bool

    @property
    def element(self) -> Element:
        """Semantic content of this item."""
        return self.decoded.element


class TreeEventKind(IntEnum):
    """Canonical structural operations shared by Reader and Writer."""
    BEGIN = 0
    ELEMENT = 1
    END = 2


@dataclass(frozen=True)
class TreeEvent:
    """Structural event; END has no borrowed payload. Skipped means omitted content."""
    kind: TreeEventKind
    item: TreeItem | None
    depth: int
    offset: int = 0
    skipped: bool = False


class _Cursor:
    __slots__ = ("_capsule", "_data", "_format")

    def __init__(self, data, format=None, *, final_input=True, nested=False,
                 frame_capacity=64, max_depth=64, max_elements=65536):
        self._data = data if isinstance(data, bytes) else bytes(memoryview(data))
        self._format = _resolve_format(format)
        fixed = isinstance(self._format, FixedFormat)
        try:
            self._capsule = _native.cursor_create(
                self._data, -1 if fixed else self._format, final_input, nested,
                frame_capacity, max_depth, max_elements,
                self._format.tag_size if fixed else 0,
                self._format.length_size if fixed else 0,
                self._format.big_endian if fixed else True)
        except _native.Error as error:
            raise _from_native(error) from None

    @property
    def format(self):
        """Format selected when the native cursor was created."""
        return self._format

    @property
    def consumed(self) -> int:
        """Parser-discardable prefix bytes in the current window."""
        return _native.cursor_status(self._capsule)[0]

    @property
    def position(self) -> int:
        """Current-window consumed byte count."""
        return self.consumed

    @property
    def offset(self) -> int:
        """Absolute frontier, including discarded windows."""
        return _native.cursor_status(self._capsule)[1]

    @property
    def at_end(self) -> bool:
        """True only at final exhaustion, never when more input is needed."""
        return bool(_native.cursor_status(self._capsule)[2])

    def set_input(self, data, *, discard=0, final_input=False) -> None:
        """Replace the window, retaining undiscarded bytes unchanged.

        Bytes are retained; other buffers are copied. Old views keep old storage
        alive. On failure the current window and traversal state are unchanged.
        """
        data = data if isinstance(data, bytes) else bytes(memoryview(data))
        try:
            _native.cursor_input(self._capsule, data, discard, final_input)
        except _native.Error as error:
            raise _from_native(error) from None
        self._data = data

    def _pull(self) -> TreeItem:
        try:
            result = _native.cursor_next(self._capsule)
        except _native.Error as error:
            raise _from_native(error) from None
        if result is None:
            raise StopIteration
        return self._decode_item(result)

    def _decode_item(self, result):
        tag, start, size, ranges, depth, offset, constructed, source = result
        encoded = memoryview(self._data)[start:start + size]
        layout = Layout(*ranges)

        def field(location):
            if location is None:
                return encoded[:0]
            begin, length = location
            return encoded[begin:begin + length]

        element = Element(Tag(tag), field(layout.value), field(layout.length))
        return TreeItem(Decoded(element, encoded, layout, source), depth, offset, bool(constructed))

    def _visit(self, callback, nested):
        def adapter(tag, value, depth, offset):
            element = Element(Tag(tag), memoryview(value))
            return callback(element, depth, offset) if nested else callback(element)
        try:
            _native.cursor_visit(self._capsule, adapter)
        except _native.Error as error:
            raise _from_native(error) from None


class TreeReader(_Cursor):
    """C preorder traversal with bounded native frames and resumable input.

    Parents are published only when their complete encoding is available.
    Mutable inputs are snapshotted. No Python tree traversal is implemented.
    """
    __slots__ = ()

    def __init__(self, data, format=None, *, final_input=True, frame_capacity=64,
                 max_depth=64, max_elements=65536):
        super().__init__(data, format, final_input=final_input, nested=True,
                         frame_capacity=frame_capacity, max_depth=max_depth,
                         max_elements=max_elements)

    def __iter__(self):
        return self

    def __next__(self) -> TreeItem:
        """Yield complete items; NEED_MORE_DATA and other failures preserve state."""
        return self._pull()

    def next_event(self) -> TreeEvent:
        """Pull through C; do not mix with node iteration for a balanced stream."""
        try:
            result = _native.cursor_event(self._capsule)
        except _native.Error as error:
            raise _from_native(error) from None
        if result is None:
            raise StopIteration
        kind, item, depth, offset, skipped = result
        return TreeEvent(TreeEventKind(kind), self._decode_item(item) if item is not None else None,
                         depth, offset, bool(skipped))

    def skip_subtree(self) -> None:
        """Skip pending descendants, also after a descent limit failure."""
        try:
            _native.cursor_skip(self._capsule)
        except _native.Error as error:
            raise _from_native(error) from None

    def visit(self, callback) -> None:
        """Visit remaining items via C, calling callback(element, depth, offset).

        None/Visit.CONTINUE continues; STOP returns, ERROR raises VisitorError.
        Callbacks receive owned snapshots and may retain them. Python exceptions
        propagate after C returns. Cursor access from the callback is prohibited.
        STOP leaves the current item published for continuation or subtree skip.
        """
        self._visit(callback, True)
