# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Exercise the public installed-target contract without a network or Core build."""

import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
FEATURES = json.loads((ROOT / "cmake/core-features.json").read_text())
PIN = json.loads((ROOT / "cmake/core-artifact.json").read_text())


@pytest.mark.parametrize("failure", [None, "missing", "disabled", "duplicate", "version", "commit", "shared"])
def test_public_target_contract(tmp_path, failure):
    headers = tmp_path / "include/tlv"
    headers.mkdir(parents=True)
    definitions = [f"#define {feature} 1" for feature in FEATURES]
    if failure == "missing":
        definitions.pop()
    if failure == "disabled":
        definitions[-1] = f"#define {FEATURES[-1]} 0"
    if failure == "duplicate":
        definitions.append(definitions[-1])
    (headers / "config.h").write_text("\n".join(definitions) + "\n")
    version = "0.0.0" if failure == "version" else PIN["version"]
    commit = "b" * 40 if failure == "commit" else PIN["commit"]
    (headers / "version.h").write_text(
        f'#define OPENTLV_VERSION_STRING "{version}"\n#define OPENTLV_GIT_COMMIT_HASH "{commit}"\n')
    kind = "SHARED" if failure == "shared" else "STATIC"
    (tmp_path / "CMakeLists.txt").write_text(
        'cmake_minimum_required(VERSION 3.26)\nproject(Contract NONE)\n'
        f'add_library(OpenTLV::tlv {kind} IMPORTED)\n'
        f'set_target_properties(OpenTLV::tlv PROPERTIES INTERFACE_INCLUDE_DIRECTORIES "{headers.parent.as_posix()}")\n'
        f'include("{(ROOT / "cmake/ValidateCore.cmake").as_posix()}")\n'
        f'opentlv_python_validate_core([==[{json.dumps(PIN)}]==] "{";".join(FEATURES)}")\n',
        encoding="utf-8")
    result = subprocess.run(["cmake", "-S", str(tmp_path), "-B", str(tmp_path / "build")],
                            capture_output=True, text=True)
    assert (result.returncode == 0) == (failure is None), result.stdout + result.stderr


def test_core_license_installs_from_native_source_path(tmp_path):
    # Like the hosted Windows checkout `D:\a\...`, the native path contains `\a`.
    source = tmp_path / "a" / "OpenTLV-0.8.0"
    source.mkdir(parents=True)
    (source / "LICENSE").write_text("Core license\n", encoding="utf-8")
    evidence = json.dumps({"source_path": str(source)})
    (tmp_path / "CMakeLists.txt").write_text(
        'cmake_minimum_required(VERSION 3.26)\nproject(License NONE)\n'
        f'include("{(ROOT / "cmake/CoreLicense.cmake").as_posix()}")\n'
        f'opentlv_python_install_core_license([==[{evidence}]==] licenses/OpenTLV)\n',
        encoding="utf-8")
    build = tmp_path / "build"
    for command in (["cmake", "-S", str(tmp_path), "-B", str(build)],
                    ["cmake", "--install", str(build), "--prefix", str(tmp_path / "prefix")]):
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0 and "Invalid" not in result.stderr, result.stdout + result.stderr
    # CMake 4 rejects backslash escapes in the generated install script; CMake 3 only warns.
    lines = [line for line in (build / "cmake_install.cmake").read_text(encoding="utf-8").splitlines()
             if "LICENSE" in line]
    assert len(lines) == 1 and f'"{source.as_posix()}/LICENSE"' in lines[0] and "\\" not in lines[0], lines
    assert (tmp_path / "prefix/licenses/OpenTLV/LICENSE").read_text(encoding="utf-8") == "Core license\n"
