# Python quality gates

Python follows the PR, Main and Full entry points established by standalone Lua.
Full is reusable by a future release workflow; this repository does not publish
packages or create tags through these workflows.

| Entry point | Trigger | Required work |
| --- | --- | --- |
| `python-pr.yml` | Pull request to `main` | Linux/CPython 3.11, both installed wheels, all Python tests, examples, Query facade, infrastructure regressions, native formatting/static analysis and CodeQL |
| `python-main.yml` | Push to `main` | Linux/CPython 3.11 wheel build, fresh installation, package/Core identity and public Reader smoke |
| `python-full.yml` | Manual dispatch or `workflow_call` | All 15 platform/interpreter configurations, both sdists rebuilt as wheels, full installed-package checks, source quality and CodeQL |

PR has no path filters, so a documentation-only pull request still produces its
required check. Feature branch pushes do not duplicate PR builds. Main does not
repeat the matrix or source analysis. Full has no push, tag or schedule trigger
and never publishes. A failed configuration does not cancel the remaining Full
matrix. PR/Main superseded runs can be cancelled.

## Supported configurations

[`cmake/ci-matrix.json`](../cmake/ci-matrix.json) is the matrix and runtime-test
inventory used by both the workflow planner and the evidence verifier:

- CPython 3.11, 3.12, 3.13, 3.14 and 3.15.
- Ubuntu 24.04, Windows latest and macOS latest hosted runners.
- Release builds, static Core with all 17 required capabilities and formats.
- Standard CPython builds; PyPy, free-threaded builds, debug interpreters and
  reduced-feature packages are not added by this migration.

This makes the existing `requires-python >=3.11` declaration explicit for the
currently released stable versions. Python 3.15 was released on
[9 October 2026](https://www.python.org/downloads/release/python-3150/).
The native wheel retains `cp311-abi3`; each matrix interpreter builds and tests
the extension, but the matrix does not claim testing one identical wheel across
all interpreter versions. Hosted runner architectures are recorded in evidence;
these checks are not a manylinux/macOS deployment-target or publication policy.

The initial inventory is 299 pytest cases, eight examples and 171 shared Query
fixtures / 664 checks. Intentional changes to tests or the pinned Core corpus
must update this inventory with reviewed evidence. Skips, failures, empty suites
and contradictory JUnit counts are rejected.

## Test ownership and quality

Python owns public API integration, Python/native conversions, exceptions,
capsules, retained buffers, object lifetime and garbage collection, imports and
packaging. The existing public API tests already exercise lifetime/GC scenarios.
They remain unchanged; no native test framework or unrelated test rewrite is
introduced.

Core owns parsing/writing, format/schema/codec/Query semantics, the shared
regression corpus, fuzzing, ABI and performance tests. Core tests, examples,
benchmarks and other language bindings remain disabled during dependency builds.
The unchanged Python Query adapter consumes `corpus.json` and `reference.py` from
the exact selected Core source in a temporary directory; those files are not
copied into this repository.

Source checks parse Python files, validate workflow structure and enforce the
inherited native `.clang-format` with Core's pinned clang-format 23.1.1.
clang-tidy 18 and cppcheck use a filtered compilation database containing every
Python extension translation unit, without analyzing Core's translation units.
CodeQL analyzes C and Python. Build/dependency and CI infrastructure regressions
run with pytest. No new Python formatting policy is imposed on migrated tests.

Each build configuration also executes the workflow's build and gate shell steps
with a stub runner before building packages. These eight regression cases verify
optional release arguments, quoting, logs and failure propagation, including
through `tee`. Both commands use nonempty arrays so `set -u` also works with
macOS Bash 3.2. For local shell-specific checks, set `OPENTLV_TEST_BASH` to the
desired Bash executable and run `tests/ci/test_shell.py` with pytest.

The native migration has documented analyzer false positives in
[`static-analysis-baseline.json`](../cmake/static-analysis-baseline.json).
Only the affected checkers in `module.c` and `writer.c` are excluded; cppcheck's
two `Py_RETURN_NONE` reports are suppressed at their exact lines. The exclusions
require the exact original SHA-256 of each source file. Any source change fails
until those exceptions are reassessed, so they cannot silently hide new code.
Pointer-sized allocations of `PyObject*` arrays are explicitly permitted by
clang-tidy's sizeof policy. The existing native implementation remains unchanged.

## Dependency verification

The existing resolver remains the sole Core selection mechanism. Every CI build
validates the selected repository, full SHA, version, public target headers and
required features. Installed dependency metadata must exactly match the build
selection. Local source overrides are prohibited in hosted CI.

With the current `release_tag: null`, ordinary PR/Main/Full builds use a clean
Git checkout at the locked SHA and record `verified: false`. This is exact source
identity, not an authenticated Core release. A release caller must invoke:

```yaml
jobs:
  full:
    uses: ./.github/workflows/python-full.yml
    with:
      require_verified_core: true
```

That mode requires Full CI and rejects the current null release lock before
building. Once an approved matching release is locked, compatible authenticated
Core binaries are preferred; otherwise the existing verified-source fallback
policy applies. Failed attestations, checksums or producer evidence stop the
build. They never fall back to Git. Testing resolver fixtures is not evidence
that a real published Core attestation was consumed.

## Evidence and required check

Each configuration creates fresh build and runtime directories. Full builds both
source distributions, rebuilds their wheels outside the repository source tree
through pip, checks wheel tags/payload and installs only those wheels into an
isolated virtualenv. The runner verifies imports, `pip check`, Core identity,
all existing tests/examples and the Query adapter. Main uses the same installed
package validation path with only its smoke check.

Successful records include the repository, checkout SHA, run ID and attempt,
matrix configuration, actual interpreter/platform/architecture, compiler probe, Core selection,
wheel SHA-256 digests, test counts, elapsed time and hashes of the CI definitions,
native/Python sources, tests and dependency configuration. Local runs explicitly
record `hosted: false` and their checkout's dirty state.

`Python quality gate` runs even after failed prerequisites. It requires the
exact matrix and all applicable job results. Main explicitly permits only the
source-quality and CodeQL jobs to be skipped. Missing, duplicate, stale,
foreign, cancelled, unexpectedly skipped or unsuccessful evidence fails.
Success evidence is removed before each attempt, so a failed rerun cannot reuse
an old success. The gate CLI accepts only an official clean hosted checkout.

After the first hosted PR run, configure branch protection/rulesets to require
the check ending in `Python quality gate` from GitHub Actions; use the exact
displayed reusable-workflow context (normally `checks / Python quality gate`).
Do not require individual Full matrix jobs on every PR. This implementation does
not change repository settings. A workflow file alone does not enforce merging
rules.

Artifacts include attempt-scoped records, runtime JUnit output and build logs.
The gate uploads `quality.json` only after acceptance. Timing collection uses the
same run/attempt, excludes itself and retries delayed API completion metadata.
Reported job seconds are elapsed runner time, not billed minutes. This is the
first standalone CI baseline; no hosted speedup or measured latency is claimed.

## Local validation

Use an isolated development environment; leave the global Python/Conan setup
unchanged:

```sh
python -m venv build/dev
# Activate build/dev using your shell.
python -m pip install -r requirements-dev.txt clang-format==23.1.1
python -B scripts/check_quality.py
python -B -m pytest -p no:cacheprovider -q tests/build tests/ci
actionlint
python -B scripts/ci.py matrix --tier full
python -B scripts/ci.py build --tier full --configuration linux-3.12 \
  --work build/full-linux-312 --output build/full-linux-312.json
```

Choose a configuration matching the actual interpreter/platform, such as
`windows-3.11` or `macos-3.15`. Every invocation requires a new `--work` directory.
The runner downloads the locked Core and test dependencies. For static checks,
configure with Ninja, `CMAKE_EXPORT_COMPILE_COMMANDS=ON` and the intended
`Python_EXECUTABLE`, then run `scripts/check_static.py --build <directory>`
with `--tool clang-tidy` and `--tool cppcheck`.

See [local validation and remaining hosted acceptance](validation/ci.md).
