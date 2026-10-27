# Contributing to opentlv-python

This repository owns the Python package, native extension, adapters, tests,
examples and packaging. Shared C behavior belongs to
[OpenTLV Core](https://github.com/OpenTLV/opentlv); documentation portal
navigation belongs to [opentlv-docs](https://github.com/OpenTLV/opentlv-docs).

This guide adds Python-specific build, test and licensing rules to the shared
[OpenTLV contribution guidelines](https://github.com/OpenTLV/.github/blob/main/CONTRIBUTING.md).
All project spaces follow the
[Code of Conduct](https://github.com/OpenTLV/.github/blob/main/CODE_OF_CONDUCT.md).
Report suspected vulnerabilities privately through this repository's Security
tab as described in the
[security policy](https://github.com/OpenTLV/.github/blob/main/SECURITY.md),
not in public issues. The [support directory](https://github.com/OpenTLV/.github/blob/main/SUPPORT.md)
lists the owning repository for each component.

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

## License and provenance

opentlv-python is MIT licensed. Marek Cingel holds copyright in his original
contributions, including the bindings migrated from Core; other contributors
retain copyright in theirs, since an MIT contribution does not assign copyright.
OpenTLV is a GitHub organization, not a copyright holder. Preserve existing
notices. Original source files by Marek Cingel start with:

```python
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
```

C sources and headers use `//`, CMake files `#`. Keep a shebang or Python
encoding declaration on the first lines, before the notice, and use your own
name and year for your own work. Do not apply this example to someone else's
work or rewrite third-party notices. Do not rewrite the frozen migrated tests,
examples or migration evidence to change their notices; their hashes are checked.

[REUSE.toml](REUSE.toml) lists documentation, configuration and migration
evidence that carry their metadata outside the file. Keep its paths explicit so
new sources cannot silently bypass the header policy. For new files that cannot
carry comments, add an explicit entry or a `.license` sidecar with the file's
actual license and owner. `LICENSES/` supplies the license texts referenced by
SPDX metadata. `scripts/check_quality.py` runs `reuse lint` with the pinned
REUSE 6.2.0; passing it checks metadata completeness, not legal provenance.

Both wheels and sdists carry `LICENSE`, declared as `license-files` in each
`pyproject.toml`. Hatchling cannot package files outside `src/`, so
`src/LICENSE` is a copy that the package policy requires to match `LICENSE`.
The native wheel links Core statically and installs Core's license from the
selected Core source as `.dist-info/licenses/OpenTLV/LICENSE`. Add the license
of every new bundled or linked dependency to the native wheel the same way, and
extend `scripts/package_contract.py` to require it.
