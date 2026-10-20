# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

from opentlv import Tag


def test_stores_bytes_in_wire_order():
    tag = Tag(b"\x9f\x02")
    assert bytes(tag) == b"\x9f\x02"
    assert tag.data == b"\x9f\x02"
    assert len(tag) == 2


def test_empty_tag_is_allowed():
    tag = Tag(b"")
    assert len(tag) == 0
    assert bytes(tag) == b""


def test_equality_and_hash_use_bytes_only():
    a = Tag(b"\x5f\x2a")
    b = Tag(bytes([0x5F, 0x2A]))
    c = Tag(b"\x5f")
    assert a == b
    assert a != c
    assert hash(a) == hash(b)
    assert a != 1
    assert a != "5f2a"


def test_ordering_matches_unsigned_lexicographic_bytes():
    assert Tag(b"\x7f") < Tag(b"\x80")
    assert Tag(b"\x9f") < Tag(b"\x9f\x00")
    assert Tag(b"") < Tag(b"\x00")


def test_formats_as_uppercase_hex():
    tag = Tag(b"\x9f\x02")
    assert str(tag) == "9F02"
    assert repr(tag) == "Tag(9F02)"
