# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Deterministic wire generation through the canonical C generator."""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Iterable, Union

import _opentlv as _native

from opentlv.field import _unsigned
from opentlv.format import _format_specification
from opentlv.format_operations import _call
from opentlv.tag import Tag

Buffer = Union[bytearray, memoryview]


@dataclass(frozen=True)
class GeneratorCandidate:
    """A candidate identifier and inclusive Value size interval (`tlv_generator_candidate_t`).

    The Format classifies constructed identifiers, which receive generated
    child streams; primitive Values contain arbitrary bytes. Leave out stream
    terminators and identifiers that require contextual ordering. An empty
    `tag` is the empty identifier, for formats that accept one.
    """

    tag: Union[Tag, bytes]
    min_value_size: int
    max_value_size: int

    def __post_init__(self) -> None:
        if not isinstance(self.tag, Tag):
            object.__setattr__(self, "tag", Tag(bytes(memoryview(self.tag))))
        _unsigned("min_value_size", self.min_value_size, sys.maxsize)
        _unsigned("max_value_size", self.max_value_size, sys.maxsize)

    def _native(self) -> tuple:
        return (self.tag.data, self.min_value_size, self.max_value_size)


class Generator:
    """Reproducible wire cases from the canonical C generator (`tlv_generate()`).

    Each case is one nonempty complete stream of candidate elements that
    decodes and re-encodes byte-exactly through the Format; it is wire data,
    not Schema- or Codec-valid content. The same `VERSION`, Format,
    candidates, limits, seed and case index produce the same bytes,
    independent of earlier calls. Different seed or index pairs do not
    guarantee different bytes.

    Python checks only types and representable ranges; Core validates the
    configuration and the Format's read and write capability on every call
    and performs all generation. Scratch workspace is allocated per call.
    """

    VERSION = _native.GENERATOR_VERSION
    """Native algorithm version (`TLV_GENERATOR_VERSION`); record it with corpora."""

    __slots__ = ("_specification", "_limits", "_candidates")

    def __init__(self, format, candidates: Iterable[GeneratorCandidate], *, max_elements: int,
                 max_depth: int, max_value_size: int, max_case_size: int,
                 seed: int = 0) -> None:
        """Copy the configuration and keep the Format alive.

        `max_elements` counts parents too, `max_depth` bounds child depth
        (roots have depth zero, at most 64), `max_value_size` bounds every
        Value and `max_case_size` the complete stream, in bytes.
        """
        candidates = tuple(candidates)
        for candidate in candidates:
            if not isinstance(candidate, GeneratorCandidate):
                raise TypeError("candidates must be GeneratorCandidate instances")
        self._specification = _format_specification(format)
        self._limits = (
            _unsigned("seed", seed),
            _unsigned("max_elements", max_elements, sys.maxsize),
            _unsigned("max_depth", max_depth, sys.maxsize),
            _unsigned("max_value_size", max_value_size, sys.maxsize),
            _unsigned("max_case_size", max_case_size, sys.maxsize))
        self._candidates = tuple(candidate._native() for candidate in candidates)

    def _options(self, case_index: int) -> tuple:
        seed, *limits = self._limits
        return (seed, _unsigned("case_index", case_index), *limits, self._candidates)

    @property
    def workspace_size(self) -> int:
        """Scratch bytes each case requires (`tlv_generator_workspace_size()`).

        Validates the limits and candidates, but not the Format.
        """
        return _call(_native.generator_workspace_size, self._options(0))

    def generate(self, case_index: int = 0) -> bytes:
        """Generate case `case_index` into new bytes of its exact size."""
        return _call(_native.generate, self._specification, self._options(case_index), None)

    def generate_into(self, buffer: Buffer, case_index: int = 0) -> int:
        """Generate case `case_index` at the start of writable `buffer`; return its size.

        `buffer` needs at least `max_case_size` bytes, otherwise
        `BufferTooShortError` is raised; extra capacity does not change the
        case. Bytes of `buffer` may change even when generation fails.
        """
        view = memoryview(buffer)
        if view.readonly or not view.c_contiguous:
            raise ValueError("buffer must be writable and contiguous")
        return _call(_native.generate, self._specification, self._options(case_index),
                     view.cast("B"))
