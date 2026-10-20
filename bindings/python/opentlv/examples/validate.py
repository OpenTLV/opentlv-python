# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Checks a document's structure -- which tags are required, how many times,
in what nesting, and with what value lengths -- without decoding it. See
parse.py for the document this schema describes.

Run with `python examples/validate.py` from `bindings/python/opentlv`, after
installing both packages.
"""

import opentlv

# Same bytes as parse.py's document.
DOCUMENT = bytes([0x6F, 0x0A, 0x84, 0x03, 0x41, 0x42, 0x43, 0xA5, 0x03, 0x50, 0x01, 0x01])
# Missing the FCI Proprietary Template (A5) the schema requires.
INCOMPLETE = bytes([0x6F, 0x05, 0x84, 0x03, 0x41, 0x42, 0x43])


def main() -> None:
    proprietary_schema = opentlv.StructureSchema([
        opentlv.StructureRule(opentlv.Tag(b"\x50"), min_length=1, max_length=1, min_occurs=1,
                               max_occurs=1, kind=opentlv.Kind.PRIMITIVE),
    ])
    fci_schema = opentlv.StructureSchema([
        opentlv.StructureRule(opentlv.Tag(b"\x84"), min_length=1, max_length=16, min_occurs=1,
                               max_occurs=1, kind=opentlv.Kind.PRIMITIVE),
        opentlv.StructureRule(opentlv.Tag(b"\xa5"), min_occurs=1, max_occurs=1,
                               children=proprietary_schema),
    ])
    top_schema = opentlv.StructureSchema([
        opentlv.StructureRule(opentlv.Tag(b"\x6f"), min_occurs=1, max_occurs=1,
                               children=fci_schema),
    ])

    top_schema.validate(DOCUMENT, format=opentlv.Format.BER)
    print("Document conforms to the schema")

    try:
        top_schema.validate(INCOMPLETE, format=opentlv.Format.BER)
    except opentlv.SchemaError as error:
        print(f"Incomplete document rejected: {error}")


if __name__ == "__main__":
    main()
