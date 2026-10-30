# opentlv-python

Python bindings for [OpenTLV](https://github.com/OpenTLV/opentlv), a library
for parsing, encoding, and working with TLV and TLV-like binary formats.

## Distribution

One distribution, `opentlv`, installs both layers: the native `_opentlv`
extension and the public `opentlv` package. It has no dependencies; there is no
separate `opentlv-core` package. Each wheel is a `cp311-abi3` wheel for
CPython 3.11 and newer, tagged `manylinux_2_28_x86_64` (Linux x86-64),
`macosx_11_0_arm64` (macOS arm64) or `win_amd64` (Windows x64). Core is linked
statically, and the extension depends only on the C runtime and Python.
It is not on PyPI yet; install from source.

## Install from source

Requires Python 3.11+, a C99 compiler, CMake 3.26+ (the Python build backend
can supply CMake) and an authenticated [GitHub CLI](https://cli.github.com/)
with `gh attestation verify`, which downloads and verifies the locked Core
release. Use a virtual environment:

```sh
python -m venv .venv
# Activate the virtual environment for your shell.
python -m pip install .
```

The package version is `0.1.0`; `opentlv.__version__` and
`_opentlv.version_string()` report this Python binding version. Python
releases are independent of Core. See [versioning](https://github.com/OpenTLV/opentlv-python/blob/main/docs/versioning.md).

The default build obtains the exact Core release locked in
[`cmake/core-artifact.json`](https://github.com/OpenTLV/opentlv-python/blob/main/cmake/core-artifact.json). It needs no sibling
checkout and works from the sdist. Every required Core capability and format is
enabled; there are no supported reduced-feature Python packages.

For local Core development, use an explicit absolute checkout path:

```sh
python -m pip install . \
  --config-settings=cmake.define.OPENTLV_PYTHON_CORE_SOURCE=/absolute/path/to/opentlv
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
See [build and verification details](https://github.com/OpenTLV/opentlv-python/blob/main/docs/development/python.md).

## Layout and validation

| Path | Content |
| --- | --- |
| `pyproject.toml` | The only build entry point: `opentlv` distribution metadata |
| `CMakeLists.txt`, `cmake/` | Native build, Core policy and wheel platform policy |
| `native/src/` | Existing native extension implementation (`_opentlv`) |
| `src/opentlv/` | Public `opentlv` package sources |
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
See the [user guide](https://github.com/OpenTLV/opentlv-python/blob/main/docs/guides/python.md) and
[migration record](https://github.com/OpenTLV/opentlv-python/blob/main/docs/migration.md).

The initial migration remains reproducible at its historical import commit.
Its frozen inventory is not rewritten to conceal subsequent build changes.

The native and public sources stay separate, but one build packages them:
`python -m pip install .` installs both. The sdist contains the CMake inputs,
dependency resolver, `native/common` adapters and `src/opentlv`, so it rebuilds
the complete package. Development tooling remains in `scripts/`. See
[contributing](https://github.com/OpenTLV/opentlv-python/blob/main/CONTRIBUTING.md) and the
[layout validation record](https://github.com/OpenTLV/opentlv-python/blob/main/docs/validation/layout.md).

## Continuous integration

Successful Main builds notify the documentation portal when documentation
inputs change. See the [notification contract and token permissions](https://github.com/OpenTLV/opentlv-python/blob/main/docs/quality-gates.md#documentation-portal-notifications).

Pull requests run the installed Python suite on Linux/CPython 3.11 and the
source quality checks. Pushes to `main` run a short build/import/API smoke.
Manual or reusable Full CI covers CPython 3.11–3.15 on Linux, Windows and macOS,
including wheel installation from the source distribution. Every tier repairs
the wheel to its portable tag, rejects bundled external libraries and runs
`twine check --strict` before installing exactly those bytes. Full then selects
one wheel per platform and the sdist, and every configuration installs its
platform's selected wheel by name and runs the installed suite on it.

The stable `Python quality gate` checks all required results and attempt-scoped
build evidence. Core's own test suites remain disabled. Every tier consumes the
attested Core release; release callers also enable `require_verified_core`,
which rejects a lock without a release tag.
See [quality gates and local commands](https://github.com/OpenTLV/opentlv-python/blob/main/docs/quality-gates.md) and
[local validation](https://github.com/OpenTLV/opentlv-python/blob/main/docs/validation/ci.md).

CI retains the tested wheels and source distributions alongside their checksums
and build records. The manual [release preparation](https://github.com/OpenTLV/opentlv-python/blob/main/docs/releases.md) runs
verified-Core Full CI and assembles an attested candidate with a manifest,
`SHA256SUMS` and a unique upload set of one wheel per platform and one sdist
for the requested `tag` input, such as `v0.1.0`, which must match
the package version, changelog and release notes. Set `publish_release: true`
to create that tag and the GitHub Release with the versioned
[release notes](https://github.com/OpenTLV/opentlv-python/blob/main/docs/release-notes.md) after verification and automatically
notify the documentation portal. The default
remains candidate-only. With `pypi: testpypi`, the run stages the verified files
on TestPyPI and installs them from there on every configuration. A later
dispatch with `pypi: pypi` and that run's ID in `candidate_run` promotes the same
bytes, without a rebuild, to a GitHub Release and PyPI. Both upload through
Trusted Publishing in a protected environment, without stored tokens. Release history is in the
[changelog](https://github.com/OpenTLV/opentlv-python/blob/main/CHANGELOG.md).

## License

MIT; see [LICENSE](https://github.com/OpenTLV/opentlv-python/blob/main/LICENSE). Marek Cingel holds copyright in his original
contributions, including the bindings migrated from Core; other contributors
and third parties retain theirs. SPDX/REUSE metadata covers every tracked file.
Wheels and sdists include the license text, and wheels also include the license
of the statically linked Core.

## Community

Contribution, conduct, security and support policies are shared across OpenTLV
in [OpenTLV/.github](https://github.com/OpenTLV/.github); the
[contributor guide](https://github.com/OpenTLV/opentlv-python/blob/main/CONTRIBUTING.md) adds Python-specific instructions. Report
suspected vulnerabilities privately as described in the
[security policy](https://github.com/OpenTLV/.github/blob/main/SECURITY.md).
