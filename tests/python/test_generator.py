# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import gc

import pytest
import _opentlv
from opentlv import (BufferTooShortError, ConstructedBit, Document, EscapedLength, FixedFormat,
                     FixedIdentifier, Format, Generator, GeneratorCandidate, InvalidArgError,
                     LimitError, Tag, TreeReader, UnsupportedError)

LIMITS = dict(max_elements=12, max_depth=3, max_value_size=300, max_case_size=2048)


def proprietary():
    # One-byte tag, escaped length and constructed tags with the top bit set.
    return Format.escaped(FixedIdentifier(1), EscapedLength(0xFF, 2),
                          constructed=ConstructedBit(0, 0x80, 0x80))


def domains():
    domains = [
        pytest.param(FixedFormat(1, 2), [GeneratorCandidate(b"\x01", 0, 300),
                                         GeneratorCandidate(b"\x02", 1, 3)], id="fixed"),
        pytest.param(proprietary(), [GeneratorCandidate(b"\x01", 0, 300),
                                     GeneratorCandidate(b"\x81", 0, 64)], id="composed")]
    if _opentlv.HAS_BER:
        domains.append(pytest.param(Format.BER, [GeneratorCandidate(b"\x5a", 0, 255),
                                                 GeneratorCandidate(b"\x70", 0, 64)], id="ber"))
    return domains


def items(data, format):
    return [(item.depth, item.element.tag, len(item.element.value), item.constructed)
            for item in TreeReader(data, format)]


@pytest.mark.parametrize("format, candidates", domains())
def test_cases_are_complete_reconstructible_streams(format, candidates):
    generator = Generator(format, candidates, seed=7, **LIMITS)
    tags = {candidate.tag for candidate in candidates}
    for case_index in range(16):
        data = generator.generate(case_index)
        assert 0 < len(data) <= LIMITS["max_case_size"]
        decoded = items(data, format)
        assert 0 < len(decoded) <= LIMITS["max_elements"]
        assert {tag for _, tag, _, _ in decoded} <= tags
        assert all(depth <= LIMITS["max_depth"] for depth, _, _, _ in decoded)
        with Document(data, format) as document:
            assert document.encode() == data


def test_cases_are_reproducible_and_random_access():
    candidates = [GeneratorCandidate(b"\x01", 0, 300), GeneratorCandidate(b"\x81", 0, 64)]
    first = Generator(proprietary(), candidates, seed=42, **LIMITS)
    later = [first.generate(index) for index in reversed(range(8))][::-1]
    second = Generator(proprietary(), candidates, seed=42, **LIMITS)
    assert [second.generate(index) for index in range(8)] == later
    other = Generator(proprietary(), candidates, seed=43, **LIMITS)
    assert [other.generate(index) for index in range(8)] != later
    assert Generator.VERSION == _opentlv.GENERATOR_VERSION >= 2


def test_constructed_candidates_nest_within_max_depth():
    candidates = [GeneratorCandidate(b"\x01", 0, 8), GeneratorCandidate(b"\x81", 0, 64)]
    nested = Generator(proprietary(), candidates, **LIMITS)
    depths = {depth for index in range(32)
              for depth, _, _, _ in items(nested.generate(index), proprietary())}
    assert max(depths) > 0
    flat = Generator(proprietary(), candidates, **dict(LIMITS, max_depth=0))
    assert all(depth == 0 for index in range(32)
               for depth, _, _, _ in items(flat.generate(index), proprietary()))


def test_values_respect_candidate_intervals():
    format = FixedFormat(1, 1)
    generator = Generator(format, [GeneratorCandidate(b"\x01", 2, 5)], **LIMITS)
    sizes = {size for index in range(32)
             for _, _, size, _ in items(generator.generate(index), format)}
    assert sizes <= set(range(2, 6)) and {2, 5} <= sizes


def test_generate_into_caller_storage():
    generator = Generator(FixedFormat(1, 2), [GeneratorCandidate(b"\x01", 0, 300)], **LIMITS)
    storage = bytearray(b"\xee" * (LIMITS["max_case_size"] + 16))
    written = generator.generate_into(storage, 5)
    assert bytes(storage[:written]) == generator.generate(5)
    view = memoryview(bytearray(LIMITS["max_case_size"]))
    assert bytes(view[:generator.generate_into(view, 5)]) == generator.generate(5)
    with pytest.raises(BufferTooShortError):
        generator.generate_into(bytearray(LIMITS["max_case_size"] - 1))
    with pytest.raises(ValueError):
        generator.generate_into(bytes(LIMITS["max_case_size"]))


def test_workspace_size_is_computed_by_core():
    generator = Generator(FixedFormat(1, 2), [GeneratorCandidate(b"\x01", 0, 8)], **LIMITS)
    assert generator.workspace_size == (LIMITS["max_depth"] + 1) * LIMITS["max_case_size"]


def test_composed_format_stays_alive():
    generator = Generator(proprietary(), [GeneratorCandidate(b"\x01", 0, 8)], **LIMITS)
    gc.collect()
    assert generator.generate(0) == generator.generate(0)


@pytest.mark.parametrize("candidates, limits, error", [
    ([GeneratorCandidate(b"\x01", 5, 2)], {}, InvalidArgError),
    ([], {}, InvalidArgError),
    ([GeneratorCandidate(b"\x01", 0, 8)], {"max_elements": 0}, InvalidArgError),
    ([GeneratorCandidate(b"\x01", 0, 8)], {"max_case_size": 0}, InvalidArgError),
    ([GeneratorCandidate(b"\x01", 0, 8)], {"max_depth": 65}, UnsupportedError),
])
def test_core_validates_configuration(candidates, limits, error):
    generator = Generator(FixedFormat(1, 2), candidates, **dict(LIMITS, **limits))
    with pytest.raises(error):
        generator.workspace_size
    with pytest.raises(error):
        generator.generate()
    with pytest.raises(error):
        generator.generate_into(bytearray(LIMITS["max_case_size"]))


def test_core_rejects_unsupported_identifiers():
    # A one-byte Fixed Format rejects the only candidate, so no case can be generated.
    generator = Generator(FixedFormat(1, 2), [GeneratorCandidate(b"\x01\x02", 0, 8)], **LIMITS)
    with pytest.raises(LimitError):
        generator.generate()


def test_python_checks_types_and_ranges():
    candidate = GeneratorCandidate(bytearray(b"\x01"), 0, 1)
    assert candidate.tag == Tag(b"\x01")
    maximum = 2 ** 64 - 1
    generator = Generator(FixedFormat(1, 2), [candidate], seed=maximum, **LIMITS)
    assert generator.generate(maximum)
    for seed in (-1, maximum + 1):
        with pytest.raises(ValueError):
            Generator(FixedFormat(1, 2), [candidate], seed=seed, **LIMITS)
    with pytest.raises(ValueError):
        generator.generate(maximum + 1)
    with pytest.raises(TypeError):
        Generator(FixedFormat(1, 2), [candidate], **dict(LIMITS, max_depth=True))
    with pytest.raises(TypeError):
        Generator(FixedFormat(1, 2), [(b"\x01", 0, 1)], **LIMITS)
    with pytest.raises(ValueError):
        GeneratorCandidate(b"\x01", -1, 1)
    with pytest.raises(TypeError):
        GeneratorCandidate(5, 0, 1)
