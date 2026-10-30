# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""One portable distribution, its independent version and validation of the actual package bytes."""

from email.parser import BytesParser
import hashlib
import json
from pathlib import PurePosixPath
import re
import tarfile
import tomllib
import zipfile

from build_support import ROOT, digest, read, require
from verified_core import lock

DISTRIBUTION = "opentlv"
PROJECT = "pyproject.toml"
# Portable tags only: never a plain linux_x86_64 or an unversioned macOS target.
PLATFORM_TAGS = {"Linux": r"manylinux_2_\d+_x86_64", "Darwin": r"macosx_\d+_0_arm64", "Windows": r"win_amd64"}


def policy(root=ROOT):
    value = read(root / "cmake/python-package.json")
    require(value.get("schema") == 1 and
            re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", value.get("version", "")),
            "Expected an independent MAJOR.MINOR.PATCH Python version")
    require(value.get("requires_python") == ">=3.11", "Python compatibility changed")
    compatible = value.get("compatible_core_versions")
    require(isinstance(compatible, list) and compatible and len(set(compatible)) == len(compatible)
            and all(isinstance(version, str) and re.fullmatch(r"\d+\.\d+\.\d+", version)
                    for version in compatible), "Declare tested Core versions explicitly")
    pinned = read(root / "cmake/core-artifact.json")
    require(pinned["version"] in compatible, "Locked Core is outside the Python compatibility policy")
    platforms = value.get("wheel_platforms")
    systems = {item["system"] for item in read(root / "cmake/ci-matrix.json")["platforms"]}
    require(isinstance(platforms, dict) and set(platforms) == set(PLATFORM_TAGS) == systems
            and all(isinstance(tag, str) and re.fullmatch(PLATFORM_TAGS[system], tag)
                    for system, tag in platforms.items()),
            "Declare one portable wheel platform tag per CI system")
    inventory = root / "docs/migration/source-inventory.json"
    migration = read(inventory)
    require(value.get("migration") == {"repository": migration["source_repository"],
                                       "commit": migration["source_commit"],
                                       "inventory_sha256": digest(inventory)},
            "Frozen migration provenance differs")
    metadata = tomllib.loads((root / PROJECT).read_text(encoding="utf-8"))
    project = metadata["project"]
    require(project["name"] == DISTRIBUTION and project["version"] == value["version"]
            and project["requires-python"] == value["requires_python"],
            "Distribution metadata differs from Python package policy")
    require(not project.get("dependencies"), "The distribution must not depend on a separate native package")
    require(project.get("license") == "MIT" and project.get("license-files") == ["LICENSE"],
            "Distribution license metadata changed")
    wheel = metadata.get("tool", {}).get("scikit-build", {}).get("wheel", {})
    require(wheel.get("packages") == ["src/opentlv"] and wheel.get("py-api") == "cp311",
            "The wheel must carry src/opentlv beside the stable-ABI extension")
    # The root pyproject.toml is the only build entry point.
    require(not (root / "src/pyproject.toml").exists(), "Remove the second build entry point src/pyproject.toml")
    return value


def check_metadata(data, value):
    metadata = BytesParser().parsebytes(data)
    for field, expected in (("Name", DISTRIBUTION), ("Version", value["version"]),
                            ("Requires-Python", value["requires_python"]),
                            ("License-Expression", "MIT"), ("License-File", "LICENSE")):
        require(metadata.get_all(field) == [expected], "Package metadata differs: " + field)
    require(not metadata.get_all("Requires-Dist"), "Built package must not depend on another distribution")


def public_sources():
    return {path.relative_to(ROOT / "src").as_posix() for path in (ROOT / "src/opentlv").glob("*.py")}


def wheel_name(value, system):
    return f'{DISTRIBUTION}-{value["version"]}-cp311-abi3-{value["wheel_platforms"][system]}.whl'


def check_wheel(path, value, selected, system):
    require(path.name == wheel_name(value, system), "Unexpected wheel filename/version/tag")
    info = DISTRIBUTION + "-" + value["version"] + ".dist-info/"
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate wheel entries")
        require([entry for entry in names if entry.endswith(".dist-info/METADATA")] == [info + "METADATA"],
                "Unexpected wheel metadata directory")
        check_metadata(archive.read(info + "METADATA"), value)
        require(info + "licenses/LICENSE" in names and
                archive.read(info + "licenses/LICENSE") == (ROOT / "LICENSE").read_bytes(),
                "Wheel license text differs")
        # The extension links Core statically.
        require(info + "licenses/OpenTLV/LICENSE" in names and
                archive.read(info + "licenses/OpenTLV/LICENSE").strip(),
                "Wheel lacks the Core license")
        wheel = BytesParser().parsebytes(archive.read(info + "WHEEL"))
        require(wheel.get_all("Tag") == ["cp311-abi3-" + value["wheel_platforms"][system]],
                "Wheel tag differs from filename")
        require(wheel.get_all("Root-Is-Purelib") == ["false"], "Wheel installation scheme differs")
        # Repair tools add directory entries; every file still has to be expected.
        payload = {entry for entry in names if not entry.startswith(info) and not entry.endswith("/")}
        native = "_opentlv.pyd" if system == "Windows" else "_opentlv.abi3.so"
        require(native in payload, "Wheel lacks the native _opentlv module")
        require("_opentlv_core_dependency.json" in payload and
                json.loads(archive.read("_opentlv_core_dependency.json")) == selected,
                "Bundled Core identity differs from build evidence")
        # Rejects vendored shared libraries, tests and stale modules alike.
        require(payload - {native, "_opentlv_core_dependency.json"} == public_sources(),
                "Wheel source inventory differs")


def sdist_inputs():
    """Required build inputs relative to the source root."""
    return {"CMakeLists.txt", "LICENSE", "README.md", "pyproject.toml",
            "docs/migration/source-inventory.json"} | {"src/" + path for path in public_sources()} | {
                path.relative_to(ROOT).as_posix()
                for directory in ("cmake", "scripts", "native")
                for path in (ROOT / directory).rglob("*")
                if path.is_file() and (path.suffix in (".py", ".c", ".h", ".in", ".json", ".cmake")
                                       or path.name == "CMakeLists.txt")}


def check_sdist(path, value):
    prefix = DISTRIBUTION + "-" + value["version"]
    require(path.name == prefix + ".tar.gz", "Unexpected sdist filename/version")
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        require(len(names) == len(set(names)), "Duplicate sdist entries")
        require(all(member.name.startswith(prefix + "/") and
                    ".." not in PurePosixPath(member.name).parts and
                    "\\" not in member.name and ":" not in member.name and
                    (member.isfile() or member.isdir()) for member in members), "Unsafe sdist member")
        relative_names = {member.name[len(prefix) + 1:] for member in members if member.isfile()}
        require(sdist_inputs() <= relative_names, "Sdist is missing build inputs")
        require(not any("bindings" in PurePosixPath(path).parts for path in relative_names),
                "Sdist contains obsolete bindings layout")
        require("src/pyproject.toml" not in relative_names, "Sdist contains a second build entry point")
        def content(relative):
            member = archive.getmember(prefix + "/" + relative)
            require(member.isfile(), "Expected a regular sdist input")
            return archive.extractfile(member).read()
        check_metadata(content("PKG-INFO"), value)
        require(content("LICENSE") == (ROOT / "LICENSE").read_bytes(), "Sdist license text differs")
        project = tomllib.loads(content("pyproject.toml").decode())["project"]
        require(project["name"] == DISTRIBUTION and project["version"] == value["version"],
                "Sdist build metadata differs")
        require(json.loads(content("cmake/python-package.json")) == value, "Sdist package policy differs")
        require(json.loads(content("cmake/core-artifact.json")) == lock(), "Sdist Core lock differs")
        require(content("docs/migration/source-inventory.json") ==
                (ROOT / "docs/migration/source-inventory.json").read_bytes(),
                "Sdist migration provenance differs")


def sdist_payload(path):
    """Digest every regular file's content; tar timestamps and ownership differ between builds."""
    with tarfile.open(path) as archive:
        return {member.name: hashlib.sha256(archive.extractfile(member).read()).hexdigest()
                for member in archive.getmembers() if member.isfile()}


def artifact_names(tier, value, system):
    names = {"wheels": wheel_name(value, system)}
    if tier == "full":
        names["sdists"] = f'{DISTRIBUTION}-{value["version"]}.tar.gz'
    return names


def validate_artifact_record(record, value):
    require(record.get("package_version") == value["version"], "Package version evidence differs")
    require(record.get("package_versions") == {DISTRIBUTION: value["version"]},
            "Installed distribution versions differ")
    expected = artifact_names(record["tier"], value, record["configuration"]["system"])
    artifacts = record.get("artifacts", {})
    require(set(artifacts) == {directory + "/" + name for directory, name in expected.items()}
            and all(re.fullmatch(r"[0-9a-f]{64}", sha) for sha in artifacts.values()),
            "Missing or invalid package digest")
    require(record["wheels"] == {DISTRIBUTION: artifacts["wheels/" + expected["wheels"]]},
            "Contradictory wheel digest")


def inspect_artifacts(work, tier, selected, value, system):
    result = {}
    for directory, name in artifact_names(tier, value, system).items():
        path = work / directory / name
        require(path.is_file(), "Missing distribution artifact: " + name)
        if directory == "wheels":
            check_wheel(path, value, selected, system)
        else:
            check_sdist(path, value)
        result[directory + "/" + name] = digest(path)
    actual = {path.relative_to(work).as_posix() for folder in ("wheels", "sdists")
              for path in (work / folder).rglob("*") if path.is_file()}
    require(actual == set(result), "Unexpected distribution artifact")
    return result


def validate_bundle(work, record, value):
    validate_artifact_record(record, value)
    require(inspect_artifacts(work, record["tier"], record["core"], value,
                              record["configuration"]["system"]) == record["artifacts"],
            "Package bytes differ from validated build")


if __name__ == "__main__":
    print(json.dumps(policy(), indent=2))
