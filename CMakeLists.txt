# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
cmake_minimum_required(VERSION 3.26)
project(OpenTLVPython LANGUAGES C)

find_package(Python 3.11 REQUIRED COMPONENTS Interpreter Development.Module Development.SABIModule)
include(cmake/Core.cmake)
add_subdirectory(bindings/python/opentlv-core)
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/core-selection.json"
    DESTINATION . RENAME _opentlv_core_dependency.json COMPONENT Python)
