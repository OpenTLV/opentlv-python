# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Addresses elements of a Document by a `/`-separated path of hexadecimal
tags instead of traversing node by node. See document.py for direct navigation
and parse.py for the document this query addresses.

Run with `python examples/query.py` from `bindings/python/opentlv`, after
installing both packages.
"""

import opentlv

# Same bytes as parse.py's document: an FCI Template (6F) holding a DF Name
# (84) and an FCI Proprietary Template (A5) holding an Application Label (50).
DOCUMENT = bytes([0x6F, 0x0A, 0x84, 0x03, 0x41, 0x42, 0x43, 0xA5, 0x03, 0x50, 0x01, 0x01])


def main() -> None:
    with opentlv.Document(DOCUMENT, opentlv.Format.BER) as document:
        # A multi-tag query traverses straight to a deeply nested element,
        # without visiting 6F and A5 as separate steps.
        label = document.find_path("6F/A5/50")
        print(f"6F/A5/50 -> tag {label.tag} value {bytes(label.value).hex(' ').upper()}")

        # A one-tag query is the same as document.find() at the top level.
        assert document.find_path("6F") == document.find(opentlv.Tag(b"\x6f"))

        # No match is not an error: it is simply None, same as find().
        assert document.find_path("6F/99") is None

        # Malformed query text raises, distinct from "no match".
        try:
            document.find_path("6F//50")
        except opentlv.InvalidSyntaxError as error:
            print(f"rejected: {error}")


if __name__ == "__main__":
    main()
