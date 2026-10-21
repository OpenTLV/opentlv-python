# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""The simplest possible round trip: write one element with the
configurable fixed-width format, then read it back. See parse.py and
write.py for a nested BER document, and the C `quick_start.c`, C++
`quick_start.cpp` and Rust `quick_start.rs` examples for the same round
trip in those languages.

Run with `python examples/quick_start.py` from `bindings/python/opentlv`,
after installing both packages (see ../../../README.md or
docs/development/python.md).
"""

import opentlv


def main() -> None:
    # One tag byte and one length byte.
    format = opentlv.FixedFormat(1, 1)
    writer = opentlv.Writer(format)
    writer.write(b"\x01", b"Hello, world!")

    for element in opentlv.Reader(writer.bytes(), format):
        print(element.value.tobytes().decode("utf-8"))


if __name__ == "__main__":
    main()
