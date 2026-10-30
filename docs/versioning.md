# Python binding versioning

The standalone binding starts at **0.1.0**, independently of Core. One
distribution, `opentlv`, carries the native `_opentlv` module and the public
`opentlv` package, so both layers always have the same binding release version.
It has no dependencies; the former `opentlv-core` distribution is not published.
Python remains `>=3.11` and every wheel retains `cp311-abi3`.

`cmake/python-package.json` is the version and compatibility policy. Keep the
version in `pyproject.toml` in sync with it. CMake configuration and source CI
reject disagreement. Artifact checks also validate the built wheel/sdist
metadata, and installed-package checks compare the distribution version and the
runtime version string.

`opentlv.__version__` and `_opentlv.version_string()` now return the **Python
binding version**, not the Core version returned at the migration baseline.
CMake generates the native version header from the policy, so source installs,
sdist builds and wheels have the same behavior without needing Git tags or Git
metadata to compute their version. Import names and function signatures remain
unchanged. Installed distribution versions are also available through:

```python
from importlib.metadata import version
import opentlv
import _opentlv

assert opentlv.__version__ == _opentlv.version_string() == version("opentlv")
```

The first Python release, **0.1.0**, supports exactly Core **0.8.0**; the
unreleased migration builds used Core 0.7.1. No broader range is claimed
without validation. `compatible_core_versions` lists tested versions;
`cmake/core-artifact.json` pins the exact Core commit and optional authenticated
release used for builds. A future Python tag `vMAJOR.MINOR.PATCH` identifies the
Python release and its checked-in Core lock. Core version changes do not
automatically change the Python version. Decide each binding release explicitly.

The installed `_opentlv_core_dependency.json` continues to identify the selected
Core for build validation and diagnostics. The lock names the attested Core
release `v0.8.0` at `345c77acb29266036df5f27d04ce315bb61853cc`; every default
build verifies its release artifacts, and official release preparation
additionally rejects a lock without a release tag.

The original migration baseline is permanently recorded separately: Core commit
`5e0aae9c77e9c22d07c7f03d6110243e9ecad85f` and the SHA-256 of
`docs/migration/source-inventory.json`. Updating the current Core lock must not
rewrite that historical inventory. The policy and the sdist retain this
provenance. Historical validation records keep their original version semantics,
including the two distributions of the GitHub release `v0.1.0`.

To prepare a new binding release, update the policy and the project version
together, write the versioned
[release notes](release-notes.md) and close the [changelog](../CHANGELOG.md);
run source checks and installed-package Full validation, then follow
[release preparation](releases.md). The initial
policy accepts stable `MAJOR.MINOR.PATCH` versions. The optional GitHub publisher
creates `v<version>` only after verified Full CI, or when promoting a candidate
staged on TestPyPI; PyPI publication of that version follows the GitHub Release
of the promotion, as described in the release guide.
