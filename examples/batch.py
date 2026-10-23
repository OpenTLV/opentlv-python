# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Validates and queries a batch of messages with work done once up front:
a structural schema checked once and a Query program compiled once.

Each message is checked against the prepared schema without repeating the
definition check, then one reusable execution evaluates the program over it
and is reset in place for the next message. A path query also visits the
raw buffer directly, and the Document view visits the same matches as nodes.

Run with `python examples/batch.py` from the repository root, after
installing both packages.
"""

import opentlv
from opentlv.codec import NumberCodec


def main() -> None:
    # 6F (FCI template) holds one 84 (DF name) and an optional A5 with 9F02 amounts.
    proprietary = opentlv.StructureSchema([
        opentlv.StructureRule(b"\x9f\x02", min_occurs=1, max_occurs=4, min_length=2,
                              max_length=2)])
    schema = opentlv.StructureSchema([opentlv.StructureRule(b"\x6f", min_occurs=1, max_occurs=1,
        children=opentlv.StructureSchema([
            opentlv.StructureRule(b"\x84", min_occurs=1, max_occurs=1, max_length=16),
            opentlv.StructureRule(b"\xa5", max_occurs=1, children=proprietary)]))]).check()

    # Amounts are 2-byte big-endian numbers, decoded by the native codec provider.
    total = opentlv.QueryProgram(
        "count(//9F02[num(.) >= $minimum])", variables={"minimum": int},
        providers={"num": opentlv.QueryCodecProvider(1001, NumberCodec(width=2))})
    print(total.format(), f"({total.plan_info['instructions']} instructions)")
    execution = total.execution()

    messages = [
        bytes.fromhex("6f118403414243a50a9f0202012c9f020200c8"),
        bytes.fromhex("6f058403444546"),
        bytes.fromhex("6f0b8403474849a5049f020101"),  # amount too short
        bytes.fromhex("6f07a5059f0202012c"),  # DF name missing
    ]
    for index, message in enumerate(messages):
        try:
            schema.validate(message)
        except opentlv.SchemaError as error:
            print(f"message {index}: rejected, {error.kind} at offset {error.offset}")
            continue
        execution.reset()
        execution.bind("minimum", 250)
        execution.visit(opentlv.TreeReader(message), lambda match: None)
        print(f"message {index}: valid, {execution.result()} amount(s) of at least 250")

    path = opentlv.Query("6f/a5/9f02")
    amounts = []
    path.visit_buffer(messages[0], lambda element, depth, offset: amounts.append(
        int.from_bytes(element.value, "big")))
    print(f"{path}: {amounts}")
    with opentlv.Document(messages[0]) as document:
        document.visit(path, lambda node: print(f"  node {node.tag} = {node.value.hex()}"))


if __name__ == "__main__":
    main()
