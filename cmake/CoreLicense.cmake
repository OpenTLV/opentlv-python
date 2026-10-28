# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

# Core is linked statically, so the wheel carries its license next to this one.
# The selection records a native path. Its Windows backslashes would become
# escape sequences in the generated install script, which CMake 4 rejects.
function(opentlv_python_install_core_license evidence destination)
    string(JSON _source GET "${evidence}" source_path)
    file(TO_CMAKE_PATH "${_source}" _source)
    install(FILES "${_source}/LICENSE" DESTINATION "${destination}" COMPONENT Python)
endfunction()
