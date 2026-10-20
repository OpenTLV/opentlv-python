# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Run the existing Python suite, full-feature check, examples and selected Core corpus."""

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

from build_support import ROOT, read, require, run
from core_dependency import git_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    args = parser.parse_args()
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
    run(sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", "-q",
        ROOT / "bindings/python/opentlv/tests")
    for example in sorted((ROOT / "bindings/python/opentlv/examples").glob("*.py")):
        run(sys.executable, "-B", example)
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
        run(sys.executable, "-B", work / "python_facade.py", cwd=work)


if __name__ == "__main__":
    main()
