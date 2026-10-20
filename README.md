# opentlv-python

Python bindings for [OpenTLV](https://github.com/OpenTLV/opentlv), a library
for parsing, encoding, and working with TLV and TLV-like binary formats.

This repository contains the source migration from Core described in
[issue #1](https://github.com/OpenTLV/opentlv-python/issues/1).
The existing implementation, tests, examples, and package metadata are
preserved byte-for-byte. Standalone build integration is a follow-up:
the imported native package still requires the original Core build tree.

## Layout

| Path | Content |
| --- | --- |
| `bindings/python/opentlv-core/` | Native `_opentlv` extension, distributed as `opentlv-core` |
| `bindings/python/opentlv/` | Public `opentlv` package, its tests and eight examples |
| `bindings/common/` | Two native adapters required by the extension |
| `tests/query/python_facade.py` | Python adapter for the Core-owned shared Query corpus |
| `docs/guides/python.md` | Preserved Python user guide |
| `docs/development/python.md` | Preserved Python developer guide |
| `docs/migration/` | Source inventory, original CI configuration, and validation evidence |

The preserved guides describe the original Core checkout. Their commands
and links to other Core documents retain that context; they are not standalone
installation instructions. Use the pinned originals linked in the
[migration record](docs/migration.md) for cross-repository documentation links.

## Migration verification

With the sibling Core checkout containing the recorded commit:

```sh
python -B scripts/verify_migration.py --core ../opentlv
```

This checks the complete original Python tree, explicit migration dependencies,
Git blob contents, and SHA-256 hashes. It does not build or install the packages.
See the [migration record](docs/migration.md) for runtime baseline results,
test ownership, supported configurations, and remaining build integration.

The packages retain their existing Python 3.11+ requirement and package version
`0.1.0`. `opentlv.__version__` continues to report the linked Core version.
