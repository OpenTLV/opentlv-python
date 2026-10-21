# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Optional mutable TLV document that owns its data and can be modified and encoded again."""

from __future__ import annotations

from typing import Iterator, Optional, Union
from weakref import WeakValueDictionary

import _opentlv as _native

from opentlv.error import _from_native, InvalidStateError
from opentlv.format import Format, _resolve_format, _format_specification
from opentlv.tag import Tag
from opentlv.cursor import TreeReader

_DEFAULT_MAX_DEPTH = 64
"""TLV_TREE_DEFAULT_DEPTH."""

_DEFAULT_MAX_ELEMENTS = 65536
"""TLV_DOCUMENT_DEFAULT_MAX_ELEMENTS."""


class _Lifetime:
    """Ownership metadata only; native C remains the source of node topology."""

    __slots__ = ("parent", "parent_revision", "revision", "alive", "__weakref__")

    def __init__(self, parent):
        self.parent = parent
        self.parent_revision = parent.revision if parent else 0
        self.revision = 0
        self.alive = True

    def valid(self):
        token = self
        while token is not None:
            if not token.alive:
                return False
            parent = token.parent
            if parent is not None and token.parent_revision != parent.revision:
                return False
            token = parent
        return True


class Node:
    """One element of a `Document`; owned by it.

    Erasing a node invalidates it and its descendants. Replacing a constructed
    value invalidates its old descendants, while the node itself stays valid.
    Invalid access raises ValueError, including after Document.close(). A Node
    keeps its document alive until explicitly closed or no longer reachable.
    """

    __slots__ = ("_document", "_address", "_lifetime", "_query_generation")

    def __init__(self, document: "Document", ptr: int, *, _key=None) -> None:
        if _key is not document._lifetimes:
            raise TypeError("nodes are obtained from Document operations")
        self._document = document
        self._address = ptr
        self._lifetime = document._lifetime(ptr)
        self._query_generation = document._query_generation

    @property
    def _ptr(self):
        if (self._document._capsule is None or
                self._query_generation != self._document._query_generation or
                not self._lifetime.valid()):
            raise ValueError("node is no longer valid")
        return self._address

    @property
    def tag(self) -> Tag:
        """The node's tag."""
        return Tag(_native.node_tag(self._ptr))

    @property
    def is_constructed(self) -> bool:
        """`True` if the node's value holds nested elements."""
        return _native.node_is_constructed(self._ptr)

    @property
    def value(self) -> bytes:
        """The node's value bytes; empty for a constructed node (read its
        children instead)."""
        return _native.node_value(self._ptr)

    @value.setter
    def value(self, value: bytes) -> None:
        """Replaces the value. For a constructed node, `value` is parsed as
        nested elements with the document's format, replacing every
        child."""
        self._document._assert_mutable()
        value = bytes(memoryview(value))
        pointer = self._ptr
        previous_revision = self._lifetime.revision
        # Invalidate before entering C: a signal delivered immediately after C
        # returns must not leave handles pointing at already released children.
        self._lifetime.revision += 1
        try:
            _native.node_set_value(pointer, value)
        except _native.Error as native_error:
            # A reported native failure guarantees the old tree is unchanged.
            self._lifetime.revision = previous_revision
            raise _from_native(native_error) from None

    @property
    def parent(self) -> Optional["Node"]:
        """The parent node, or `None` for a top-level node."""
        return self._document._wrap(_native.node_parent(self._ptr))

    @property
    def first_child(self) -> Optional["Node"]:
        """The first child of a constructed node, or `None`."""
        return self._document._wrap(_native.node_first_child(self._ptr))

    @property
    def identity(self) -> int:
        """Stable native identity in this Document; stale handles fail before access."""
        return _native.node_identity(self._ptr)

    @property
    def next(self) -> Optional["Node"]:
        """The next sibling, or `None`."""
        return self._document._wrap(_native.node_next(self._ptr))

    def next_same_tag(self) -> Optional["Node"]:
        """The next sibling with the same tag as this node, or `None`."""
        return self._document._wrap(_native.node_next_same_tag(self._ptr))

    def __iter__(self) -> Iterator["Node"]:
        """Iterates this node's direct children, in encoding order."""
        child = self.first_child
        while child is not None:
            yield child
            child = child.next

    def find(self, tag: Union[Tag, bytes]) -> Optional["Node"]:
        """Finds the first direct child with `tag`."""
        return self._document.find(tag, parent=self)

    def insert(self, tag: Union[Tag, bytes], value: bytes = b"",
               before: Optional["Node"] = None) -> "Node":
        """Inserts a new child element; see `Document.insert`."""
        return self._document.insert(tag, value, parent=self, before=before)

    def erase(self) -> None:
        """Removes this node and all of its descendants from its document."""
        self._document._assert_mutable()
        pointer = self._ptr
        self._lifetime.alive = False
        _native.node_erase(pointer)

    @property
    def encoded_size(self) -> int:
        """The encoded size of this element with its descendants."""
        try:
            return _native.node_encoded_size(self._ptr)
        except _native.Error as native_error:
            raise _from_native(native_error) from None

    def encoded_size_as(self, format: Format) -> int:
        """Measure this subtree in a compatible destination builtin Format."""
        try:
            return _native.node_encoded_size(self._ptr, _resolve_format(format))
        except _native.Error as native_error:
            raise _from_native(native_error) from None

    def encode(self, format: Format | None = None) -> bytes:
        """Encode this subtree, optionally using a compatible destination builtin."""
        try:
            return _native.node_encode(self._ptr, -1 if format is None else _resolve_format(format))
        except _native.Error as native_error:
            raise _from_native(native_error) from None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Node):
            return self._lifetime is other._lifetime and self._document is other._document
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._lifetime)

    def __repr__(self) -> str:
        kind = "constructed" if self.is_constructed else "primitive"
        return f"Node(tag={self.tag!r}, {kind})"


class Document:
    """An owned, mutable TLV document: parses input into a tree of nodes that
    can be searched, changed, extended and shortened, then encoded again.

    Unlike `Reader`/`Writer`, a document copies every tag and value into its
    own storage, so it is the only part of OpenTLV that allocates beyond a
    Python object's own memory. Close it deterministically with `close()` or
    a `with` block instead of waiting for garbage collection when that
    matters, for example for a large document.

    >>> document = Document(bytes([0x01, 0x02, 0xAA, 0xBB]))
    >>> node = document.first
    >>> node.tag.data, node.value
    (b'\\x01', b'\\xaa\\xbb')
    >>> node.value = b"\\xcc"
    >>> document.encode()
    b'\\x01\\x01\\xcc'
    """

    __slots__ = ("_capsule", "_lifetimes", "_query_generation", "_query_active")

    def __init__(self, data: Optional[bytes] = None, format: Format | None = None, *,
                 max_depth: int = _DEFAULT_MAX_DEPTH,
                 max_elements: int = _DEFAULT_MAX_ELEMENTS,
                 retain_source_locations: bool = False) -> None:
        """Creates a document, empty or parsed from `data`.

        `format` is used both to parse `data` (and any constructed value
        later assigned to a node) and to `encode()` the document again.
        `retain_source_locations` preserves original offsets/header lengths for
        Query without borrowing input bytes. Edits invalidate affected nodes and
        ancestors; unaffected nodes retain their original coordinates.
        """
        format = _format_specification(format)
        self._lifetimes = WeakValueDictionary()
        self._query_generation = 0
        self._query_active = 0
        try:
            if data is None:
                self._capsule = _native.document_create(format, max_depth, max_elements)
            else:
                self._capsule = _native.document_parse(
                    data, format, max_depth, max_elements, retain_source_locations)
        except _native.Error as native_error:
            raise _from_native(native_error) from None

    def _assert_mutable(self):
        if self._query_active:
            raise InvalidStateError(_native.RESULT_INVALID_STATE)

    def _lifetime(self, ptr):
        if self._capsule is None:
            raise ValueError("document is closed")
        # Only retained handles need ownership tokens. Read ancestry from C;
        # this neither enumerates nor processes the document's elements.
        pending = []
        parent = None
        while ptr is not None:
            parent = self._lifetimes.get(ptr)
            if parent is not None and parent.valid():
                break
            pending.append(ptr)
            ptr = _native.node_parent(ptr)
            parent = None
        for address in reversed(pending):
            parent = _Lifetime(parent)
            self._lifetimes[address] = parent
        return parent

    def _node_ptr(self, node):
        if node is None:
            return None
        if not isinstance(node, Node) or node._document is not self:
            raise ValueError("node belongs to a different document")
        return node._ptr

    def _wrap(self, ptr: Optional[int]) -> Optional[Node]:
        return None if ptr is None else Node(self, ptr, _key=self._lifetimes)

    def __len__(self) -> int:
        """The number of elements in the document, including nested ones."""
        return _native.document_count(self._capsule)

    @property
    def first(self) -> Optional[Node]:
        """The first top-level node, or `None` for an empty document."""
        return self._wrap(_native.document_first(self._capsule))

    def __iter__(self) -> Iterator[Node]:
        """Iterates the top-level nodes, in encoding order."""
        node = self.first
        while node is not None:
            yield node
            node = node.next

    def find(self, tag: Union[Tag, bytes], parent: Optional[Node] = None) -> Optional[Node]:
        """Finds the first direct child of `parent` (or the top level) with `tag`."""
        tag_bytes = tag.data if isinstance(tag, Tag) else tag
        parent_ptr = self._node_ptr(parent)
        return self._wrap(_native.document_find(self._capsule, parent_ptr, tag_bytes))

    def find_path(self, query: str) -> Optional[Node]:
        """Finds the first element addressed by a path query, for example `"6F/A5/50"`."""
        try:
            return self._wrap(_native.document_find_path(self._capsule, query))
        except _native.Error as native_error:
            raise _from_native(native_error) from None

    def insert(self, tag: Union[Tag, bytes], value: bytes = b"", parent: Optional[Node] = None,
               before: Optional[Node] = None) -> Node:
        """Inserts a new element with `tag` and `value`.

        `parent` is the constructed node that receives the element, or
        `None` for the top level; `before` is an existing child of `parent`
        the new node precedes, or `None` to append at the end. As for
        `Node.value`, a value of a tag the document's format treats
        as constructed is parsed as nested elements.
        """
        self._assert_mutable()
        tag_bytes = tag.data if isinstance(tag, Tag) else tag
        parent_ptr = self._node_ptr(parent)
        before_ptr = self._node_ptr(before)
        try:
            ptr = _native.document_insert(self._capsule, parent_ptr, before_ptr, tag_bytes, value)
        except _native.Error as native_error:
            raise _from_native(native_error) from None
        return self._wrap(ptr)

    def select(self, program, *, bindings=None, context=None, value_capacity=None, **limits):
        """Evaluate a compiled Query, returning checked snapshot Nodes or an owned scalar.

        Query workspace and Value snapshot allocation belongs to the Python
        wrapper. Use QueryExecution for explicit storage and continuation.
        """
        from opentlv.program import QueryProgram
        if not isinstance(program, QueryProgram):
            raise TypeError("QueryProgram required")
        execution = program.execution(**limits)
        for name, value in (bindings or {}).items():
            execution.bind(name, value)
        execution.evaluate_document(self, context=context, value_capacity=value_capacity)
        return list(execution) if program.info["result_kind"] == 0 else execution.result()

    @property
    def encoded_size(self) -> int:
        """The encoded size of the whole document."""
        try:
            return _native.document_encoded_size(self._capsule)
        except _native.Error as native_error:
            raise _from_native(native_error) from None

    def encoded_size_as(self, format: Format) -> int:
        """Measure the document in a compatible destination builtin Format."""
        try:
            return _native.document_encoded_size(self._capsule, _resolve_format(format))
        except _native.Error as native_error:
            raise _from_native(native_error) from None

    def encode(self, format: Format | None = None) -> bytes:
        """Encode the document, optionally using a compatible destination builtin."""
        try:
            return _native.document_encode(self._capsule, -1 if format is None else _resolve_format(format))
        except _native.Error as native_error:
            raise _from_native(native_error) from None

    def close(self) -> None:
        """Frees the document immediately instead of waiting for garbage collection.

        Every node from this document, and the document itself, must not be
        used afterwards.
        """
        self._assert_mutable()
        self._capsule = None

    def __enter__(self) -> "Document":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"Document(count={len(self)})"


class DocumentBuilder:
    """Resumable C materialization of a whole stream or its next subtree.

    current_subtree=True selects the last item returned by next(reader), for
    example after QueryMatcher.matches(). It performs no second root pull.
    Pulls, input replacement, skips, visitors and builder creation invalidate
    that selection. It cannot be combined with next_subtree=True.

    While active, the TreeReader permits input replacement and status queries,
    but rejects pulls, skips and visitors. consume() returns an owning Document
    only when complete; NeedMoreDataError retains unfinished state. Terminal
    errors, completion and close() release the reader for further use.
    """
    __slots__ = ("_capsule", "_reader")

    def __init__(self, reader: TreeReader, *, next_subtree=False, current_subtree=False,
                 max_depth=_DEFAULT_MAX_DEPTH, max_elements=_DEFAULT_MAX_ELEMENTS):
        if not isinstance(reader, TreeReader):
            raise TypeError("DocumentBuilder requires a TreeReader")
        if next_subtree and current_subtree:
            raise ValueError("choose either next_subtree or current_subtree")
        self._reader = reader
        try:
            self._capsule = _native.document_builder_create(
                reader._capsule, 2 if current_subtree else int(next_subtree),
                max_depth, max_elements)
        except _native.Error as error:
            raise _from_native(error) from None

    def consume(self) -> Document:
        """Consume available items; propagate C continuation or terminal errors."""
        # Allocate facade bookkeeping before C transfers ownership.
        document = Document.__new__(Document)
        document._lifetimes = WeakValueDictionary()
        document._query_generation = 0
        document._query_active = 0
        try:
            document._capsule = _native.document_builder_consume(self._capsule)
        except _native.Error as error:
            raise _from_native(error) from None
        return document

    def close(self) -> None:
        """Discard unfinished nodes and release the cursor; completed data survives."""
        self._capsule = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
