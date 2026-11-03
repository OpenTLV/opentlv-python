# OpenTLV Python v0.2.0

First release for PyPI: one distribution, `opentlv`, now carries both the native
`_opentlv` extension and the public `opentlv` package, and has no dependencies.
The separate `opentlv-core` distribution of v0.1.0 is discontinued and is not
published. Imports, the public API and the Core lock are unchanged from v0.1.0.

```sh
python -m pip install opentlv
```

- If the v0.1.0 packages are installed, run
  `python -m pip uninstall opentlv-core opentlv` first: both distributions
  ship `_opentlv`.
- Pins OpenTLV Core **v0.8.0** at
  `345c77acb29266036df5f27d04ce315bb61853cc`, linked statically with every
  required capability and format enabled.
- Includes the Reader/Writer and Tree Reader/Writer, streaming sessions,
  composed Formats, Schema, Document, Query, Value and structure codecs and the
  deterministic Generator, with fourteen runnable examples in the repository.
- Publishes one portable `cp311-abi3` wheel per platform for CPython 3.11 and
  newer: `manylinux_2_28_x86_64`, `macosx_11_0_arm64` and `win_amd64`. The
  extension depends only on the C runtime and Python, and wheels bundle no
  external library. Other platforms build from the sdist, which rebuilds the
  complete package and needs a C99 compiler, CMake 3.26 or newer and an
  authenticated GitHub CLI for Core verification.
- Fixes the native module name for builds with CPython 3.15, whose
  `cp311-abi3` wheel CPython 3.11 to 3.14 could not import.
- Every Full CI configuration, CPython 3.11 to 3.15 on Linux, Windows and
  macOS, installs and tests the exact files of the upload set by name and
  hash. The release workflow stages those files on TestPyPI and installs them
  from there on every configuration. Only a successful staging run can be
  promoted: the promotion uploads the same files, without a rebuild, to PyPI
  through Trusted Publishing with PEP 740 provenance.
- Distributes `opentlv-python-0.2.0.zip`, its `manifest.json` and `SHA256SUMS`
  with GitHub build-provenance attestations. See
  [release preparation](https://github.com/OpenTLV/opentlv-python/blob/v0.2.0/docs/releases.md)
  for verifying them.

Generic Core symbol coverage is complete, but symbol references do not prove
functional parity, and Builtins-specific parity remains outside this release.
