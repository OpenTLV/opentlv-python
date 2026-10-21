# Independent packaging validation (#4)

Validation date: 2026-10-21. These are local checks of uncommitted changes on
`feature/4_python_packaging_versioning`, based on commit
`c459b19002aafaee72df65c48dbd13f6eea57f1f`. They are not hosted or publication
evidence. See [machine-readable results](packaging.json).

## Scope

Both Python distributions use the independent binding version `0.1.0` and the
facade requires `opentlv-core==0.1.0`. `_opentlv.version_string()` and
`opentlv.__version__` now report that binding version. The separately recorded
Core selection remains `0.7.1` at
`5e0aae9c77e9c22d07c7f03d6110243e9ecad85f` with all supported features.
Import names, Python >=3.11 compatibility and the existing 299-case API suite
are preserved. Historical migration inventory and runtime logs are unchanged.

## Completed checks

- Windows/CPython 3.11: the Full build runner created both sdists, rebuilt their
  wheels against a freshly resolved pinned Core, installed both into an isolated
  environment and passed 299 API tests, eight examples and 171 Query fixtures /
  664 checks with no skips. Artifact metadata, contents, checksums and bundled
  Core identity passed validation. `build/issue4-windows.json` records this run;
  its definition hashes match the implemented source and CI contracts.
- An additional clean Windows installation requested only `opentlv==0.1.0`
  using `--no-index --find-links build/issue4-windows/wheels`. pip resolved the
  matching native dependency; `pip check` and both runtime version APIs passed.
- WSL Linux/CPython 3.12.3 rebuilt those same Windows-produced source archives
  into native Linux and pure Python wheels with a freshly resolved pinned Core.
  A clean `--no-index --find-links` install of only `opentlv==0.1.0` resolved the
  matching native wheel. `pip check`, artifact checks, all 299 API tests, eight
  examples and 171 Query fixtures / 664 checks passed without skips. Both public
  version expressions and both installed distributions reported `0.1.0`.
  Evidence is in `build/issue4-linux-from-sdist/validation.json` and its build log.
- Windows and WSL Linux: all 162 dependency/public-target/CI/package regressions
  passed, including the eight Bash argument/failure-propagation cases. New cases
  cover metadata drift, unbounded/mismatched dependencies, missing/modified
  artifacts, stale attempts, incomplete matrices, unverified Core, manual-main
  preflight, successful candidate assembly and checksum preservation.
- Release preflight correctly rejects the current null Core release lock.
  Positive assembly tests use explicit synthetic verified-Core fixtures; they
  do not claim to consume a real attestation or execute hosted release jobs.
- Python syntax/workflow checks, clang-format 23.1.1 and actionlint 1.7.7 passed.
  Linux clang-tidy 18 and cppcheck 2.13 passed for all 12 native translation units.
  The inherited native analyzer exclusions were reassessed for the three-line
  version implementation change; suppressed paths, checkers and line numbers
  remain unchanged.

## Local environment notes

The first sandboxed Windows test run could not start Git Bash because its
signal pipe was denied (Win32 error 5). The same suite passed outside the
sandbox. A first build invocation exposed a local-variable/import name clash
in the new package-policy integration; it was corrected before the successful
Windows build and regression runs.

WSL uses the existing local Python development headers under
`build/issue2-linux-deps/extracted/usr/include`, with both `Python_INCLUDE_DIR`
and the multiarch include root supplied explicitly. No system Python or Conan
environment was changed. Initial static-analysis setup lacked those include
paths; the extracted cppcheck executable also required its local shared-library
directory in `LD_LIBRARY_PATH`. The Linux full-run attempts stopped during source
archive creation are not reported as successful runs. Linux validation instead
rebuilt the actual Windows-generated sdists, demonstrating cross-platform source
archive consumption without needing the Python or Core development checkout as
the package input. The existing repository tests were then run against the
installed packages.

## Remaining hosted and release evidence

A new hosted Full run must validate all 15 configurations and uploaded package
bytes on the implementation revision. macOS and the additional interpreter
versions were not run locally. GitHub OIDC attestation generation and the manual
candidate workflow remain unexecuted. An approved real Core schema-2 release
must be locked before that workflow can pass.

PyPI/TestPyPI publication and remote tag/GitHub Release creation remain disabled.
Runner-native Linux wheels have not established portable PyPI binary coverage.
See [release preparation and future publishing](../releases.md).
