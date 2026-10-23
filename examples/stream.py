# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Streams elements from one buffer into a fixed caller-owned output buffer
through one native Writer session: re-encodes most elements, copies a
selected one unchanged, checks the remaining capacity and stops cleanly
when the output is full.

Run with `python examples/stream.py` after installing both packages.
"""

import opentlv


def main() -> None:
    # Tag 0x02 uses a non-minimal long-form BER length (0x81 0x02).
    data = bytes([0x01, 0x01, 0xAA, 0x02, 0x81, 0x02, 0xBB, 0xCC,
                  0x03, 0x00, 0x04, 0x03, 0x01, 0x02, 0x03])
    storage = bytearray(12)
    writer = opentlv.Writer(buffer=storage)  # Never grows or allocates output.
    reader = opentlv.Reader(data)
    while not reader.at_end:
        decoded = reader.read_source()
        element = decoded.element
        try:
            if element.tag == opentlv.Tag(b"\x02"):
                writer.preserve(decoded)  # Original framing, checked by C.
            else:
                writer.write_element(element)  # Canonical re-encoding.
        except opentlv.BufferTooShortError as error:
            print(f"{element.tag}: needs {error.required} bytes, "
                  f"{error.available} left; stopping")
            break
        print(f"{element.tag}: {writer.remaining} bytes left")
    print(f"output: {writer.view().hex(' ')}")

    # Without Layout or source, read_element() skips the metadata that
    # preservation needs; it suits elements that are only inspected.
    element, consumed = opentlv.read_element(data)
    print(f"first element: {element.tag} {bytes(element.value).hex()}, {consumed} bytes")


if __name__ == "__main__":
    main()
