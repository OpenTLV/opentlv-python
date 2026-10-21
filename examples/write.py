# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Builds the same nested BER-TLV document parse.py reads, encoding the
innermost elements first and using each encoded result as the next level's
value: the standard way to build constructed TLV bottom-up.

Run with `python examples/write.py` from `bindings/python/opentlv`, after
installing both packages.
"""

import opentlv

# Same bytes as parse.py's document.
EXPECTED = bytes([0x6F, 0x0A, 0x84, 0x03, 0x41, 0x42, 0x43, 0xA5, 0x03, 0x50, 0x01, 0x01])


def main() -> None:
    df_name = opentlv.Writer(opentlv.Format.BER)
    df_name.write(opentlv.Tag(b"\x84"), b"ABC")

    label = opentlv.Writer(opentlv.Format.BER)
    label.write(opentlv.Tag(b"\x50"), b"\x01")

    proprietary = opentlv.Writer(opentlv.Format.BER)
    proprietary.write(opentlv.Tag(b"\xa5"), label.bytes())

    document = opentlv.Writer(opentlv.Format.BER)
    document.write(opentlv.Tag(b"\x6f"), df_name.bytes() + proprietary.bytes())

    encoded = document.bytes()
    print(f"wrote {len(encoded)} bytes: {encoded.hex(' ').upper()}")
    assert encoded == EXPECTED


if __name__ == "__main__":
    main()
