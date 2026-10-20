# Python CI validation

Local validation for [issue #3](https://github.com/OpenTLV/opentlv-python/issues/3)
on 2026-10-20. The implementation adds PR/Main/Full entry points; these local
checks are not hosted workflow acceptance or release authorization.

## Scope

The existing native implementation, public Python API, 299 original pytest cases,
eight examples, common headers and Query adapter are unchanged. CI regression
tests verify the frozen inventory for the original tests/examples.

The Core lock remains `0.7.1` at
`5e0aae9c77e9c22d07c7f03d6110243e9ecad85f` with a null release tag.
Official builds require all existing Core features and keep Core's native test
suites disabled. Real Core release attestations were not exercised.

## Completed local checks

- Windows CPython 3.11.4: the Full runner built both source distributions,
  rebuilt their wheels, installed them into a fresh virtualenv and passed all
  299 original tests with zero skips, eight examples and 171 Query fixtures /
  664 checks. `pip check`, installed Core metadata and full feature checks passed.
- WSL Ubuntu CPython 3.12.3/GCC 13.3: the same final Full runner passed both
  sdist-to-wheel builds, fresh installation, all 299 tests with zero skips,
  eight examples and 171 Query fixtures / 664 checks.
  Both platforms used their own clean pinned Core checkout from GitHub,
  without a sibling-source override, and explicitly recorded `verified: false`.
- Windows and WSL Ubuntu/CPython 3.12.3: 121 dependency, public-target and CI
  infrastructure tests passed. These include matrix completeness, exact
  repository/commit/run/attempt, stale success invalidation, failed/skipped job
  rejection, JUnit consistency, source-baseline guards and timing retries.
- Native formatting with the inherited clang-format 23.1.1 policy, Python
  syntax checks, workflow parsing and `git diff --check` passed.
- Actionlint 1.7.7 passed for all six workflows.
- Linux clang-tidy 18 and cppcheck 2.13 passed for all 12 extension translation
  units with the documented, source-hash-bound false-positive baseline.
- A real `--require-release` runner invocation rejected the current null Core
  release lock before creating its work directory or success evidence.

The [machine-readable summary](ci.json) records the final runtime results,
compiler probes, dependency selections, wheel digests and hashes of local logs.
Raw logs and build records are retained under ignored `build/issue3-*` paths.

## Diagnostics resolved during validation

The locally installed clang-format 21 and an initial clang-format 18 probe
disagreed with two imported expressions. Core's actual pre-commit pin is
23.1.1; using it passed without editing the native sources.

Clang 18 cannot model CPython error-indicator propagation or the scope of
Core's external fixed-format initialization. Cppcheck 2.13 reports two
`Py_RETURN_NONE` branches as missing returns. Reviewed, source-hash-bound
exceptions are documented in
[`static-analysis-baseline.json`](../../cmake/static-analysis-baseline.json).
They fail when the affected source changes and must then be reassessed.

An initial WSL Full run built both wheels but could not bootstrap pip inside
the runtime venv because the local distribution lacks `ensurepip`. The runner
now creates an empty venv and uses the build interpreter's pip `--python`
support to manage it. This keeps the installed-package checks isolated without
changing system Python. The final Windows and Linux runs passed this path.
WSL compilation uses previously extracted local
Python development headers through explicit CMake flags.

## Remaining acceptance

The complete hosted PR/Main/Full workflows, macOS and Python 3.13–3.15 matrix
entries have not been run from this local change. CodeQL upload, hosted timing
collection and actual GitHub required-check contexts need real Actions runs.
Local matrix/gate fixtures do not substitute for those runs.

Branch protection/rulesets have not been modified. After the first hosted PR
run, require the observed `Python quality gate` check as described in
[quality gates](../quality-gates.md). A real approved Core release must be locked
before the strict release mode can succeed. Package publication, signing and
release automation remain separate work.
