# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Canonical C Query parsing and resumable matching."""
import _opentlv as _native
from opentlv.cursor import TreeReader
from opentlv.element import Element
from opentlv.error import _from_native
from opentlv.tag import Tag


class Query:
    """An owned parsed path, such as '30/04'; grammar and errors come from C."""
    __slots__ = ("_capsule",)

    def __init__(self, text: str):
        if not isinstance(text, str):
            raise TypeError("query must be text")
        try:
            self._capsule = _native.query_create(text)
        except _native.Error as error:
            raise _from_native(error) from None

    @property
    def steps(self) -> tuple[Tag, ...]:
        """Owned tags returned by the C query-step API."""
        return tuple(Tag(tag) for tag in _native.query_steps(self._capsule))

    def matcher(self):
        """Create independent matching state for a new traversal."""
        return QueryMatcher(self)

    def visit_buffer(self, data, callback, format=None, **limits):
        """Visit matches in complete input using a C Tree Reader and C Query matcher."""
        self.matcher().visit(TreeReader(data, format, **limits), callback)


class QueryMatcher:
    """Owns a copy of its query; retains C matching state across STOP and input replacement."""
    __slots__ = ("_capsule",)

    def __init__(self, query: Query):
        if not isinstance(query, Query):
            raise TypeError("Query required")
        try:
            self._capsule = _native.query_create(query._capsule)
        except _native.Error as error:
            raise _from_native(error) from None

    def matches(self, tag: Tag | bytes, depth: int) -> bool:
        """Feed every preorder item in order, including nonmatching ancestors."""
        return _native.query_matches(self._capsule, tag.data if isinstance(tag, Tag) else tag, depth)

    def reset(self):
        """Reset matching state for a fresh traversal; Reader state is independent."""
        self._rebind(None)

    def rebind(self, query: Query):
        """Own an equivalent Query copy while preserving suspended matching state."""
        if not isinstance(query, Query):
            raise TypeError("Query required")
        self._rebind(query._capsule)

    def _rebind(self, query):
        try:
            _native.query_rebind(self._capsule, query)
        except _native.Error as error:
            raise _from_native(error) from None

    def visit(self, reader: TreeReader, callback) -> None:
        """Call callback(element, depth, offset) for matches using C Query traversal.

        Use Visit.CONTINUE/STOP/ERROR or None. Exceptions propagate safely after
        C returns. Do not interleave unmatched pulls or mutate either object in
        callbacks. Callback elements own copied value bytes and may be retained.
        """
        if not isinstance(reader, TreeReader):
            raise TypeError("TreeReader required")
        def adapter(tag, value, depth, offset):
            return callback(Element(Tag(tag), memoryview(value)), depth, offset)
        try:
            _native.query_visit(self._capsule, reader._capsule, adapter)
        except _native.Error as error:
            raise _from_native(error) from None
