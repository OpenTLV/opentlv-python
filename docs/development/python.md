# Python development

## Build

Run these commands from the root of
[opentlv-python](https://github.com/OpenTLV/opentlv-python), in an activated
virtual environment. Core remains the source of truth for shared architecture
and TLV semantics; this repository owns Python implementation and development.

The repository builds one distribution, `opentlv`, with unchanged import names
and API. Its source modules stay separate:

| Source | Import | Installed at |
| --- | --- | --- |
| `native/` (CMake target `_opentlv`) | `_opentlv` | Wheel root, with `_opentlv_core_dependency.json` |
| `src/opentlv/` | `opentlv` | `opentlv/` |

Use Python 3.11+, a C99 compiler, Git and CMake 3.26+. The root
`pyproject.toml` is the only build entry point: scikit-build-core builds the
native module with CPython's Limited API (`Py_LIMITED_API=0x030B0000`) and
copies `src/opentlv` beside it (`wheel.packages`). Each wheel is tagged
`cp311-abi3-<platform>`; Core is static and uses PIC for shared-module linking.
Windows uses the dynamic MSVC runtime.

```sh
python -m pip install .
```

The sdist contains the CMake files, resolver, `native/src` sources,
`native/common` adapters and `src/opentlv`, so it rebuilds the complete package.
Tests live in `tests/python` and examples in `examples`, outside the installed
package. Run examples from the repository root. Only the Python install component
and `src/opentlv` enter the wheel: no Core headers, archives, or build tools are
installed as Python package payload. The distribution declares
`License-Expression: MIT` and carries `LICENSE` as its `License-File`. Because
Core is linked statically, the wheel also carries Core's license as
`.dist-info/licenses/OpenTLV/LICENSE`. There is no `opentlv-core` distribution
and no dependency on one.

To build the sdist and rebuild the wheel from it:

```sh
python -m pip install build pytest
python -m build --sdist --outdir build/dist .
python -m pip wheel --no-deps build/dist/opentlv-0.1.0.tar.gz -w build/wheels
```

## Portable wheels

`wheel_platforms` in `cmake/python-package.json` declares one platform tag per
CI system. CI repairs the built wheel to that tag and audits its shared-library
dependencies:

| System | Tag | Tool |
| --- | --- | --- |
| Linux x86-64 | `manylinux_2_28_x86_64` | `auditwheel repair --only-plat` |
| macOS arm64 | `macosx_11_0_arm64` | `delocate-wheel --require-archs arm64 --require-target-macos-version 11.0` |
| Windows x64 | `win_amd64` | `delvewheel repair` |

`MACOSX_DEPLOYMENT_TARGET` is set from the tag, so Core, which is compiled in
the same build, has the same target. A wheel that needs newer glibc symbols, a
newer macOS or another architecture fails the repair. The package checks reject
any library a tool would bundle (`opentlv.libs/`, `opentlv/.dylibs/`): Core stays
statically linked, and the extension depends only on the C runtime and Python.
On Linux and macOS the module is always `_opentlv.abi3.so`: CMake would take
the platform-qualified stable-ABI suffix that CPython 3.15 reports
(`.abi3-x86_64-linux-gnu.so`), which CPython 3.11–3.14 cannot import, so the build
sets the suffix explicitly and the package checks require it.
The repaired bytes are the ones installed and tested. `twine check --strict`
validates the metadata and README of every wheel and sdist.

Builds are not bit-for-bit reproducible: each Full configuration produces its own
bytes for the same filename. Full CI therefore selects the upload set explicitly
and tests those exact files on every configuration, as described in
[upload set verification](../quality-gates.md#upload-set-verification) and
[release preparation](../releases.md).

## Core selection

`cmake/core-artifact.json` is the sole dependency lock. It records the repository,
full commit SHA, Core version, optional release tag, and verified-source fallback
policy. Selection happens before executing dependency CMake code:

1. An explicit `OPENTLV_PYTHON_CORE_SOURCE` selects a local Git checkout for
   development. Its actual version, commit and dirty state are recorded.
   `CI`, `GITHUB_ACTIONS`, or `OPENTLV_PYTHON_REQUIRE_VERIFIED_CORE=ON` prohibit
   this override.
2. A non-null release tag selects authenticated Core schema-2 release artifacts.
   The tag must resolve to the locked commit and agree with the locked version.
3. With a null release tag, clone and check out the exact locked Git commit.
   Reject a missing revision, wrong version, or modified cached checkout.
   `OPENTLV_PYTHON_REQUIRE_VERIFIED_CORE=ON` rejects this mode.

There is no implicit sibling discovery or arbitrary installed-package fallback.
`CMAKE_PREFIX_PATH` cannot replace the selected dependency. Changes to the lock
require a fresh build directory; an old cached source at a different revision
fails rather than silently changing its identity.

```sh
cmake -S . -B build/local \
  -DOPENTLV_PYTHON_CORE_SOURCE=/absolute/path/to/opentlv
cmake --build build/local --config Release --target _opentlv
```

For pip, pass the same setting as
`--config-settings=cmake.define.OPENTLV_PYTHON_CORE_SOURCE=/absolute/path/to/opentlv`.
Use an absolute path, since build frontends may change the working directory.
Development overrides are not official release evidence.

## Local workspace development

In [opentlv-workspace](https://github.com/OpenTLV/opentlv-workspace), Core and
Python are sibling checkouts. From `opentlv-python`, explicitly select Core:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
$coreSource = (Resolve-Path ../opentlv).Path
python -m pip install . "--config-settings=cmake.define.OPENTLV_PYTHON_CORE_SOURCE=$coreSource"
```

On POSIX shells:

```sh
python3 -m venv .venv
. .venv/bin/activate
core_source=$(cd ../opentlv && pwd)
python -m pip install . --config-settings="cmake.define.OPENTLV_PYTHON_CORE_SOURCE=$core_source"
```

Rebuild and reinstall the distribution after changing Core or the Python sources. Without
this override, the standalone build uses its dependency lock even when a
sibling Core exists. The override is for local development and is rejected
in CI; use the pinned build for CI validation.

## Supported Python versions

The distribution requires Python 3.11 or newer. The native extension targets
CPython's 3.11 stable ABI (`cp311-abi3`); the configured Full CI matrix covers
CPython 3.11 through 3.15 on Linux, Windows and macOS. Matrix configuration is
not a claim that every hosted run has passed. See the
[quality gates](../quality-gates.md) and [validation record](../validation/ci.md)
for scope and evidence. PyPy and free-threaded builds are not in that matrix.

## Contributing and reporting issues

Report Python API, packaging, installation and binding test problems in the
[Python issue tracker](https://github.com/OpenTLV/opentlv-python/issues), and
submit Python changes to [opentlv-python](https://github.com/OpenTLV/opentlv-python).
Include the Python version, operating system, reproduction and installed
`_opentlv_core_dependency.json` metadata when reporting build problems.
Report suspected vulnerabilities privately as described in the shared
[security policy](https://github.com/OpenTLV/.github/blob/main/SECURITY.md),
not in public issues.
Run the [installed-package validation](#validation) and the relevant
[quality checks](../quality-gates.md) before submitting a change.

Shared C behavior and architecture belong to
[Core](https://github.com/OpenTLV/opentlv); report those problems in the
[Core issue tracker](https://github.com/OpenTLV/opentlv/issues).
Portal navigation and presentation belong to
[opentlv-docs](https://github.com/OpenTLV/opentlv-docs/issues).

## Full configuration and public Core interface

`cmake/core-features.json` lists all 17 required capabilities and formats.
Source builds force these requirements on using internal CMake cache entries;
command-line `OFF` values cannot create an official feature variant.
The embedded Core's own bindings, tests, examples and other auxiliary builds
are disabled. This avoids recursive Python builds and duplicate targets.

The extension links only `OpenTLV::tlv`. Both source and binary selections are
checked against the public generated `tlv/config.h` and `tlv/version.h` exposed
by that target. Missing, disabled or duplicate requirements, non-static targets,
and mismatched version/commit headers stop configuration. Installed package
capabilities are never inferred from the consumer's CMake options.

All existing Python format providers are compiled. The full-Core requirement
does not introduce new Python wrappers or change existing Python behavior.
The previous reduced-build documentation is historical.

## Verified release artifacts

The resolver follows the CLI/Lua external-consumer policy and Core's schema-2
release contract. It uses `gh release download` and `gh attestation verify`
with the repository, `core-release.yml` signer workflow and exact source digest.
It authenticates the manifest, checksum list and every consumed artifact.
Manifest version, commit, repository, Full CI status, run and attempt must agree.
Every required Full CI check must pass; workflow definitions and configuration
hashes are compared with the matching authenticated source archive.
Archive extraction rejects traversal, unsafe links and unsupported members.

Binary compatibility requires the actual consumer compiler ID/version,
operating system, x64 target, pointer width, static linkage, Release configuration,
runtime/libc compatibility and every required Core feature. Linux static binaries
must explicitly attest PIC; it is never inferred from architecture. Unsupported
platforms, cross compilation and multi-config generators use verified source
when permitted. The official wheel remains statically linked.

A bad signature, wrong identity or checksum is an error, not a reason to fall
back to unverified Git. Only absence of a compatible binary permits the locked
verified-source fallback. Binary builds also obtain the matching authenticated
source archive for the Core-owned Query corpus.

The current lock has no release tag. Local tests exercise verification success
and rejection with fixtures; they do not establish availability or acceptance
of a real attested Core release. Publication and release automation are outside #2.

## Validation

Use an isolated virtual environment and install the wheel before checking it:

```sh
python -m pip install pytest
python -m pip install . --config-settings=build-dir=build/native
python -B -m pytest -p no:cacheprovider -q tests/build
python -B scripts/check_python.py --selection build/native/core-selection.json
```

`check_python.py` checks installed build evidence, that `_opentlv` and `opentlv`
both belong to the installed `opentlv` distribution and that no `opentlv-core`
is installed, the Python binding version and all existing format flags, runs the
original pytest suite and fourteen examples, then
runs the unchanged Query facade against the selected Core corpus/reference.
The corpus is staged in a temporary directory; Core-owned test files are not
copied into this repository. Keep the selected Core source available for this step.

Dependency tests cover rejected identities, dirty pinned sources, CI overrides,
artifact authentication/checksums, compatibility, extraction and the public CMake
target contract. The migration inventory and initial runtime evidence remain
frozen; see [migration history](../migration.md).

See [standalone validation](../validation/standalone-build.md) for completed local
checks, source selections and limitations.

## Versioning and ownership

The Python distribution version is `0.1.0`. `opentlv.__version__` and
`_opentlv.version_string()` report that Python binding version, generated from
`cmake/python-package.json` during configuration. Core `0.8.0` is in the
dependency lock and installed dependency metadata; it no longer supplies the
public Python version string. See [versioning](../versioning.md) and
[release preparation](../releases.md).

Python owns its extension, facade, tests, examples and two native adapters.
Core owns shared Query semantics and the diagnostic vocabulary generator.
Diagnostic generated outputs remain unchanged; generator ownership and package
publication are not moved by this build integration.

The workflow under `docs/migration/original-python.yml` is historical evidence.
Standalone PR/Main/Full workflows are documented in
[quality gates](../quality-gates.md). They validate the installed distribution and
retain the original tests. Source integration #2 did not establish hosted CI
coverage; #3's [validation record](../validation/ci.md) distinguishes local checks
from the hosted runs still needed for acceptance. Publication remains separate.
