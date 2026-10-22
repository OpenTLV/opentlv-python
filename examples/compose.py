# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Defines a proprietary TLV format from generic field encodings and uses it
with the standard Tree Writer, Reader, Document and Query, without writing C.

Each element has a one-byte tag and an escaped length: one byte below 0xFF,
or 0xFF followed by a two-byte big-endian count. Tags with the top bit set
hold nested elements.

Run with `python examples/compose.py` from the repository root, after
installing both packages.
"""

import opentlv


def main() -> None:
    format = opentlv.Format.escaped(
        opentlv.FixedIdentifier(1),
        opentlv.EscapedLength(0xFF, 2),
        constructed=opentlv.ConstructedBit(0, 0x80, 0x80))

    writer = opentlv.TreeWriter(1024, format)
    writer.begin(b"\x81")
    writer.write(opentlv.Element(opentlv.Tag(b"\x01"), b"\x00" * 300))
    writer.write(opentlv.Element(opentlv.Tag(b"\x02"), b"name"))
    writer.end()
    wire = writer.finish()
    print("wire:", wire[:6].hex(" ").upper(), "...", len(wire), "bytes")

    for item in opentlv.TreeReader(wire, format):
        kind = "constructed" if item.constructed else f"{len(item.element.value)} bytes"
        print("  " * item.depth + f"{item.element.tag}: {kind}")

    with opentlv.Document(wire, format) as document:
        program = opentlv.QueryProgram("//02", format=format)
        (name,) = document.select(program)
        print("//02 ->", bytes(name.value).decode())
        assert document.encode() == wire

    # The Format itself decodes, measures and encodes one element.
    print(format.measure(b"\x02", b"name"))
    assert format.decode(wire).element.tag == opentlv.Tag(b"\x81")


if __name__ == "__main__":
    main()
