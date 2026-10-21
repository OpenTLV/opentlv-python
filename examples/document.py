# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Changes an existing message with Document instead of rebuilding it from
scratch: parses it into a tree of nodes, replaces one value, appends a new
top-level element, and encodes the result. Document is the allocating,
mutable counterpart to the zero-copy Reader/Writer; see parse.py/write.py for
those.

Run with `python examples/document.py` from `bindings/python/opentlv`, after
installing both packages.
"""

import opentlv

# An FCI Template (6F) holding a DF Name (84) and an Application Label (50).
FCI = bytes([0x6F, 0x0B, 0x84, 0x03, 0x41, 0x42, 0x43, 0x50, 0x04, ord("O"), ord("L"), ord("D"), 0])


def main() -> None:
    with opentlv.Document(FCI, opentlv.Format.BER) as document:
        fci = document.first  # the 6F template
        label = fci.find(opentlv.Tag(b"\x50"))  # a direct child of 6F, not top-level
        print(f"original label: {bytes(label.value)!r}")
        label.value = b"NEW"

        document.insert(opentlv.Tag(b"\x9f\x02"), b"\x00\x00\x00\x00\x01\x00")

        encoded = document.encode()
        print(f"encoded {len(encoded)} bytes: {encoded.hex(' ').upper()}")

        # The change round-trips through a fresh parse.
        reread = opentlv.Document(encoded, opentlv.Format.BER)
        assert bytes(reread.first.find(opentlv.Tag(b"\x50")).value) == b"NEW"
        assert reread.find(opentlv.Tag(b"\x9f\x02")) is not None
        reread.close()


if __name__ == "__main__":
    main()
