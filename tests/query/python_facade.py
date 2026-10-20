# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Common corpus through the public Python compiled Query facade."""
import json
from pathlib import Path
from opentlv import QueryProgram, Document, TreeReader, NeedMoreDataError, OpenTLVError
from reference import tree


def scalar(value):
    if isinstance(value, bool):
        return f"bool:{int(value)}"
    if isinstance(value, int):
        return f"int:{value}"
    if isinstance(value, str):
        return "string:" + value.encode().hex()
    return "bytes:" + value.hex()


def main():
    cases = json.loads(Path(__file__).with_name("corpus.json").read_text())["cases"]
    checks = 0
    for case in cases:
        wire = bytes.fromhex(case["wire"])
        for optimize in (True, False):
            try:
                program = QueryProgram(case["query"], optimize=optimize,
                    names={"fixture:leaf": b"\x5a", "fixture:container": b"\x70"})
            except OpenTLVError as error:
                assert "diagnostic" in case, (case["id"], error)
                expected = case["diagnostic"]
                assert (error.code, error.query["query_kind"]) == (expected["code"], expected["kind"]), case["id"]
                if "begin" in expected:
                    # The expression span is primary, or related evidence beside another location.
                    span = error.location if error.location.domain == "expression" else error.query["expression"]
                    assert (span.begin, span.end) == (expected["begin"], expected["end"]), case["id"]
                checks += 1
                continue
            assert "diagnostic" not in case, case["id"]
            expected = case["matches"]
            if program.info["level"] != 3:
                actual = program.evaluate(wire, max_work=100000000)
                result = [match.offset for match in actual] if isinstance(actual, list) else scalar(actual)
                assert result == expected, (case["id"], "Reader", result, expected)
                checks += 1
            document = Document(wire, retain_source_locations=True)
            execution = program.execution(max_work=100000000)
            execution.evaluate_document(document)
            if program.info["result_kind"]:
                result = scalar(execution.result())
            else:
                # Source offsets belong to the fixture, not to native Nodes.
                # Map public checked handle identities to independent preorder.
                _, reference_nodes = tree(wire)
                offsets = {}
                stack = []
                node = document.first
                while node is not None:
                    offsets[node.identity] = reference_nodes[len(offsets)]["offset"]
                    if node.next is not None:
                        stack.append(node.next)
                    node = node.first_child
                    if node is None and stack:
                        node = stack.pop()
                result = [offsets[node.identity] for node in execution]
            assert result == expected, (case["id"], "Document", result, expected)
            checks += 1
            document.close()
    print(f"Python public Query facade: {len(cases)} common fixtures, {checks} optimized/backend checks passed")


if __name__ == "__main__":
    main()
