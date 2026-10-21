# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Shows the one place Python's Writer departs from the C, C++ and Rust
writer: it owns a bytearray it grows as needed, instead of filling a
caller-provided fixed-capacity buffer, so it never fails for lack of space.
It still raises for an error the format itself reports, such as a tag the
format cannot encode.

Run with `python examples/writer.py` from `bindings/python/opentlv`, after
installing both packages.
"""

import opentlv


def main() -> None:
    writer = opentlv.Writer()  # opentlv.Format.BER; starts small and grows.
    # A value far larger than the writer's small initial buffer; no capacity
    # to pre-size or error to retry after, unlike C, C++ or Rust.
    large_value = bytes(1000)
    writer.write(opentlv.Tag(b"\x01"), large_value)
    print(f"wrote {len(writer)} bytes without ever sizing a buffer")

    # A truncated BER identifier is still an error, growable buffer or not.
    try:
        writer.write(opentlv.Tag(b"\x9f"), b"")
    except opentlv.InvalidTagError as error:
        print(f"rejected: {error}")


if __name__ == "__main__":
    main()
