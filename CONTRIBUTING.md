# Contributing to opentlv-python

This repository owns the Python package, native extension, adapters, tests,
examples and packaging. Shared C behavior belongs to
[OpenTLV Core](https://github.com/OpenTLV/opentlv); documentation portal
navigation belongs to [opentlv-docs](https://github.com/OpenTLV/opentlv-docs).

Use Python 3.11+ and an activated virtual environment. From the repository root:

```sh
python -m pip install -r requirements-dev.txt
python -m pip install . --config-settings=build-dir=build/native
python -m pip install ./src
python -B -m pytest -p no:cacheprovider -q tests/build tests/ci
python -B scripts/check_python.py --selection build/native/core-selection.json
```

Edit public Python code in `src/opentlv`, native implementation in `native/src`
and Python-owned C adapters in `native/common`. Keep API tests in `tests/python`
and runnable examples in `examples`; neither belongs in installed packages.
Build and validation tools remain in `scripts`.

The root `pyproject.toml` builds `opentlv-core`; `src/pyproject.toml` builds
`opentlv`. Preserve both distribution names, imports and matching versions.
See [versioning](docs/versioning.md) before changing package metadata.

Run [source quality checks](docs/quality-gates.md) for affected code. Pull requests
use the existing fast PR gate; Full CI remains the release quality gate and is
not required for ordinary PR merge. See [development](docs/development/python.md)
for standalone and workspace Core selection, source-distribution builds and
installed-package validation. Use a fresh native build directory after moving
sources or changing the Core selection.

Report reproducible problems in the
[Python issue tracker](https://github.com/OpenTLV/opentlv-python/issues), including
Python version, operating system and installed `_opentlv_core_dependency.json`.
Document user-facing changes under `Unreleased` in `CHANGELOG.md`.
