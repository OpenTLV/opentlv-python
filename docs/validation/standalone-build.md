# Standalone Python build validation

Local validation for [issue #2](https://github.com/OpenTLV/opentlv-python/issues/2)
on 2026-10-20. This records local evidence, not hosted CI or release acceptance.

## Dependency and implementation

The lock selects Core `0.7.1` at
`5e0aae9c77e9c22d07c7f03d6110243e9ecad85f`, with no release tag.
The Windows default build cloned Core from GitHub and recorded a clean
`pinned-git` selection with `verified: false`. It used no sibling checkout.
Both Python distribution versions remain `0.1.0`.

The native implementation, Python facade, original pytest modules, examples,
common adapters and Query facade remain unchanged. The migration verifier
passed all 77 original files using import commit
`e0e2ce1014bfa57a86d796a2e5c5b8935cfad49a`; its inventory remains frozen.

## Completed checks

| Check | Windows x64 | Linux x64, WSL Ubuntu |
| --- | --- | --- |
| Python | CPython 3.11.4 | CPython 3.12.3 |
| Compiler | MSVC 19.44.35222.0 | GCC 13.3.0 |
| CMake | 3.31.7 | 3.28.3 |
| Native wheel | `cp311-abi3-win_amd64` | `cp311-abi3-linux_x86_64` |
| Standalone native/public package build and install | Passed | Passed |
| Existing pytest suite | 299 passed | 299 passed |
| Existing examples | 8 passed | 8 passed |
| Shared Query corpus | 171 fixtures / 664 checks | 171 fixtures / 664 checks |
| Dependency and public-target contract tests | 52 passed | 52 passed |
| Core selection | Local and pinned remote source | Local source |
| Native sdist rebuilt outside repository tree | Passed, pinned remote Core | Not run |

The final Windows source build was reconfigured and rebuilt against the clean
pinned cache after the verification changes; its wheel passed runtime tests again.
All 17 Core requirements remained internal and enabled with all 17 command-line
inputs set to `OFF`. Real CMake configuration rejected both a local override in
CI and a required verified release with the null release lock.

Wheel inspection found only the extension, dependency record and distribution
metadata, without Core headers or archives. The sdist includes the independent
build files, resolver and adapters. Linux compilation used `-fPIC`.

Linux used a development override of the shared Windows Core checkout.
WSL Git reported `dirty: true`, preserved in its dependency record; this is
development/PIC evidence, not an official pinned Linux build. Windows Git
reported that sibling checkout clean. Python headers were unpacked from Ubuntu's
`libpython3.12-dev` into `build/`. Dependencies were installed in project virtual
environments; system Python installations were not modified.

## Verification tests

Tests cover exact source identity, dirty pinned sources, annotated version tags,
CI overrides, unavailable revisions, release locking, manifest identity and
run/attempt mismatches, incomplete Full CI results, workflow/configuration hashes,
failed attestations without Git fallback, archive checksums/traversal,
binary compatibility/PIC, verified binary/source selection, and public target
feature/version/commit validation.

Authenticated download tests use fixtures and mocked `gh` responses. They check
signer/source arguments and failure behavior; they do not prove authentication
against a real published release.

## Local evidence and limitations

The [machine-readable report](standalone-build.json) records selections and
hashes of local logs and wheels. Logs remain under ignored `build/`:

- `issue2-local-build.log`, `issue2-local-tests.log`: sibling-source build.
- `issue2-final-local-build.log`: all feature inputs set to `OFF`.
- `issue2-sdist-build.log`, `issue2-sdist-tests.log`: sdist with remote pinned Core.
- `issue2-final-pinned-build.log`, `issue2-final-pinned-tests.log`: final source build.
- `issue2-linux-build.log`, `issue2-linux-tests.log`: Linux build and runtime tests.
- `issue2-build-tests.log`, `issue2-linux-build-tests.log`: dependency tests.
- `issue2-reject-ci.log`, `issue2-reject-release.log`: configuration rejection.

The first pip attempt hit a sandbox cache restriction; subsequent commands used
`--no-cache-dir`. The first Linux configure lacked Python headers; the retry used
locally extracted headers. Neither failed attempt counts as a successful build.

macOS, other Python versions, hosted CI, real release-artifact attestations and
publication were not run. An approved Core release must be locked before the
verified-release mode can succeed. Publication and hosted CI architecture remain
outside this implementation.
