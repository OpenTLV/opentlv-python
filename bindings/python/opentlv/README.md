# opentlv (experimental)

For public API setup and a first task, start with [the Python user guide](../../../docs/guides/python.md).
The component details below cover packaging, implementation or development.

Python bindings for [OpenTLV](https://github.com/marekcingel/OpenTLV), a
portable C99 library for reading, writing and validating TLV data.

This package wraps `_opentlv`, a native extension that calls the public
OpenTLV C API directly, into an idiomatic API. `Reader`, `Writer`,
`Document`/`Node`, `Element`, `Tag`, `Format`, `LengthSchema`/`StructureSchema`,
the `OpenTLVError` exception hierarchy and a narrow `codec` submodule (EMV
amounts only) are bound so far:

```python
import opentlv

data = bytes([0x01, 0x02, 0xAA, 0xBB, 0x02, 0x00])
for element in opentlv.Reader(data):
    print(element.tag, bytes(element.value))

writer = opentlv.Writer()
writer.write(opentlv.Tag(b"\x50"), b"VISA")
print(writer.bytes())

print(opentlv.__version__)
```

See
[Python bindings](https://marekcingel.github.io/OpenTLV/development/python/)
for build instructions and scope, and [Using OpenTLV from
Python](https://marekcingel.github.io/OpenTLV/guides/python/) for reading,
writing and error handling.

Schema diagnostic `path` values retain the outermost enclosing tags; `path_omitted`
counts innermost scopes beyond the native path capacity. Query Schema error
dictionaries expose the same `path_omitted` field.
