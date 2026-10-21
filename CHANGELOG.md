# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed

- Fix macOS CI startup with Bash 3.2 while preserving optional verified-Core arguments and failure propagation. (#3)

### Added

- Add standalone Python PR, Main, and Full CI with installed-package tests, platform/version coverage, and verified dependency quality gates. (#3)
- Build Python packages independently with pinned Core identity, verified release artifact support, and all supported Core features enabled. (#2)
- Import the existing Python bindings, tests, examples, and documentation from Core with recorded migration provenance and baseline validation. (#1)
