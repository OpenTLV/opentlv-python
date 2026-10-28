# opentlv-python

Python bindings for [OpenTLV](https://github.com/OpenTLV/opentlv), a library
for parsing, encoding, and working with TLV and TLV-like binary formats.

## Install from source

Requires Python 3.11+, a C99 compiler, CMake 3.26+ (the Python build backend
can supply CMake) and an authenticated [GitHub CLI](https://cli.github.com/)
with `gh attestation verify`, which downloads and verifies the locked Core
release. Use a virtual environment:

```sh
python -m venv .venv
# Activate the virtual environment for your shell.
python -m pip install . ./src
```

The repository root builds the native `opentlv-core` distribution (`_opentlv`
import). `src` builds the public `opentlv` package.
Both package versions are `0.1.0`; `opentlv.__version__` and
`_opentlv.version_string()` report this Python binding version. The public
package requires exactly the matching native package version. Python releases
are independent of Core. See [versioning](docs/versioning.md).

The default build obtains the exact Core release locked in
[`cmake/core-artifact.json`](cmake/core-artifact.json). It needs no sibling
checkout and works from the native package's sdist. Core is linked statically
into a `cp311-abi3` extension. Every required Core capability and format is
enabled; there are no supported reduced-feature Python packages.

For local Core development, use an explicit absolute checkout path:

```sh
python -m pip install . \
  --config-settings=cmake.define.OPENTLV_PYTHON_CORE_SOURCE=/absolute/path/to/opentlv
python -m pip install ./src
```

On Windows use a path such as `D:/Projects/OpenTLV/opentlv`.
The override is rejected when `CI` or `GITHUB_ACTIONS` is enabled, or when
attested Core is required. Local revisions and dirty state are recorded.

## Dependency assurance

The lock selects the Core release `v0.8.0` at
`345c77acb29266036df5f27d04ce315bb61853cc`, so every default build consumes
its authenticated schema-2 release artifacts. The resolver prefers a
compatible static binary and checks its SHA-256, GitHub Artifact Attestation,
signer workflow, source commit, and release evidence before consumption.
It uses the matching verified source artifact when no compatible binary exists
and the lock permits source fallback. Verification failures stop the build
and never fall back to Git. The build then checks the public headers, version,
commit and required features.

To require that release path explicitly:

```sh
python -m pip install . \
  --config-settings=cmake.define.OPENTLV_PYTHON_REQUIRE_VERIFIED_CORE=ON
```

This rejects the local Core override and a lock without a release tag. A pinned
Git build is reproducible source selection, not evidence of an attested release.
See [build and verification details](docs/development/python.md).

## Layout and validation

| Path | Content |
| --- | --- |
| `pyproject.toml`, `CMakeLists.txt`, `cmake/` | Standalone native build and Core policy |
| `native/src/` | Existing native extension implementation |
| `src/pyproject.toml`, `src/opentlv/` | Public `opentlv` distribution metadata and package sources |
| `tests/python/` | Existing Python API tests |
| `examples/` | Fourteen runnable examples, outside the installed package |
| `native/common/` | Two binding-owned native adapters |
| `scripts/check_python.py` | Installed-wheel, pytest, example and Query validation |
| `tests/build/` | Dependency verification and public Core target tests |
| `tests/ci/`, `.github/workflows/` | PR/Main/Full gates and evidence regressions |
| `docs/migration/` | Frozen source inventory and original migration evidence |

Build diagnostics are written to `core-selection.json` in the CMake build
directory and installed as `_opentlv_core_dependency.json` beside the extension.
They identify the actual dependency mode, version, commit and verification state.
See the [user guide](docs/guides/python.md) and
[migration record](docs/migration.md).

The initial migration remains reproducible at its historical import commit.
Its frozen inventory is not rewritten to conceal subsequent build changes.

The two build entry points preserve the existing distribution identities:
`python -m pip install . ./src` installs both packages. The facade's metadata
lives beside `src/opentlv` so its sdist is self-contained; the root native
sdist contains the CMake inputs, dependency resolver and `native/common` adapters.
Development tooling remains in `scripts/`. See [contributing](CONTRIBUTING.md)
and the [layout validation record](docs/validation/layout.md).

## Continuous integration

Successful Main builds notify the documentation portal when documentation
inputs change. See the [notification contract and token permissions](docs/quality-gates.md#documentation-portal-notifications).

Pull requests run the installed Python suite on Linux/CPython 3.11 and the
source quality checks. Pushes to `main` run a short build/import/API smoke.
Manual or reusable Full CI covers CPython 3.11–3.15 on Linux, Windows and macOS,
including wheel installation from both source distributions.

The stable `Python quality gate` checks all required results and attempt-scoped
build evidence. Core's own test suites remain disabled. Every tier consumes the
attested Core release; release callers also enable `require_verified_core`,
which rejects a lock without a release tag.
See [quality gates and local commands](docs/quality-gates.md) and
[local validation](docs/validation/ci.md).

CI retains the tested wheels and source distributions alongside their checksums
and build records. The manual [release preparation](docs/releases.md) runs
verified-Core Full CI and assembles an attested candidate with a manifest and
`SHA256SUMS`. Set `publish_release: true` to create the version tag and GitHub
Release with the versioned [release notes](docs/release-notes.md) after
verification and automatically notify the documentation portal. The default
remains candidate-only; PyPI publication is disabled. Release history is in the
[changelog](CHANGELOG.md).

## License

MIT; see [LICENSE](LICENSE). Marek Cingel holds copyright in his original
contributions, including the bindings migrated from Core; other contributors
and third parties retain theirs. SPDX/REUSE metadata covers every tracked file.
Both wheels and sdists include the license text, and the native `opentlv-core`
wheel also includes the license of the statically linked Core.

## Community

Contribution, conduct, security and support policies are shared across OpenTLV
in [OpenTLV/.github](https://github.com/OpenTLV/.github); the
[contributor guide](CONTRIBUTING.md) adds Python-specific instructions. Report
suspected vulnerabilities privately as described in the
[security policy](https://github.com/OpenTLV/.github/blob/main/SECURITY.md).
