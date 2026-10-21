# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Changed

- Normalize Python sources under `src/opentlv`, native code under `native`, and standalone tests/examples; update packaging, validation and development paths without changing package identities or API. (#10)
- Clarify standalone installation, workspace development, supported Python versions and contribution ownership, and link examples to the Python repository. (OpenTLV/opentlv-docs#34)
- Report the independent Python binding version through `opentlv.__version__` and `_opentlv.version_string()`, and require the matching native package version. (#4)

### Fixed

- Fix macOS CI startup with Bash 3.2 while preserving optional verified-Core arguments and failure propagation. (#3)

### Added

- Notify the documentation portal after successful Main CI documentation changes, with exact source identity, isolated dispatch credentials and regression coverage. (#13)
- Add Python package version/Core compatibility policy, validated CI distribution artifacts, and manual release preparation with checksums and provenance; keep publication disabled. (#4)
- Add standalone Python PR, Main, and Full CI with installed-package tests, platform/version coverage, and verified dependency quality gates. (#3)
- Build Python packages independently with pinned Core identity, verified release artifact support, and all supported Core features enabled. (#2)
- Import the existing Python bindings, tests, examples, and documentation from Core with recorded migration provenance and baseline validation. (#1)
