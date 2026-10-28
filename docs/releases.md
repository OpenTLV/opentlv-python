# Python release preparation

`Python release preparation` (`python-release.yml`) is a manual candidate gate.
Every dispatch names the release with the required `tag` input, for example
`v0.1.0`. By default it produces an attested candidate for that tag. The
optional `publish_release` input also creates exactly that tag and a GitHub
Release after verification.
No PyPI/TestPyPI credentials or package-index publisher jobs are configured.

## Prepare a candidate

1. Select a real authenticated Core schema-2 release. Update the exact Core
   commit/version/tag in `cmake/core-artifact.json` and validate its compatibility
   with `cmake/python-package.json`. A null release tag causes preflight to fail;
   do not bypass it or relabel pinned Git as verified. Python 0.1.0 locks Core
   `v0.8.0` at `345c77acb29266036df5f27d04ce315bb61853cc`.
2. Select the independent Python version as described in [versioning](versioning.md).
   Write [`docs/release-notes.md`](release-notes.md), starting with
   `# OpenTLV Python v<version>`, and close the `Unreleased` changelog section as
   `## [<version>] - <YYYY-MM-DD>`. Both files belong to the hashed CI definitions,
   so change them before the Full run. Merge the reviewed candidate to `main`,
   wait for its Main CI to pass and dispatch the workflow there with
   `tag: v<version>`.
3. Preflight requires a manual dispatch from `main` on the official clean
   checkout. It rejects a missing or malformed tag (only stable
   `vMAJOR.MINOR.PATCH`), a tag that differs from the version of both
   distributions, release notes that do not start with `# OpenTLV Python <tag>`,
   a changelog without the closed section, and a tag or GitHub Release that
   already exists. It never derives a tag from the metadata. Full CI runs in the
   same workflow run with verified Core required across all 15 existing
   configurations.
   Source quality, CodeQL, installed API tests, examples, Query and package checks
   must pass. Dependency verification failures stop the build.
4. Assembly validates the exact repository, dispatch SHA, run ID and attempt,
   definition hashes, full matrix, quality report and every package checksum.
   It also opens the packages again to check metadata and dependency identity.
   A failure produces no completed candidate.
5. Download `python-release-candidate-<attempt>` from that run. It contains
   `opentlv-python-<version>.zip`, `manifest.json` and `SHA256SUMS`. The ZIP keeps
   each configuration's actual tested wheels/sdists, record and shared quality
   report. The manifest binds the requested tag, each internal file, the Python
   policy, migration baseline and Core lock to the exact run. All three top-level files receive
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

## GitHub release and documentation publication

To release the verified candidate on GitHub, dispatch the same workflow from
`main` with the `tag` and `publish_release: true`. Do not create the tag
beforehand. With `publish_release: false`, the run creates no tag or release.
The publisher repeats the preflight checks for the requested tag and requires
successful Full and assembly jobs, the exact current run/attempt, a candidate
assembled for the same tag, unchanged candidate metadata and checksums, and
valid attestations for all three candidate files. It then creates the requested
tag at the dispatch commit
and uploads those files to a draft GitHub Release whose text is
`docs/release-notes.md`. Before and after publishing the draft, it checks the
tag commit, the release text and every uploaded asset's name, size and SHA-256
digest. It never uploads packages to PyPI.

Only after GitHub confirms a published release does the workflow upload
`component-release-<attempt>` containing `release.json`. The separate
`Notify Python release documentation` workflow checks the publication job and
receipt, then sends `component-release-published` to `OpenTLV/opentlv-docs`.
Candidate-only runs skip this notification. The notifier performs no checkout
and executes no downloaded code with the dispatch credential.

Install the Docs receiver/configuration before enabling this producer.
Configure `OPENTLV_DOCS_DISPATCH_TOKEN` with Contents write permission limited
to `OpenTLV/opentlv-docs`. Docs needs `OPENTLV_COMPONENT_READ_TOKEN` with Contents
and Actions read access to the configured component repositories. It verifies
the successful producer, attempt-scoped artifact digest, published release ID
and exact tag/commit before publishing `python/<version>/` and updating the
Python version catalog/stable alias. Development pins and other components'
published documentation remain unchanged.

Retry a failed notifier while the producer receipt is retained; duplicate
notifications reuse the immutable snapshot. A failed publisher may leave a tag
or partial GitHub release: inspect and recover manually before retrying. The
publisher never overwrites an existing tag or release. Full-run retries produce
new attempt identities, so old artifacts cannot authorize a new attempt.
After receipt expiry, publication requires a newly verified producer receipt;
do not fabricate one from an old preparation artifact.

Local tests mock GitHub publication and dispatch. Hosted release, receipt,
Docs publication and resulting URLs still require end-to-end verification.

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
