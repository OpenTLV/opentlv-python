# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Parses a nested BER-TLV document and prints every element in document
order, descending into constructed elements recursively; then shows how a
truncated buffer surfaces as an error instead of a partial result. See
write.py for building the same bytes and validate.py for checking the
document's structure without decoding it. The C, C++, Rust and JavaScript
"parse" examples parse the same bytes and report the same fields.

Run with `python examples/parse.py` from `bindings/python/opentlv`, after
installing both packages.
"""

import opentlv

# An FCI Template (6F) holding a DF Name (84) and an FCI Proprietary
# Template (A5) holding an Application Label (50).
DOCUMENT = bytes([0x6F, 0x0A, 0x84, 0x03, 0x41, 0x42, 0x43, 0xA5, 0x03, 0x50, 0x01, 0x01])


def print_elements(data: bytes, depth: int = 0) -> int:
    # Elements borrow `data`; nesting is descended by re-reading a child
    # element's value with a new Reader.
    count = 0
    for element in opentlv.Reader(data, opentlv.Format.BER):
        value = bytes(element.value)
        print(f"{'  ' * depth}tag={element.tag} length={len(value)} value={value.hex(' ').upper()}")
        count += 1

        # Bit 6 of the first tag byte marks a constructed (nested) element.
        if element.tag.data[0] & 0x20:
            count += print_elements(value, depth + 1)
    return count


def main() -> None:
    count = print_elements(DOCUMENT)
    # 6F, its two children (84, A5) and A5's child (50).
    assert count == 4

    # Malformed input raises instead of returning a partial result.
    truncated = DOCUMENT[:-2]
    try:
        list(opentlv.Reader(truncated, opentlv.Format.BER))
    except opentlv.OpenTLVError as error:
        print(f"truncated input: {error} (offset {error.offset})")


if __name__ == "__main__":
    main()
