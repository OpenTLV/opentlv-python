# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Generates reproducible wire cases for a custom TLV format and checks a
round-trip property over them, the way a property-based test or a fuzz
corpus would use them.

Each case is one complete stream produced by the canonical C generator from
a candidate table, limits, a seed and a case index. The same inputs always
produce the same bytes, so a failing case is replayed from its index alone.

Run with `python examples/generate.py` from the repository root, after
installing both packages.
"""

import opentlv


def main() -> None:
    format = opentlv.Format.escaped(
        opentlv.FixedIdentifier(1),
        opentlv.EscapedLength(0xFF, 2),
        constructed=opentlv.ConstructedBit(0, 0x80, 0x80))
    generator = opentlv.Generator(
        format,
        [opentlv.GeneratorCandidate(b"\x01", 0, 300),  # crosses the 0xFF length escape
         opentlv.GeneratorCandidate(b"\x02", 0, 8),
         opentlv.GeneratorCandidate(b"\x81", 0, 128)],  # constructed: generated children
        max_elements=16, max_depth=3, max_value_size=300, max_case_size=4096, seed=2026)
    print(f"generator version {generator.VERSION}, workspace {generator.workspace_size} bytes")

    # Property: every case re-encodes byte-exactly through a Document.
    for case_index in range(100):
        wire = generator.generate(case_index)
        with opentlv.Document(wire, format) as document:
            assert document.encode() == wire, f"case {case_index} does not round-trip"

    wire = generator.generate(7)
    print("case 7:", len(wire), "bytes")
    for item in opentlv.TreeReader(wire, format):
        kind = "constructed" if item.constructed else f"{len(item.element.value)} bytes"
        print("  " * (item.depth + 1) + f"{item.element.tag}: {kind}")

    # Reuse caller storage of at least max_case_size bytes across cases.
    storage = bytearray(4096)
    written = generator.generate_into(storage, 7)
    assert storage[:written] == wire


if __name__ == "__main__":
    main()
