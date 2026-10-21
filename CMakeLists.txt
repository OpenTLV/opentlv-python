# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
cmake_minimum_required(VERSION 3.26)
project(OpenTLVPython LANGUAGES C)

find_package(Python 3.11 REQUIRED COMPONENTS Interpreter Development.Module Development.SABIModule)
execute_process(COMMAND "${Python_EXECUTABLE}" -B "${CMAKE_CURRENT_SOURCE_DIR}/scripts/package_contract.py"
    RESULT_VARIABLE _package_result OUTPUT_QUIET)
if(NOT _package_result EQUAL 0)
    message(FATAL_ERROR "Python package metadata validation failed")
endif()
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/python-package.json"
    "${CMAKE_CURRENT_SOURCE_DIR}/pyproject.toml"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/pyproject.toml")
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/cmake/python-package.json" _python_package)
string(JSON OPENTLV_PYTHON_VERSION GET "${_python_package}" version)
configure_file(cmake/python-version.h.in generated/opentlv_python_version.h @ONLY)
include(cmake/Core.cmake)
add_subdirectory(native)
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/core-selection.json"
    DESTINATION . RENAME _opentlv_core_dependency.json COMPONENT Python)
