# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

set(OPENTLV_PYTHON_CORE_SOURCE "" CACHE PATH "Explicit local Core Git checkout (development only)")
option(OPENTLV_PYTHON_REQUIRE_VERIFIED_CORE "Require an attested Core release; reject pinned Git" OFF)
set(_core_selection "${CMAKE_CURRENT_BINARY_DIR}/core-selection.json")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/core-probe.json"
    "{\"COMPILER_ID\":\"${CMAKE_C_COMPILER_ID}\","
    "\"COMPILER_VERSION\":\"${CMAKE_C_COMPILER_VERSION}\","
    "\"SIZEOF_DATA_PTR\":\"${CMAKE_SIZEOF_VOID_P}\","
    "\"SYSTEM\":\"${CMAKE_SYSTEM_NAME}\","
    "\"PROCESSOR\":\"${CMAKE_SYSTEM_PROCESSOR}\","
    "\"COMPILER_ARCHITECTURE\":\"${CMAKE_C_COMPILER_ARCHITECTURE_ID}\","
    "\"CROSS_COMPILING\":\"${CMAKE_CROSSCOMPILING}\"}\n")
set(_core_args
    --work "${CMAKE_CURRENT_BINARY_DIR}/core-dependency"
    --output "${_core_selection}"
    --probe "${CMAKE_CURRENT_BINARY_DIR}/core-probe.json")
if(CMAKE_CONFIGURATION_TYPES)
    # A single Release binary cannot satisfy every multi-config build.
    list(APPEND _core_args --configuration MultiConfig)
elseif(CMAKE_BUILD_TYPE)
    list(APPEND _core_args --configuration "${CMAKE_BUILD_TYPE}")
endif()
if(OPENTLV_PYTHON_CORE_SOURCE)
    list(APPEND _core_args --source "${OPENTLV_PYTHON_CORE_SOURCE}")
endif()
if(OPENTLV_PYTHON_REQUIRE_VERIFIED_CORE)
    list(APPEND _core_args --require-release)
endif()
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_LIST_DIR}/core-artifact.json"
    "${CMAKE_CURRENT_LIST_DIR}/core-features.json"
    "${CMAKE_SOURCE_DIR}/scripts/core_dependency.py"
    "${CMAKE_SOURCE_DIR}/scripts/verified_core.py"
    "${CMAKE_SOURCE_DIR}/scripts/build_support.py")
execute_process(COMMAND "${Python_EXECUTABLE}" -B
    "${CMAKE_SOURCE_DIR}/scripts/core_dependency.py" ${_core_args}
    RESULT_VARIABLE _core_result)
if(NOT _core_result EQUAL 0)
    message(FATAL_ERROR "Core dependency resolution failed; see the diagnostic above.")
endif()
file(READ "${_core_selection}" _core_json)

# These are requirements, not supported user-selectable feature variants.
file(READ "${CMAKE_CURRENT_LIST_DIR}/core-features.json" _features_json)
string(JSON _features_count LENGTH "${_features_json}")
math(EXPR _last_feature "${_features_count} - 1")
set(_core_features "")
foreach(_index RANGE ${_last_feature})
    string(JSON _feature GET "${_features_json}" ${_index})
    list(APPEND _core_features "${_feature}")
    set(${_feature} ON CACHE INTERNAL "Required by the official Python binding" FORCE)
    set(${_feature} ON)
endforeach()
foreach(_option CXX LUA PYTHON WASM TESTS EXAMPLES DOCS BENCHMARKS FUZZING SHARED_LIBS)
    set(OPENTLV_BUILD_${_option} OFF CACHE INTERNAL "Core library only" FORCE)
    set(OPENTLV_BUILD_${_option} OFF)
endforeach()
set(OPENTLV_WARNINGS_AS_ERRORS OFF CACHE INTERNAL "Preserve Python package build behavior" FORCE)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
# Match the existing Windows Python wheel runtime.
set(CMAKE_MSVC_RUNTIME_LIBRARY MultiThreadedDLL)

string(JSON _core_source ERROR_VARIABLE _source_error GET "${_core_json}" source_dir)
if(NOT _source_error)
    add_subdirectory("${_core_source}" "${CMAKE_CURRENT_BINARY_DIR}/core-build" EXCLUDE_FROM_ALL)
else()
    string(JSON _core_package GET "${_core_json}" package_dir)
    # Only the authenticated resolver may select a binary package.
    set(OpenTLV_DIR "${_core_package}" CACHE PATH "Verified Core package" FORCE)
    find_package(OpenTLV CONFIG REQUIRED PATHS "${_core_package}" NO_DEFAULT_PATH)
    file(REAL_PATH "${OpenTLV_DIR}" _actual_package)
    file(REAL_PATH "${_core_package}" _expected_package)
    if(NOT _actual_package STREQUAL _expected_package)
        message(FATAL_ERROR "Verified Core package was shadowed")
    endif()
endif()
include("${CMAKE_CURRENT_LIST_DIR}/ValidateCore.cmake")
opentlv_python_validate_core("${_core_json}" "${_core_features}")
