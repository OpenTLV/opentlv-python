# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Bounded owned buffers around the canonical C Tree Writer."""
import _opentlv as _native
from opentlv.error import _from_native
from opentlv.fixed_format import FixedFormat
from opentlv.format import _resolve_format
from opentlv.tag import Tag


class TreeWriter:
    """Own output, scratch and frame storage; all encoding is performed by C.

    Capacity never grows implicitly. Open tags remain alive until end(). bytes()
    returns only the finalized prefix; finish() rejects unclosed parents.
    """
    __slots__ = ("_capsule",)

    def __init__(self, capacity, format=None, *, scratch_capacity=None,
                 frame_capacity=64, max_depth=64, max_elements=65536):
        format = _resolve_format(format)
        fixed = isinstance(format, FixedFormat)
        if scratch_capacity is None:
            scratch_capacity = capacity
        try:
            self._capsule = _native.tree_writer_create(
                -1 if fixed else format, capacity, scratch_capacity, frame_capacity,
                max_depth, max_elements, format.tag_size if fixed else 0,
                format.length_size if fixed else 0, format.big_endian if fixed else True)
        except _native.Error as error:
            raise _from_native(error) from None

    def _action(self, operation, *args):
        try:
            return _native.tree_writer_action(self._capsule, operation, *args)
        except _native.Error as error:
            raise _from_native(error) from None

    def begin(self, tag: Tag | bytes) -> None:
        """Open a constructed item, retaining immutable tag bytes until successful end."""
        self._action(0, tag.data if isinstance(tag, Tag) else bytes(memoryview(tag)))

    def write(self, element) -> None:
        """Append a semantic Element through C; no tag/value input is retained."""
        self._action(1, element.tag.data, bytes(element.value))

    def set_tag_capacity(self, capacity=None) -> None:
        """Configure bounded owned Tag copying; None restores retained-tag mode.

        Requires no open parents. Zero capacity rejects nonempty identifiers.
        """
        if capacity is not None and capacity < 0:
            raise ValueError("nonnegative Tag capacity required")
        try:
            _native.tree_writer_tags(self._capsule, -1 if capacity is None else capacity)
        except _native.Error as error:
            raise _from_native(error) from None

    def write_event(self, event) -> None:
        """Consume through C; retain BEGIN tag ownership until successful END."""
        element = event.item.element if event.item is not None else None
        try:
            _native.tree_writer_event(self._capsule, int(event.kind), event.depth,
                                      element.tag.data if element else b"",
                                      bytes(element.value) if element else b"", event.skipped)
        except _native.Error as error:
            raise _from_native(error) from None

    def end(self) -> None:
        """Close the innermost parent; failure preserves state and output."""
        self._action(2)

    def bytes(self) -> bytes:
        """Copy finalized output; open roots are excluded."""
        return self._action(4)

    def finish(self) -> bytes:
        """Require all parents closed and copy finalized output; does not seal the writer."""
        return self._action(3)

    @classmethod
    def measure(cls, items, capacity, format=None, *, scratch_capacity=None,
                frame_capacity=64, max_depth=64, max_elements=65536) -> bytes:
        """Measure and stage preorder ``(Element, depth, constructed)`` records.

        Returns the staged encoding; its length is the exact measured size.
        C owns parent closure and validates preorder depth and classification.
        The source is consumed even on failure. Workspace exhaustion exceptions
        expose required_data and required_scratch lower bounds; retry with a
        fresh source. Those fields are zero for other native failures.
        """
        writer = cls(capacity, format, scratch_capacity=scratch_capacity,
                     frame_capacity=frame_capacity, max_depth=max_depth,
                     max_elements=max_elements)
        records = ((element.tag.data, bytes(element.value), depth, constructed)
                   for element, depth, constructed in items)
        try:
            return _native.tree_writer_measure(writer._capsule, records)
        except _native.Error as native_error:
            error = _from_native(native_error)
            error.required_data = getattr(native_error, "required_data", 0)
            error.required_scratch = getattr(native_error, "required_scratch", 0)
            raise error from None


    @classmethod
    def measure_events(cls, events, capacity, format=None, **options) -> bytes:
        """Stage a balanced event stream through C; retry requires a fresh source.

        Owned records keep BEGIN Tags alive. Workspace requirements are reported
        as for measure(); NEED_MORE_DATA aborts this one-shot operation.
        """
        writer = cls(capacity, format, **options)
        def records():
            for event in events:
                element = event.item.element if event.item is not None else None
                yield (int(event.kind), event.depth, element.tag.data if element else b"",
                       bytes(element.value) if element else b"", event.skipped)
        try:
            return _native.tree_writer_measure(writer._capsule, records(), True)
        except _native.Error as native_error:
            error = _from_native(native_error)
            error.required_data = getattr(native_error, "required_data", 0)
            error.required_scratch = getattr(native_error, "required_scratch", 0)
            raise error from None
