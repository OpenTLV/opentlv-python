# Python source migration

This document records the historical #1 baseline. Standalone integration in
#2 subsequently changed build metadata and guides, while preserving the native
and Python implementation, existing tests, examples and frozen inventory.
Use the [current build guide](development/python.md) for installation.
To verify the original import without requiring today's working tree to match it:

```sh
python -B scripts/verify_migration.py --core ../opentlv \
  --import-ref e0e2ce1014bfa57a86d796a2e5c5b8935cfad49a
```

## Provenance

| Field | Value |
| --- | --- |
| Source repository | [OpenTLV/opentlv](https://github.com/OpenTLV/opentlv) |
| Source commit | `5e0aae9c77e9c22d07c7f03d6110243e9ecad85f` |
| Source directory | [`bindings/python/`](https://github.com/OpenTLV/opentlv/tree/5e0aae9c77e9c22d07c7f03d6110243e9ecad85f/bindings/python) |
| Destination | [OpenTLV/opentlv-python](https://github.com/OpenTLV/opentlv-python) |
| Migration issue | [opentlv-python#1](https://github.com/OpenTLV/opentlv-python/issues/1) |

The import copies committed Git blobs, preserving their bytes and original
copyright and SPDX notices. It does not transplant Git history into the
existing destination repository. The source commit and per-file mapping retain
traceability to the original history (`git log <commit> -- <source-path>`).

The baseline is the clean local Core `main` checkout at the recorded commit,
not the older Core revision in the workspace integration manifest. This source
provenance does not update that manifest or select a standalone release
dependency.

## Source inventory

The [inventory](migration/source-inventory.json) records all 77 imported files
with source paths, destination paths, and SHA-256 hashes:

| Source | Destination | Files |
| --- | --- | ---: |
| `bindings/python/opentlv-core/` | Same path | 21 |
| `bindings/python/opentlv/` | Same path | 50 |
| `bindings/common/path_query.h`, `query_schema.h` | Same paths | 2 |
| `tests/query/python_facade.py` | Same path | 1 |
| `docs/guides/python.md`, `docs/development/python.md` | Same paths | 2 |
| `.github/workflows/python.yml` | `docs/migration/original-python.yml` | 1 |

The complete 71-file Python subtree includes 22 pytest modules and eight
examples. Keeping the original directory layout preserves native relative
includes and avoids implementation or test rewrites. The two common headers
are binding adapters, not copies of Core's library implementation.

The workflow is historical evidence, not an active standalone workflow.
The original build files are retained even though their parent Core build
context is not present in this repository. Do not run the imported native
package's `pip install` command against this repository before standalone build
integration is implemented.

The verifier compares the inventory with the complete Git tree, checks each
file byte-for-byte against its original Git blob, and rejects missing, extra,
or modified Python files. Future build changes should be reviewed against
this frozen import inventory rather than updating its hashes to hide changes.

## Preserved contracts

- Distribution names `opentlv-core` and `opentlv`, imports `_opentlv` and
  `opentlv`, and both package versions (`0.1.0`) remain unchanged.
- Public names, signatures, exception handling, diagnostic mappings,
  ownership, cleanup, and native capsule behavior are unchanged.
- At the migration baseline, `opentlv.__version__` reports the linked Core
  version. Standalone packaging (#4) subsequently changes this to the Python
  binding version; see [versioning](versioning.md). Historical evidence below
  retains the original behavior.
- Optional-format availability and fixed-format behavior are unchanged.
- Existing tests and examples are copied without rewriting assertions.
- No Core sources, tests, generators, or CI workflows are removed or changed.

## Supported versions and configurations at the baseline

Both packages declare Python `>=3.11`. The native module uses CPython's
Limited API (`Py_LIMITED_API=0x030B0000`) and the `cp311` stable ABI wheel
setting. Its build requires CMake 3.26+ and a C99 compiler.

The original package build statically links Core and disables the C++ layer,
Core tests, Core examples, and warnings-as-errors. Core capabilities and
optional formats default to enabled. The existing native CMake file also
conditionally compiles BER, CER, DER, EMV, NFC, and LLDP adapters; the original
component-test instructions cover reduced builds using `test_components.py`.
This migration adds no supported Python version or build configuration.

The original CI config selects Python 3.11 on Ubuntu 24.04 for main pushes
and relevant pull requests, adding Windows and macOS on release tags.
It runs pytest, the shared Query corpus through the Python facade, and every
Python example. This describes the preserved workflow, not evidence that
all those platforms passed at the migration commit.

## Test and documentation ownership

| Area | Ownership and migration treatment |
| --- | --- |
| `bindings/python/opentlv/tests/` | Binding-owned tests; all 22 modules copied unchanged |
| `tests/query/python_facade.py` | Binding-owned adapter; copied unchanged |
| `tests/query/corpus.json`, `reference.py` | Core-owned shared semantics; consume from the exact Core baseline for migration verification |
| Other Core Query/property/format tests | Remain in Core; not imported |
| Diagnostic vocabulary generator | `scripts/generate_diagnostic_vocabulary.py` remains Core-owned |
| Generated `diagnostic.py` and its test | Existing generated outputs copied unchanged with the Python subtree |
| Python guides and examples | Imported unchanged; original Core-relative documentation context retained |

The Query adapter imports `reference.py` and reads its adjacent `corpus.json`.
It must be run in the matching Core test context until standalone integration
provides these dependencies explicitly. Do not silently substitute a newer
corpus or claim that an unexecuted adapter passed.

The diagnostic generator also emits other language bindings. Moving or
rewriting it would change shared ownership; a future integration must explicitly
define how this repository refreshes and validates its generated output.
No missing Core behavioral coverage was established by this migration.

For historical cross-links and original build instructions, use the pinned
[user guide](https://github.com/OpenTLV/opentlv/blob/5e0aae9c77e9c22d07c7f03d6110243e9ecad85f/docs/guides/python.md)
and
[developer guide](https://github.com/OpenTLV/opentlv/blob/5e0aae9c77e9c22d07c7f03d6110243e9ecad85f/docs/development/python.md).
Links into other Core documents in the imported guides are intentionally
preserved; those shared documents are not duplicated here.

## Recorded validation

Local validation on 2026-10-20 used Windows x64, CPython 3.11.4,
CMake 3.31.7, MSVC 19.44.35222.0, and a Release build with the package's
default enabled Core capabilities and formats. Dependencies were installed
into an isolated environment under `build/issue1-venv`; the global Python
environment was not changed.

The original Core test run completed before importing any binding files.
After import, both packages were rebuilt and force-reinstalled from the
overlaid Core archive. Installed distribution metadata confirmed both packages
came from that temporary tree.

| Check | Original Core baseline | Imported sources in Core context |
| --- | --- | --- |
| Native and Python wheel build/install | Passed | Passed |
| Existing pytest suite | 299 passed | 299 passed |
| Shared Query corpus | 171 fixtures, 664 checks passed | 171 fixtures, 664 checks passed |
| Existing examples | 8 passed | 8 passed |
| Linked Core version | `0.7.1` | `0.7.1` |
| BER, CER, DER, EMV, LLDP, NFC availability | All enabled | All enabled |

Query and example stdout matched exactly across the two runs. No binding
test failure or skipped pytest test was observed in this configuration.
The first imported build attempt with eight MSBuild workers stopped after
`Checking Build System` without a specific diagnostic. Its cause was not
established; the serial rebuild and all tests passed. The failed attempt is
recorded separately rather than counted as a test failure or omitted.

The [machine-readable report](migration/validation.json) records exact commands,
working directories, tool versions, CMake options, exit codes, durations, and
log hashes. Compact raw test outputs are retained in
[baseline output](migration/windows-baseline.log) and
[imported-source output](migration/windows-imported.log). Larger build logs
remain in the ignored local `build/issue1-baseline/` and
`build/issue1-imported/` directories at the paths recorded in the report.

Source verification passed for all 77 files. Additional checks in a temporary
copy confirmed that the verifier rejects a changed blob, an incomplete
inventory, and an unexpected Python source file.

Linux, macOS, other Python versions, and reduced builds were not tested.
Hosted CI, standalone installation, and release/publication were not run.
These local results establish the migration comparison in the original Core
build context, not standalone build readiness.

## Reproducing the runtime comparison

Use an isolated Python 3.11 environment with the dependency versions recorded
in [validation.json](migration/validation.json). First use the clean Core
checkout at the recorded SHA as the working directory:

```sh
python -m pip install --no-build-isolation --no-deps ./bindings/python/opentlv-core
python -m pip install --no-build-isolation --no-deps ./bindings/python/opentlv
python -B -m pytest -p no:cacheprovider -q bindings/python/opentlv/tests
python -B tests/query/python_facade.py
```

Run each `.py` file in `bindings/python/opentlv/examples/` with the same
interpreter. `python` here denotes the isolated environment's interpreter;
the report contains the actual commands and working directories.

For the post-import comparison, export that exact Core commit into a fresh
temporary directory with `git archive`. For every inventory entry, copy the
destination repository's `destination` file into the temporary tree's `source`
path. This makes the build consume the imported files, including both common
headers and the Query adapter, while using the original Core-owned library,
corpus, and reference implementation. Keep this tree outside the real Core
checkout.

Write this metadata to `opentlv-source.txt` in the temporary tree, ending each
line with LF:

```text
version=0.7.1
commit=5e0aae9c77e9c22d07c7f03d6110243e9ecad85f
```

This uses Core's existing archive metadata support and prevents version
detection from reading the enclosing Python repository. It preserves the
linked library version `0.7.1`; archive mode reports revision count zero
instead of the checkout's count of 25. These temporary metadata are not part
of the imported binding or a standalone dependency policy.

Repeat both package installations from this temporary tree with
`--force-reinstall --no-cache-dir` and a separate native build directory,
then repeat pytest, Query, and examples. On Windows the successful comparison
used `CMAKE_BUILD_PARALLEL_LEVEL=1`. Verify import locations and Core version
after installation so the tests cannot silently use a different environment.

## Follow-up boundaries

Standalone Core dependency selection, native build adaptation, packaging,
active CI, and release automation require subsequent integration. Core cleanup
and workspace pin changes are separate work. The source migration does not
claim standalone installation, hosted CI validation, or release readiness.
