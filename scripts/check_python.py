# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Run the existing Python suite, full-feature check, examples and selected Core corpus."""

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

# Allow the CI runner to use Python isolated mode without inheriting PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_support import ROOT, read, require, run, write
from core_dependency import git_identity
from ci_contract import junit_counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--junit", type=Path)
    args = parser.parse_args()
    if args.output:
        args.output.unlink(missing_ok=True)
    selected = read(args.selection)
    import _opentlv
    import opentlv
    installed = read(Path(_opentlv.__file__).with_name("_opentlv_core_dependency.json"))
    require(installed == selected, "Installed wheel differs from selected build evidence")
    require(opentlv.__version__ == selected["version"], "Loaded Core version differs from selection")
    for name in ("BER", "CER", "DER", "EMV", "NFC", "LLDP"):
        require(getattr(_opentlv, "HAS_" + name), "Official wheel is missing " + name)
    print(json.dumps({"extension": _opentlv.__file__, "package": opentlv.__file__,
                      "core": selected}, indent=2), flush=True)
    # Installed wheels must be exercised, not a source-tree package or PYTHONPATH.
    for module in (_opentlv, opentlv):
        require(Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()),
                "Module was not imported from the validation environment")
    items = list(opentlv.Reader(bytes.fromhex("02012a")))
    require(len(items) == 1 and bytes(items[0].value) == b"\x2a", "Public Reader smoke failed")
    result = {"smoke": True}
    if args.smoke:
        if args.output:
            write(args.output, result)
        return
    pytest_args = [] if args.junit is None else ["--junitxml=" + str(args.junit.resolve())]
    run(sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", "-q",
        *pytest_args, ROOT / "bindings/python/opentlv/tests")
    if args.junit:
        result["tests"] = junit_counts(args.junit)
    examples = sorted((ROOT / "bindings/python/opentlv/examples").glob("*.py"))
    for example in examples:
        run(sys.executable, "-B", example)
    result["examples"] = len(examples)
    source = Path(selected["source_path"])
    if selected["mode"] in ("pinned-git", "local-source"):
        identity = git_identity(source)
        require(identity["commit"] == selected["commit"], "Core corpus revision changed")
        require(selected["mode"] == "local-source" or not identity["dirty"], "Core corpus is modified")
    else:
        require((source / "opentlv-source.txt").read_text() ==
                f'version={selected["version"]}\ncommit={selected["commit"]}\n',
                "Core corpus archive identity differs")
    # Keep the imported facade and Core's shared semantic fixtures unchanged.
    with tempfile.TemporaryDirectory(prefix="opentlv-query-") as temporary:
        work = Path(temporary)
        for name in ("reference.py", "corpus.json"):
            shutil.copyfile(source / "tests/query" / name, work / name)
        shutil.copyfile(ROOT / "tests/query/python_facade.py", work / "python_facade.py")
        output = run(sys.executable, "-B", work / "python_facade.py", cwd=work, capture=True)
        print(output)
        match = re.fullmatch(r"Python public Query facade: (\d+) common fixtures, "
                             r"(\d+) optimized/backend checks passed", output.strip())
        require(match is not None, "Missing Query facade summary")
        result["query"] = {"fixtures": int(match[1]), "checks": int(match[2])}
    if args.output:
        write(args.output, result)


if __name__ == "__main__":
    main()
