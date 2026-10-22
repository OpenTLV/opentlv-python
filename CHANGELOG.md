# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Changed

- Normalize Python sources under `src/opentlv`, native code under `native`, and standalone tests/examples; update packaging, validation and development paths without changing package identities or API. (#10)
- Clarify standalone installation, workspace development, supported Python versions and contribution ownership, and link examples to the Python repository. (OpenTLV/opentlv-docs#34)
- Report the independent Python binding version through `opentlv.__version__` and `_opentlv.version_string()`, and require the matching native package version. (#4)

### Fixed

- Correct the `LICENSE` copyright holder from the OpenTLV organization, inherited from the GitHub template, to Marek Cingel, matching the source headers and the Core license. (#16)
- Fix macOS CI startup with Bash 3.2 while preserving optional verified-Core arguments and failure propagation. (#3)

### Added

- Compose custom Formats without C: `Format.fields()`, `Format.variable()`, `Format.escaped()` and `Format.packed()` build a `ComposedFormat` from `FixedIdentifier`, `VariableIdentifier`, `FixedLength`, `VariableLength`, `EscapedLength` and `PackedField` encodings, with optional tag-only identifiers and `ConstructedBit` nesting, through Core's variable, escaped, packed, binary, tagged and generic field compositions. Composed formats work with Reader, TreeReader, Writer, TreeWriter, Document, Query and schemas; every Format also exposes `decode()`, `measure()`, `encode()`, `can_read` and `can_write` with the Format's error detail. Native entry points take one format specification instead of separate fixed-format variants. (#20)
- Report pinned Core API coverage in PR and Full CI as a non-blocking job: `TLV_API` functions and data referenced from `native/` and `src/`, in total and per header, for core and builtins separately; added and removed symbols when a pull request changes the Core pin; and a documented ignore list for primitives and diagnostic producers in `cmake/api-coverage.json`. The script uses only the standard library and can be reused by other bindings. (#19)
- Optionally publish verified candidates as GitHub releases and notify Docs with exact published-release evidence; keep package-index publication disabled. (OpenTLV/opentlv-docs#42)
- Notify the documentation portal after successful Main CI documentation changes, with exact source identity, isolated dispatch credentials and regression coverage. (#13)
- Add Python package version/Core compatibility policy, validated CI distribution artifacts, and manual release preparation with checksums and provenance; keep publication disabled. (#4)
- Add standalone Python PR, Main, and Full CI with installed-package tests, platform/version coverage, and verified dependency quality gates. (#3)
- Build Python packages independently with pinned Core identity, verified release artifact support, and all supported Core features enabled. (#2)
- Import the existing Python bindings, tests, examples, and documentation from Core with recorded migration provenance and baseline validation. (#1)
