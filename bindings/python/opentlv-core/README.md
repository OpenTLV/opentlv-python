# opentlv-core (experimental)

For public API setup and a first task, start with [the Python user guide](../../../docs/guides/python.md).
The component details below cover packaging, implementation or development.

Native Python bindings to the [OpenTLV](https://github.com/marekcingel/OpenTLV)
C API: a native extension, built directly against the CPython C API and the
CPython Limited API, that registers the C functions as plain Python callables
with no added safety checks or Pythonic ergonomics (`read`, for example,
parses one element with a given wire format and raises a plain
`_opentlv.Error` on failure, without the typed exceptions or Reader
iteration the `opentlv` package builds on top of it). Imported as
`_opentlv`: the leading underscore marks the implementation module as private.
The separately packaged distribution is named `opentlv-core`:

```python
import _opentlv

print(_opentlv.version_string())
```

Not meant to be used directly; use the `opentlv` package instead. See
[Python bindings](https://marekcingel.github.io/OpenTLV/development/python/).

Built-in format providers live in `src/formats/` and are selected by their
CMake component options. `src/format.c` maps stable Python format IDs to the
enabled providers and registers availability flags. `module.c` uses that
shared lookup without including protocol format headers. Fixed-format
operations remain always available. Document remains a required component.

For reduced builds, run `pytest bindings/python/opentlv/tests/test_components.py`
with the rebuilt native extension and Python package on `PYTHONPATH`.
