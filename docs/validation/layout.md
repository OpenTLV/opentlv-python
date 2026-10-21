# Source layout validation

Issue #10 was validated locally on 21 October 2026, from the uncommitted
`feature/10_normalize_python_layout` changes based on
`76767ba52419baf86728a5014e0a128935ed672b`.

Both distributions retain version `0.1.0`. The pinned dependency remains Core
`0.7.1` at `5e0aae9c77e9c22d07c7f03d6110243e9ecad85f`, without release attestation.

| Check | Result |
| --- | --- |
| Build/dependency and CI infrastructure tests | 169 passed on Windows and Linux |
| Windows CPython 3.11.4, MSVC | Both sdists rebuilt as wheels; fresh installation; 299 tests, eight examples, 171 Query fixtures and 664 checks passed |
| Linux CPython 3.12.3, GCC | Both sdists rebuilt as wheels; fresh installation; 299 tests, eight examples, 171 Query fixtures and 664 checks passed |
| Direct source wheels with explicit local Core, Windows | Both wheels built and installed into a fresh environment; dependency checks and isolated public/native import smoke passed |
| Archive contracts | Expected source inputs and wheel modules present; no obsolete `bindings/` tree or tests/examples in installed payloads |
| Relocation fidelity | 18 Python modules, 22 test modules, eight examples and two adapters byte-identical to the parent; native implementation differs only in three adapter include paths |
| Historical migration | All 77 original imports verified at `e0e2ce1014bfa57a86d796a2e5c5b8935cfad49a`; frozen inventory unchanged |
| Source quality | Python syntax, workflow structure, clang-format 23.1.1 and `git diff --check` passed |
| Native analysis | clang-tidy 18 and cppcheck 2.13 passed for all 12 extension translation units |

The local records are `build/issue10-windows.json` and
`build/issue10-linux-clean.json`, with wheels, sdists and runtime reports under
the corresponding directories. Their input hashes match the current relocated
implementation. Linux package validation used a byte-checked temporary source
copy on the Linux filesystem to avoid scanning old builds on the mounted Windows
drive. Infrastructure tests ran against the working tree. Windows shell tests
passed after rerunning outside the sandbox that blocked Git Bash signal pipes.

These are two local Full build configurations, not a completed hosted Full gate.
Hosted PR CI, CodeQL, the complete 15-configuration matrix, macOS and release
attestation/publication were not run. The PR/Main/Full workflow split and Core
dependency selection policy are unchanged; ordinary PR merge does not require
Full CI.
