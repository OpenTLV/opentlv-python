# Python release preparation

`Python release preparation` (`python-release.yml`) is a manual candidate gate.
Every dispatch names the release with the required `tag` input, for example
`v0.1.0`. By default it produces an attested candidate for that tag. The
optional `publish_release` input also creates exactly that tag and a GitHub
Release after verification.
The optional `pypi` input uploads the verified upload set to TestPyPI or PyPI
through [Trusted Publishing](#pypi-trusted-publishing); no index credentials are
stored.

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
   `vMAJOR.MINOR.PATCH`), a tag that differs from the distribution version,
   release notes that do not start with `# OpenTLV Python <tag>`,
   a changelog without the closed section, and a tag or GitHub Release that
   already exists. It never derives a tag from the metadata. Full CI runs in the
   same workflow run with verified Core required across all 15 existing
   configurations.
   Source quality, CodeQL, installed API tests, examples, Query and package checks
   must pass. Dependency verification failures stop the build.
4. Assembly validates the exact repository, dispatch SHA, run ID and attempt,
   definition hashes, full matrix, quality report and every package checksum.
   It also opens the packages again to check metadata, platform tags, payload
   and dependency identity. A failure produces no completed candidate.
5. Download `python-release-candidate-<attempt>` from that run. It contains
   `opentlv-python-<version>.zip`, `manifest.json` and `SHA256SUMS`. The ZIP keeps
   each configuration's actual tested wheel and sdist, record and shared quality
   report, plus the upload set in `dist/`. The manifest binds the requested tag,
   each internal file, the selected `distributions`, the Python policy, migration
   baseline and Core lock to the exact run. All three top-level files receive
   GitHub build-provenance attestations before artifact upload.

Rerun all jobs when retrying a candidate or GitHub publication. Earlier attempts'
packages or quality reports are rejected; only a package-index upload retries
with **Re-run failed jobs** (see [PyPI Trusted Publishing](#pypi-trusted-publishing)). Candidate files retain their tested bytes; assembly does not rebuild
them. Builds are not bit-for-bit reproducible: the five Python versions of one
platform produce the same `cp311-abi3` wheel filename with different bytes, and
every configuration builds its own sdist. They therefore remain in separate
directories, and assembly selects a unique upload set in `dist/`: each platform's
wheel from its CPython 3.11 configuration (the stable-ABI floor) and the sdist
from `linux-3.11`. These are copies of the exact bytes those configurations
installed and tested, with the same SHA-256, and each filename appears once.

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
digest. It does not upload packages; the separate `pypi` job does.

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

## PyPI Trusted Publishing

Only the `opentlv` distribution is published; `opentlv-core` is not. The
`pypi` dispatch input selects the index:

| `pypi` | Effect |
| --- | --- |
| `none` (default) | No package-index upload. |
| `testpypi` | Rehearsal on TestPyPI. Runs after assembly; with `publish_release: false` the tag must still be unused. |
| `pypi` | Production. Requires `publish_release: true`: preflight rejects the dispatch otherwise, and the job runs only after this run has published the tag and GitHub Release. |

The `Publish verified Python packages to <index>` job runs in the GitHub
environment of the same name and is the only job with `id-token: write` besides
the provenance attestation in assembly. PyPI accepts its OIDC token only for this
repository, workflow and environment, so no API token exists to leak, and pull
requests, forks and other workflows cannot publish. Before any upload,
`scripts/publish_pypi.py prepare` checks:

- a manual dispatch of the canonical `python-release.yml` from `main` on the
  official clean checkout, the requested tag against the package version,
  release notes and closed changelog, and the locked attested Core;
- successful Full and assembly jobs, and for PyPI a successful publisher job
  whose release has the tag at this commit, the release notes and exactly the
  candidate's assets;
- the candidate manifest, `SHA256SUMS`, GitHub attestations and the producing
  run, as for the GitHub publisher: the candidate must come from this run and
  its attempt, or an earlier attempt when only failed jobs were re-run;
- each file of the candidate's `dist/` upload set against the manifest, the
  tested configuration's bytes and record, and the package contract: one wheel
  per declared platform tag and one sdist.

The pinned `pypa/gh-action-pypi-publish` then uploads those files with PEP 740
attestations, never with `skip-existing`. `confirm` waits until the index lists
exactly the upload set with the same SHA-256 digests and uploads a receipt,
`python-package-index-<index>-<attempt>`, with the plan.

Index files are immutable, so `prepare` never replaces one: it fails when the
index lists a file for this version that is not in the upload set or has other
bytes, and otherwise uploads only the files still missing. To retry a failed
upload, use **Re-run failed jobs** on the same run. The job then takes this
run's newest attested candidate, from the attempt that assembled it, so it
uploads the same bytes and can complete an interrupted upload; the candidate's
producer must still be this run, and the environment approval is requested
again. Re-running all jobs rebuilds new bytes, and its preflight rejects a tag
that already exists, so after a published GitHub Release, or once any file of a
version is on the index, a different candidate needs a new patch version.

### One-time configuration

These settings live outside this repository and are made by a maintainer:

1. In the repository settings, create the environments `testpypi` and `pypi`.
   Limit deployment branches to `main`, require a reviewer for `pypi` (and
   preferably for `testpypi`), and add no secrets or variables. The `pypi` job
   then waits for approval after the GitHub Release exists.
2. On [PyPI](https://pypi.org/manage/account/publishing/), add a pending
   GitHub publisher for the project `opentlv`: owner `OpenTLV`, repository
   `opentlv-python`, workflow `python-release.yml`, environment `pypi`. On
   [TestPyPI](https://test.pypi.org/manage/account/publishing/), which has
   separate accounts, add the same publisher with environment `testpypi`. A
   pending publisher does not reserve the name; the first successful upload
   creates the project under the registering account. Ownership and a later
   transfer to the `opentlv` organization are tracked in #47.
3. Create no PyPI API tokens for this project, and remove any that exist.

Still open before the first upload: installation tests of the selected `dist/`
bytes on every supported host (#50), the TestPyPI rehearsal and handoff (#51)
and the first public release (#52).

Build-tool dependencies currently have bounded/minimum requirements rather than
a complete environment lock. Exact Core source selection and retained package
checksums provide traceability, not a claim of bit-for-bit reproducibility across
different toolchains or build times. Local tests mock the index and GitHub; no
hosted TestPyPI or PyPI upload has been validated here.
