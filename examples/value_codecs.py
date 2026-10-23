# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Decodes element Values with opentlv's generic codecs: packed digits, ASCII
text and an IPv4 address list, each through a public OpenTLV C codec selected
explicitly rather than by tag; see docs/guides/python.md#codec.

Run with `python examples/value_codecs.py` from the repository root, after
installing both packages.
"""

from ipaddress import IPv4Address

import opentlv
from opentlv import DigitsCodec, OpenTLVError, TextCodec, ValueCodec

MESSAGE = bytes.fromhex(
    "5a05123456789f"            # 5A: digits 123456789, F-padded
    "500456495341"              # 50: label "VISA"
    "8108c0000201c6336401")     # 81: two IPv4 addresses

CODECS = {
    "5A": DigitsCodec(),
    "50": TextCodec(),
    "81": ValueCodec.IPV4_LIST,
}


def main() -> None:
    values = {}
    for element in opentlv.Reader(MESSAGE, opentlv.Format.BER):
        tag = str(element.tag)
        values[tag] = CODECS[tag].decode(element.value)
        print(f"tag {tag}: {values[tag]!r}")
    assert values["5A"] == "123456789"
    assert values["50"] == "VISA"
    assert values["81"] == (IPv4Address("192.0.2.1"), IPv4Address("198.51.100.1"))

    assert DigitsCodec().encode(values["5A"]) == bytes.fromhex("123456789f")
    addresses = ValueCodec.IPV4_LIST.encode(["192.0.2.1", "198.51.100.1"])
    assert addresses == bytes.fromhex("c0000201c6336401")

    try:
        DigitsCodec().decode(b"\x1a")  # A is not a decimal digit
    except OpenTLVError as error:
        print(f"rejected: {error} ({error.codec_detail['reason_name']})")


if __name__ == "__main__":
    main()
