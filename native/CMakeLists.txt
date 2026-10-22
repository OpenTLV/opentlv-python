# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

# USE_SABI builds against the CPython stable ABI (Py_LIMITED_API) so one wheel
# per platform works on every Python 3.11 and newer. The module is installed
# at the wheel root (not inside a package directory), so `import _opentlv`
# resolves directly to it, mirroring how the Rust opentlv-sys crate root is
# itself the raw extern "C" declarations.
Python_add_library(_opentlv MODULE USE_SABI 3.11 WITH_SOABI src/module.c src/format.c src/format.h src/compose.c src/generator.c src/generator.h src/reader.c src/reader.h src/writer.c src/writer.h src/schema.c src/schema.h src/query.c src/query.h)
target_sources(_opentlv PRIVATE src/formats/ber.c src/formats/cer.c
    src/formats/der.c src/formats/emv.c src/formats/nfc_type2.c src/formats/lldp.c)

target_link_libraries(_opentlv PRIVATE OpenTLV::tlv)
target_include_directories(_opentlv PRIVATE "${PROJECT_BINARY_DIR}/generated")
target_compile_features(_opentlv PRIVATE c_std_99)

install(TARGETS _opentlv DESTINATION . COMPONENT Python)
