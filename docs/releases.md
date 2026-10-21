# Python release preparation

`Python release preparation` (`python-release.yml`) is a manual candidate gate.
It does not create remote tags, GitHub Releases, or publish to PyPI/TestPyPI.
No package-index credentials or publisher jobs are configured.

## Prepare a candidate

1. Select a real authenticated Core schema-2 release. Update the exact Core
   commit/version/tag in `cmake/core-artifact.json` and validate its compatibility
   with `cmake/python-package.json`. The current null release tag deliberately
   causes preflight to fail; do not bypass it or relabel pinned Git as verified.
2. Select the independent Python version as described in [versioning](versioning.md).
   Merge the reviewed candidate to `main` and dispatch the workflow there.
3. Preflight requires the official clean checkout. Full CI runs in the same
   workflow run with verified Core required across all 15 existing configurations.
   Source quality, CodeQL, installed API tests, examples, Query and package checks
   must pass. Dependency verification failures stop the build.
4. Assembly validates the exact repository, dispatch SHA, run ID and attempt,
   definition hashes, full matrix, quality report and every package checksum.
   It also opens the packages again to check metadata and dependency identity.
   A failure produces no completed candidate.
5. Download `python-release-candidate-<attempt>` from that run. It contains
   `opentlv-python-<version>.zip`, `manifest.json` and `SHA256SUMS`. The ZIP keeps
   each configuration's actual tested wheels/sdists, record and shared quality
   report. The manifest binds each internal file, the Python policy, migration
   baseline and Core lock to the exact run. All three top-level files receive
   GitHub build-provenance attestations before artifact upload.

Rerun all jobs when retrying. Earlier attempts' packages or quality reports are
rejected. Candidate files retain their tested bytes; assembly does not rebuild
them. Multiple configurations can produce the same wheel filename with different
bytes, so they remain in separate directories. This archive is a validation
candidate, not a flat package-index upload directory.

Follow [GitHub's attestation verification instructions](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
to verify downloaded subjects against `OpenTLV/opentlv-python` and the
`python-release.yml` signer. Check the expected commit and run as well as
`SHA256SUMS`; a checksum alone does not authenticate the producer. Manifest
records are evidence, while the hosted attestation authenticates their origin.

## Future PyPI publication (separate approval and issue)

1. Confirm ownership/availability of both package names, release version and
   supported platform/architecture targets. Do not infer availability from the
   local project names.
2. Establish the final portable wheel policy (including Linux platform tags and
   external-library inspection), select one artifact per filename and test the
   final bytes on supported hosts. Current runner-native wheels do not by
   themselves establish portable PyPI binary coverage. Any repair/rebuild changes
   the bytes and requires fresh installation tests, checksums and provenance.
3. Check final metadata and README rendering with `python -m twine check` over
   the selected wheels and sdists. Keep both distributions at the same version
   and retain the exact native-package requirement. Validate a clean install
   using a directory containing only those files and `pip --no-index --find-links`.
4. Configure separate reviewed TestPyPI and PyPI
   [Trusted Publishers](https://docs.pypi.org/trusted-publishers/) for both
   distributions and a protected publishing environment. This is not configured
   by migration or by the candidate workflow.
5. After explicit publishing approval, test the selected artifacts on TestPyPI,
   then publish the approved artifacts to PyPI through the separately implemented
   publisher. Publish the native dependency before the facade, verify a fresh
   installation/import, and record the release tag, file hashes and provenance.

Build-tool dependencies currently have bounded/minimum requirements rather than
a complete environment lock. Exact Core source selection and retained package
checksums provide traceability, not a claim of bit-for-bit reproducibility across
different toolchains or build times. No PyPI publication has been validated here.
