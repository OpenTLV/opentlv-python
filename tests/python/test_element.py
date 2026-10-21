# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

from opentlv import Element, Tag


def test_exposes_tag_and_value():
    tag = Tag(b"\x5a")
    element = Element(tag, memoryview(b"\x01\x02\x03"))
    assert element.tag == tag
    assert bytes(element.value) == b"\x01\x02\x03"


def test_equality_compares_tag_and_value():
    a = Element(Tag(b"\x01"), memoryview(b"\xaa"))
    b = Element(Tag(b"\x01"), memoryview(b"\xaa"))
    c = Element(Tag(b"\x02"), memoryview(b"\xaa"))
    assert a == b
    assert a != c
    assert a != "not an element"


def test_repr_shows_tag_and_value():
    element = Element(Tag(b"\x9f\x02"), memoryview(b"\xde\xad"))
    assert repr(element) == "Element(tag=Tag(9F02), value=b'\\xde\\xad')"
