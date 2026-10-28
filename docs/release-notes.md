# OpenTLV Python v0.1.0

First standalone Python release: the native `opentlv-core` distribution
(`_opentlv`) and the public `opentlv` package are versioned together as
**0.1.0**, independently of Core. The facade requires exactly
`opentlv-core==0.1.0`.

- Pins OpenTLV Core **v0.8.0** at
  `345c77acb29266036df5f27d04ce315bb61853cc` and builds from its attested
  release artifacts by default. Core is linked statically with every required
  capability and format enabled; there are no reduced-feature packages.
- Includes the Reader/Writer and Tree Reader/Writer, streaming sessions,
  composed Formats, Schema, Document, Query, Value and structure codecs and the
  deterministic Generator, with fourteen runnable examples.
- Requires Python 3.11 or newer; the native wheel targets the CPython 3.11
  stable ABI (`cp311-abi3`). Full CI covers CPython 3.11 to 3.15 on Linux,
  Windows and macOS.
- Building from source needs a C99 compiler, CMake 3.26 or newer and an
  authenticated GitHub CLI for Core verification.
- Distributes `opentlv-python-0.1.0.zip`, its `manifest.json` and `SHA256SUMS`
  with GitHub build-provenance attestations. The archive holds the wheels and
  sdists actually tested by each Full CI configuration, their build records and
  the quality report. See
  [release preparation](https://github.com/OpenTLV/opentlv-python/blob/v0.1.0/docs/releases.md)
  for verifying them.

PyPI publication remains a separate follow-up; the runner-native wheels are not
yet portable package-index wheels. Generic Core symbol coverage is complete,
but symbol references do not prove functional parity, and Builtins-specific
parity remains outside this release.
