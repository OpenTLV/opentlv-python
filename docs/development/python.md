# Python development

## Build

The repository contains two distributions with unchanged import names and API:

| Build path | Distribution | Import |
| --- | --- | --- |
| Repository root | `opentlv-core` | `_opentlv` |
| `bindings/python/opentlv` | `opentlv` | `opentlv` |

Use Python 3.11+, a C99 compiler, Git and CMake 3.26+. The native build uses
scikit-build-core and CPython's Limited API (`Py_LIMITED_API=0x030B0000`).
The wheel is tagged `cp311-abi3`; Core is static and uses PIC for shared-module
linking. Windows uses the dynamic MSVC runtime. Hatchling builds the public
package. The Python implementation and native API are unchanged by #2.

```sh
python -m pip install . ./bindings/python/opentlv
```

The old `pip install ./bindings/python/opentlv-core` entry point belonged to
the Core monorepo. Its package metadata now lives at the repository root so
the sdist contains its CMake files, resolver, native sources and common adapters.
Only the Python install component enters the wheel: no Core headers, archives,
or build tools are installed as Python package payload.

To build both wheels and test native sdist rebuilding:

```sh
python -m pip install build pytest
python -m build --sdist --outdir build/dist .
python -m pip wheel --no-deps build/dist/opentlv_core-0.1.0.tar.gz -w build/wheels
python -m pip wheel --no-deps ./bindings/python/opentlv -w build/wheels
```

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

Use an isolated virtual environment and install both wheels before checking them:

```sh
python -m pip install pytest
python -m pip install . --config-settings=build-dir=build/native
python -m pip install ./bindings/python/opentlv
python -B -m pytest -p no:cacheprovider -q tests/build
python -B scripts/check_python.py --selection build/native/core-selection.json
```

`check_python.py` checks installed build evidence, linked Core version and all
existing format flags, runs the original pytest suite and eight examples, then
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

Both Python distribution versions remain `0.1.0`.
`opentlv.__version__` continues to report the linked Core version, currently
`0.7.1` for the locked dependency. No Python API or version semantic is changed.

Python owns its extension, facade, tests, examples and two native adapters.
Core owns shared Query semantics and the diagnostic vocabulary generator.
Diagnostic generated outputs remain unchanged; generator ownership and package
publication are not moved by this build integration.

The workflow under `docs/migration/original-python.yml` is historical evidence.
Standalone PR/Main/Full workflows are documented in
[quality gates](../quality-gates.md). They validate installed distributions and
retain the original tests. Source integration #2 did not establish hosted CI
coverage; #3's [validation record](../validation/ci.md) distinguishes local checks
from the hosted runs still needed for acceptance. Publication remains separate.
