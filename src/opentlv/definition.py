# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Generic identifier metadata; registry lookup delegates to C."""
from dataclasses import dataclass
import _opentlv as _native
from opentlv.tag import Tag


@dataclass(frozen=True)
class Definition:
    """Canonical identifier and descriptive name, without Schema or Codec policy."""
    tag: Tag
    name: str | None = None

    def __post_init__(self):
        if not isinstance(self.tag, Tag):
            object.__setattr__(self, "tag", Tag(bytes(self.tag)))
        if self.name is not None:
            if not isinstance(self.name, str):
                raise TypeError("definition name must be a string or None")
            if "\x00" in self.name:
                raise ValueError("definition name cannot contain NUL")


class DefinitionRegistry:
    """Owned registry; duplicate identifiers resolve to the first entry through C."""
    __slots__ = ("_definitions",)

    def __init__(self, definitions=()):
        self._definitions = tuple(definitions)
        if any(not isinstance(item, Definition) for item in self._definitions):
            raise TypeError("Definition records required")

    @property
    def definitions(self) -> tuple[Definition, ...]:
        """Immutable records in registry order."""
        return self._definitions

    def find(self, tag) -> Definition | None:
        """Find using C's tag equality; unknown identifiers return None."""
        tag = tag.data if isinstance(tag, Tag) else bytes(tag)
        index = _native.definition_find(tuple(item.tag.data for item in self._definitions), tag)
        return None if index is None else self._definitions[index]
