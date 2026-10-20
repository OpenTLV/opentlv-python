# FindPython's USE_SABI/SABIModule support requires CMake 3.26; this only
# raises the required CMake version for this subdirectory, not the repository
# as a whole (OPENTLV_BUILD_PYTHON defaults OFF, so a plain C/C++ build never
# reaches this file), and scikit-build-core supplies its own modern CMake for
# the Python build path regardless.
cmake_minimum_required(VERSION 3.26)

find_package(Python 3.11 REQUIRED COMPONENTS Interpreter Development.Module Development.SABIModule)

# USE_SABI builds against the CPython stable ABI (Py_LIMITED_API) so one wheel
# per platform works on every Python 3.11 and newer. The module is installed
# at the wheel root (not inside a package directory), so `import _opentlv`
# resolves directly to it, mirroring how the Rust opentlv-sys crate root is
# itself the raw extern "C" declarations.
Python_add_library(_opentlv MODULE USE_SABI 3.11 WITH_SOABI src/module.c src/format.c src/format.h src/reader.c src/reader.h src/writer.c src/writer.h src/schema.c src/schema.h src/query.c src/query.h)
if(OPENTLV_FORMAT_BER)
    target_sources(_opentlv PRIVATE src/formats/ber.c)
endif()
if(OPENTLV_FORMAT_CER)
    target_sources(_opentlv PRIVATE src/formats/cer.c)
endif()
if(OPENTLV_FORMAT_DER)
    target_sources(_opentlv PRIVATE src/formats/der.c)
endif()
if(OPENTLV_EMV)
    target_sources(_opentlv PRIVATE src/formats/emv.c)
endif()
if(OPENTLV_NFC)
    target_sources(_opentlv PRIVATE src/formats/nfc_type2.c)
endif()
if(OPENTLV_LLDP)
    target_sources(_opentlv PRIVATE src/formats/lldp.c)
endif()

target_link_libraries(_opentlv PRIVATE tlv)

install(TARGETS _opentlv DESTINATION .)
