# Python bindings (experimental)

The Python bindings live in `bindings/python/`, two separately packaged
distributions:

| Package | Purpose |
| --- | --- |
| `opentlv-core` | Native extension, written directly against the CPython C API; registers the OpenTLV C API as Python callables |
| `opentlv` | Pure-Python package built on `opentlv-core` |

This mirrors the Rust bindings' `opentlv-sys`/`opentlv` split (see [Rust
bindings](rust.md)): all CPython C API interaction is isolated in
`opentlv-core`; `opentlv` is plain Python and imports
the private `_opentlv` module directly (`import _opentlv` resolves to the compiled
extension). For setup and usage, see [Using OpenTLV from
Python](../guides/python.md). For the naming and shape this binding follows
and adapts, see the [language bindings conceptual model](../concepts/bindings.md).

`opentlv-core` exposes the linked library's version, stateless
element-parsing and -encoding calls (`read`, `write`, `encoded_size`)
parameterized by wire format, their `*_fixed` counterparts
(`read_fixed`, `write_fixed`, `encoded_size_fixed`) for the configurable
fixed-width format (`tlv_fixed_format_t`), `structure_validate` (a serialized
rule tree in, a pass/fail with diagnostic detail out), `emv_decode_amount`/
`emv_encode_amount` (the one concrete `tlv_codec_t` the public C API
exports), and a `document_*`/`node_*` family wrapping `tlv_document_t`
(as a `PyCapsule`) and `tlv_node_t` (as a plain integer; see
[relationship to the C API](../guides/python.md#relationship-to-the-c-api)).
`opentlv` builds `Reader`, `Writer`, `Document`/`Node`, `Element`, `Tag`,
`Format`, `FixedFormat`, `LengthSchema`/`StructureSchema`, the `OpenTLVError`
exception hierarchy and the narrow `codec` submodule on top of it; see [Using
OpenTLV from Python](../guides/python.md).

## Build

Requirements: Python 3.11 or newer, CMake 3.26 or newer and a C99 compiler.

```sh
pip install ./bindings/python/opentlv-core ./bindings/python/opentlv
pip install pytest
pytest bindings/python/opentlv/tests
```

[scikit-build-core](https://scikit-build-core.readthedocs.io/) drives the
`opentlv-core` build: it configures and builds the OpenTLV C library with
CMake from the repository root
(`bindings/python/opentlv-core/pyproject.toml` points
`tool.scikit-build.cmake.source-dir` at it), as a static library, and links
it into the extension. The C++ layer, CLI, tests and examples are not built.
The extension is compiled against the CPython Limited API
(`Py_LIMITED_API=0x030B0000`) as an `abi3` module, so one wheel per platform
works on every Python 3.11 and newer. `opentlv` is a plain
[hatchling](https://hatch.pypa.io/latest/plugins/builder/wheel/)-built wheel
with no compiled component; it declares `opentlv-core` as a dependency.
Neither package is published anywhere yet, so install both together from a
checkout, as above; when installed in the same `pip install` invocation, pip
resolves `opentlv`'s `opentlv-core` dependency against the local wheel it
just built instead of looking on PyPI.

## Versioning

Each package's own version, declared in its `pyproject.toml`, is independent
of the OpenTLV C library's version and is not derived from the repository's
Git tags; it follows its own release cadence, the same way the Rust crates'
`Cargo.toml` version does (see [Rust bindings](rust.md#versioning)).
`opentlv.__version__` is a separate thing: it calls `tlv_version_string()` at
import time (through `opentlv-core`) and reports the version of the
*linked C library*, not either package's own version. The two can differ,
for example packages at `0.1.0` built against OpenTLV C library `0.7.1`.

## Continuous integration

The [Python Bindings
workflow](https://github.com/marekcingel/OpenTLV/blob/main/.github/workflows/python.yml)
runs on every push and pull request to `main`: it installs both packages with
`pip install ./bindings/python/opentlv-core ./bindings/python/opentlv` and
runs `pytest bindings/python/opentlv/tests` on Linux, and additionally on
Windows and macOS for release tags.
