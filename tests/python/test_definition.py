# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import gc
import pytest
from opentlv import Definition, DefinitionRegistry, Tag


def test_registry_uses_c_first_match_and_retains_owned_metadata():
    source = bytearray([1])
    first = Definition(source, "first-?")
    registry = DefinitionRegistry([first, Definition(b"\x01", "second"), Definition(b"")])
    source[0] = 2
    found = registry.find(b"\x01")
    assert found is first
    assert registry.find(b"").name is None
    assert registry.find(b"\x02") is None
    assert len(registry.definitions) == 3
    assert DefinitionRegistry().find(b"") is None
    del registry, source
    gc.collect()
    assert found.tag == Tag(b"\x01") and found.name == "first-?"
    with pytest.raises(ValueError):
        Definition(b"\x01", "bad\x00name")
