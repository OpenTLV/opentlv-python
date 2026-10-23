# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Audits and edits a parsed record: validates a decoded INTEGER against
named numbers, changes a 3-bit flag of a packed header byte without
touching its other bits, and reports the Document revision and where the
changed element was in the original input.

Run with `python examples/audit.py` after installing both packages.
"""

import opentlv

COLOR = opentlv.ValueConstraint.allowed({0: "red", 1: "green", 2: "blue"})
PRIORITY = opentlv.PackedField(bit_offset=5, bit_width=3)  # Top bits of one byte.


def main() -> None:
    # SEQUENCE { INTEGER 1, OCTET STRING A4 }: a color and a header byte.
    wire = bytes.fromhex("30060201010401a4")
    document = opentlv.Document(wire, retain_source_locations=True)
    color, header = document.first

    value = opentlv.ValueCodec.INT64_MINIMAL_BE.decode(color.value)
    COLOR.validate(value)
    print(f"color {value} is {COLOR.name(value)}")
    try:
        COLOR.validate(7)
    except opentlv.SchemaError:
        print("color 7 is not allowed")

    data = bytearray(header.value)
    print(f"priority {PRIORITY.read(data, header_size=1)} in header {data.hex()}")
    PRIORITY.write(data, 2, header_size=1)
    print(f"priority 2 in header {data.hex()}")

    revision = document.revision
    origin = header.source_location  # An edit drops the changed node's coordinates.
    header.value = data
    print(f"revision {revision} -> {document.revision}: {header.tag} was at offset "
          f"{origin.offset}; unchanged {color.tag} is still at "
          f"{color.source_location.offset}")
    print(f"encoded: {document.encode().hex(' ')}")


if __name__ == "__main__":
    main()
