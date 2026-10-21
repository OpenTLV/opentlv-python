# Python binding versioning

The standalone binding starts at **0.1.0**, independently of Core. Both
distributions, `opentlv` and `opentlv-core`, share one binding release version.
The facade requires `opentlv-core==0.1.0`; mixing different binding releases is
unsupported. Python remains `>=3.11` and the native wheel retains `cp311-abi3`.

`cmake/python-package.json` is the version and compatibility policy. Keep the
version in both `pyproject.toml` files and the facade's exact dependency in sync
with it. CMake configuration and source CI reject disagreement. Artifact checks
also validate the built wheel/sdist metadata, and installed-package checks
compare both distribution versions and the runtime version string.

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
assert version("opentlv") == version("opentlv-core")
```

The initial supported Core version is exactly **0.7.1**. No broader range is
claimed without validation. `compatible_core_versions` lists tested versions;
`cmake/core-artifact.json` pins the exact Core commit and optional authenticated
release used for builds. A future Python tag `vMAJOR.MINOR.PATCH` identifies the
Python release and its checked-in Core lock. Core version changes do not
automatically change the Python version. Decide each binding release explicitly.

The installed `_opentlv_core_dependency.json` continues to identify the selected
Core for build validation and diagnostics. Official release preparation requires
an attested Core release; the current `release_tag: null` permits pinned-Git
development builds only.

The original migration baseline is permanently recorded separately: Core commit
`5e0aae9c77e9c22d07c7f03d6110243e9ecad85f` and the SHA-256 of
`docs/migration/source-inventory.json`. Updating the current Core lock must not
rewrite that historical inventory. The policy and native sdist retain this
provenance. Historical validation records keep their original version semantics.

To prepare a new binding release, update the policy, both project versions and
the exact facade dependency together; run source checks and installed-package
Full validation, then follow [release preparation](releases.md). The initial
policy accepts stable `MAJOR.MINOR.PATCH` versions. Publishing and remote tag
creation require separate post-migration work.
