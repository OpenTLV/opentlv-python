# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Independent distribution versions and validation of the actual package bytes."""

from email.parser import BytesParser
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tomllib
import zipfile

from build_support import ROOT, digest, read, require
from verified_core import lock

DISTRIBUTIONS = ("opentlv-core", "opentlv")
PROJECTS = ("pyproject.toml", "src/pyproject.toml")


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
    inventory = root / "docs/migration/source-inventory.json"
    migration = read(inventory)
    require(value.get("migration") == {"repository": migration["source_repository"],
                                       "commit": migration["source_commit"],
                                       "inventory_sha256": digest(inventory)},
            "Frozen migration provenance differs")
    for name, path in zip(DISTRIBUTIONS, PROJECTS):
        project = tomllib.loads((root / path).read_text(encoding="utf-8"))["project"]
        require(project["name"] == name and project["version"] == value["version"]
                and project["requires-python"] == value["requires_python"],
                "Distribution metadata differs from Python package policy")
        expected = ["opentlv-core==" + value["version"]] if name == "opentlv" else []
        require(project.get("dependencies", []) == expected, "Python package dependency must be exact")
        require(project.get("license") == "MIT" and project.get("license-files") == ["LICENSE"],
                "Distribution license metadata changed")
    # Hatchling cannot package files outside src/, so the public package keeps a copy.
    require((root / "src/LICENSE").read_bytes() == (root / "LICENSE").read_bytes(),
            "src/LICENSE differs from LICENSE")
    return value


def check_metadata(data, name, value):
    metadata = BytesParser().parsebytes(data)
    for field, expected in (("Name", name), ("Version", value["version"]),
                            ("Requires-Python", value["requires_python"]),
                            ("License-Expression", "MIT"), ("License-File", "LICENSE")):
        require(metadata.get_all(field) == [expected], "Package metadata differs: " + field)
    dependencies = [re.sub(r"[\s()]", "", item) for item in metadata.get_all("Requires-Dist", [])]
    require(dependencies == (["opentlv-core==" + value["version"]] if name == "opentlv" else []),
            "Built package dependency must be exact")


def check_wheel(path, name, value, selected):
    prefix = name.replace("-", "_") + "-" + value["version"]
    tag = "cp311-abi3-" if name == "opentlv-core" else "py3-none-any"
    require(path.name.startswith(prefix + "-" + tag) and path.name.endswith(".whl"),
            "Unexpected wheel filename/version/tag")
    info = prefix + ".dist-info/"
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate wheel entries")
        require([entry for entry in names if entry.endswith(".dist-info/METADATA")] == [info + "METADATA"],
                "Unexpected wheel metadata directory")
        check_metadata(archive.read(info + "METADATA"), name, value)
        require(info + "licenses/LICENSE" in names and
                archive.read(info + "licenses/LICENSE") == (ROOT / "LICENSE").read_bytes(),
                "Wheel license text differs")
        wheel = BytesParser().parsebytes(archive.read(info + "WHEEL"))
        require(wheel.get_all("Tag") == [path.name[len(prefix) + 1:-4]], "Wheel tag differs from filename")
        require(wheel.get_all("Root-Is-Purelib") == ["false" if name == "opentlv-core" else "true"],
                "Wheel installation scheme differs")
        payload = [entry for entry in names if not entry.startswith(info)]
        if name == "opentlv-core":
            require(len(payload) == 2 and "_opentlv_core_dependency.json" in payload
                    and any(entry.startswith("_opentlv.") and entry.endswith((".so", ".pyd"))
                            and "/" not in entry for entry in payload), "Unexpected native wheel payload")
            require(json.loads(archive.read("_opentlv_core_dependency.json")) == selected,
                    "Bundled Core identity differs from build evidence")
            # The extension links Core statically.
            require(info + "licenses/OpenTLV/LICENSE" in names and
                    archive.read(info + "licenses/OpenTLV/LICENSE").strip(),
                    "Native wheel lacks the Core license")
        else:
            require("opentlv/__init__.py" in payload and
                    all(entry.startswith("opentlv/") and ".." not in PurePosixPath(entry).parts
                        for entry in payload), "Unexpected public wheel payload")
            require(set(payload) == {path.relative_to(ROOT / "src").as_posix()
                                    for path in (ROOT / "src/opentlv").glob("*.py")},
                    "Public wheel source inventory differs")


def sdist_inputs(name):
    """Required build inputs relative to each distribution's source root."""
    if name == "opentlv":
        return {"pyproject.toml", "README.md", "LICENSE"} | {
            path.relative_to(ROOT / "src").as_posix()
            for path in (ROOT / "src/opentlv").glob("*.py")}
    return {"CMakeLists.txt", "LICENSE", "README.md", "pyproject.toml", "src/pyproject.toml",
            "docs/migration/source-inventory.json"} | {
                path.relative_to(ROOT).as_posix()
                for directory in ("cmake", "scripts", "native")
                for path in (ROOT / directory).rglob("*")
                if path.is_file() and (path.suffix in (".py", ".c", ".h", ".in", ".json", ".cmake")
                                       or path.name == "CMakeLists.txt")}


def check_sdist(path, name, value):
    prefix = name.replace("-", "_") + "-" + value["version"]
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
        require(sdist_inputs(name) <= relative_names, "Sdist is missing build inputs")
        require(not any("bindings" in PurePosixPath(path).parts for path in relative_names),
                "Sdist contains obsolete bindings layout")
        if name == "opentlv":
            require(not any(PurePosixPath(path).parts[0] in ("tests", "examples", "native", "scripts")
                            for path in relative_names), "Unexpected public sdist payload")
        def content(relative):
            member = archive.getmember(prefix + "/" + relative)
            require(member.isfile(), "Expected a regular sdist input")
            return archive.extractfile(member).read()
        check_metadata(content("PKG-INFO"), name, value)
        require(content("LICENSE") == (ROOT / "LICENSE").read_bytes(), "Sdist license text differs")
        project = tomllib.loads(content("pyproject.toml").decode())["project"]
        require(project["name"] == name and project["version"] == value["version"],
                "Sdist build metadata differs")
        if name == "opentlv-core":
            require(json.loads(content("cmake/python-package.json")) == value,
                    "Sdist package policy differs")
            require(json.loads(content("cmake/core-artifact.json")) == lock(), "Sdist Core lock differs")
            require(content("docs/migration/source-inventory.json") ==
                    (ROOT / "docs/migration/source-inventory.json").read_bytes(),
                    "Sdist migration provenance differs")


def artifact_names(tier, value):
    version = re.escape(value["version"])
    names = {"wheels/opentlv": rf"opentlv-{version}-py3-none-any\.whl",
             "wheels/opentlv-core": rf"opentlv_core-{version}-cp311-abi3-[A-Za-z0-9_.]+\.whl"}
    if tier == "full":
        names.update({"sdists/" + name: re.escape(name.replace("-", "_") + "-" + value["version"] + ".tar.gz")
                      for name in DISTRIBUTIONS})
    return names


def validate_artifact_record(record, value):
    require(record.get("package_version") == value["version"], "Package version evidence differs")
    require(record.get("package_versions") == dict.fromkeys(DISTRIBUTIONS, value["version"]),
            "Installed distribution versions differ")
    expected = artifact_names(record["tier"], value)
    artifacts = record.get("artifacts", {})
    require(len(artifacts) == len(expected), "Incomplete package artifact inventory")
    for key, pattern in expected.items():
        directory, name = key.split("/")
        matches = [(path, sha) for path, sha in artifacts.items()
                   if re.fullmatch(directory + "/" + pattern, path)]
        require(len(matches) == 1 and re.fullmatch(r"[0-9a-f]{64}", matches[0][1]),
                "Missing or invalid package digest")
        if directory == "wheels":
            require(record["wheels"].get(name) == matches[0][1], "Contradictory wheel digest")


def inspect_artifacts(work, tier, selected, value):
    result = {}
    for key, pattern in artifact_names(tier, value).items():
        directory, name = key.split("/")
        matches = [path for path in (work / directory).iterdir() if re.fullmatch(pattern, path.name)]
        require(len(matches) == 1 and matches[0].is_file(), "Missing or duplicate distribution artifact")
        path = matches[0]
        if directory == "wheels":
            check_wheel(path, name, value, selected)
        else:
            check_sdist(path, name, value)
        result[path.relative_to(work).as_posix()] = digest(path)
    actual = {path.relative_to(work).as_posix() for folder in ("wheels", "sdists")
              for path in (work / folder).rglob("*") if path.is_file()}
    require(actual == set(result), "Unexpected distribution artifact")
    return result


def validate_bundle(work, record, value):
    validate_artifact_record(record, value)
    require(inspect_artifacts(work, record["tier"], record["core"], value) == record["artifacts"],
            "Package bytes differ from validated build")


if __name__ == "__main__":
    print(json.dumps(policy(), indent=2))
