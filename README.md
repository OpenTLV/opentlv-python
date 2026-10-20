# opentlv-python

Python bindings for [OpenTLV](https://github.com/OpenTLV/opentlv), a library
for parsing, encoding, and working with TLV and TLV-like binary formats.

## Install from source

Requires Python 3.11+, Git, a C99 compiler, and CMake 3.26+ (the Python build
backend can supply CMake). Use a virtual environment:

```sh
python -m venv .venv
# Activate the virtual environment for your shell.
python -m pip install . ./bindings/python/opentlv
```

The repository root builds the native `opentlv-core` distribution (`_opentlv`
import). `bindings/python/opentlv` builds the public `opentlv` package.
Both package versions remain `0.1.0`; `opentlv.__version__` reports the linked
Core version. No package publication is part of this integration.

The default build obtains the exact Core commit and version in
[`cmake/core-artifact.json`](cmake/core-artifact.json). It needs no sibling
checkout and works from the native package's sdist. Core is linked statically
into a `cp311-abi3` extension. Every required Core capability and format is
enabled; there are no supported reduced-feature Python packages.

For local Core development, use an explicit absolute checkout path:

```sh
python -m pip install . \
  --config-settings=cmake.define.OPENTLV_PYTHON_CORE_SOURCE=/absolute/path/to/opentlv
python -m pip install ./bindings/python/opentlv
```

On Windows use a path such as `D:/Projects/OpenTLV/opentlv`.
The override is rejected when `CI` or `GITHUB_ACTIONS` is enabled, or when
attested Core is required. Local revisions and dirty state are recorded.

## Dependency assurance

The current lock selects Core `0.7.1` at
`5e0aae9c77e9c22d07c7f03d6110243e9ecad85f`. Its `release_tag` is null:
the default build verifies the Git revision, clean source tree, version,
public headers, and required features, but **does not claim release attestation**.

When an approved Core schema-2 release is locked, the resolver prefers a
compatible static binary and checks its SHA-256, GitHub Artifact Attestation,
signer workflow, source commit, and release evidence before consumption.
It uses the matching verified source artifact when no compatible binary exists
and the lock permits source fallback. Verification failures stop the build.
Release artifact resolution requires authenticated `gh` with attestation support.

To require that release path:

```sh
python -m pip install . \
  --config-settings=cmake.define.OPENTLV_PYTHON_REQUIRE_VERIFIED_CORE=ON
```

This intentionally fails with the current null release lock. A pinned Git
build is reproducible source selection, not evidence of an attested release.
See [build and verification details](docs/development/python.md).

## Layout and validation

| Path | Content |
| --- | --- |
| `pyproject.toml`, `CMakeLists.txt`, `cmake/` | Standalone native build and Core policy |
| `bindings/python/opentlv-core/src/` | Existing native extension implementation |
| `bindings/python/opentlv/` | Public package, 22 pytest modules and eight examples |
| `bindings/common/` | Two binding-owned native adapters |
| `scripts/check_python.py` | Installed-wheel, pytest, example and Query validation |
| `tests/build/` | Dependency verification and public Core target tests |
| `docs/migration/` | Frozen source inventory and original migration evidence |

Build diagnostics are written to `core-selection.json` in the CMake build
directory and installed as `_opentlv_core_dependency.json` beside the extension.
They identify the actual dependency mode, version, commit and verification state.
See the [user guide](docs/guides/python.md) and
[migration record](docs/migration.md).

The initial migration remains reproducible at its historical import commit.
Its frozen inventory is not rewritten to conceal subsequent build changes.
