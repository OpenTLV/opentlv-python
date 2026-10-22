# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Exercise Core API coverage parsing, reporting and pin diffs against local repositories."""

import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import api_coverage

HEADER = """\
#ifndef TLV_SAMPLE_H
#define TLV_SAMPLE_H
#define TLV_SAMPLE_DECLARE(name) TLV_API int name(void);
/* TLV_API int tlv_commented(void); */
#ifdef __cplusplus
extern "C" {
#endif
// TLV_API int tlv_line_commented(void);
TLV_API tlv_result_t tlv_multi_line(const uint8_t* data,
                                    size_t size, void (*visit)(void* context, int item));
TLV_NODISCARD TLV_API const char* TLV_PRINTF(1, 2) tlv_attributed(const char* format, ...);
extern TLV_API const tlv_codec_t tlv_codec_sample;
TLV_API extern const tlv_format_t tlv_format_sample;
extern TLV_API const uint8_t tlv_table[TLV_TABLE_SIZE][2];
typedef struct { int (*callback)(void); } tlv_plain_t;
#ifdef __cplusplus
}
#endif
#endif
"""


def git(repository, *args):
    return subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                           "-C", str(repository), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(repository, files):
    for name, text in files.items():
        path = repository / name
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repository, "add", "-A")
    git(repository, "commit", "-q", "-m", "change")
    return git(repository, "rev-parse", "HEAD")


def test_declarations_cover_function_and_data_shapes():
    found = dict(api_coverage.declarations("tlv/include/tlv/sample.h", HEADER))
    assert found == {"tlv_multi_line": "function", "tlv_attributed": "function",
                     "tlv_codec_sample": "data", "tlv_format_sample": "data", "tlv_table": "data"}


def test_unrecognized_declaration_fails_closed():
    with pytest.raises(ValueError, match="Unrecognized TLV_API declaration"):
        list(api_coverage.declarations("tlv/x.h", "TLV_API void (*tlv_handler(void))(int);"))


def test_references_ignore_comments_but_keep_literals():
    c_text = 'call(tlv_a); // tlv_b\n/* tlv_c */ const char* s = "//"; tlv_d(\'"\');'
    c_ids = api_coverage.IDENTIFIER.findall(api_coverage.strip_comments(Path("x.c"), c_text))
    assert {"tlv_a", "tlv_d"} <= set(c_ids) and not {"tlv_b", "tlv_c"} & set(c_ids)
    rust = "fn f<'a>(x: &'a u8) { ffi::tlv_e(x) } // tlv_f\n"
    rust_ids = set(api_coverage.IDENTIFIER.findall(api_coverage.strip_comments(Path("x.rs"), rust)))
    assert "tlv_e" in rust_ids and "tlv_f" not in rust_ids
    python = "value = _native.tlv_g  # tlv_h\n"
    python_ids = set(api_coverage.IDENTIFIER.findall(api_coverage.strip_comments(Path("x.py"), python)))
    assert "tlv_g" in python_ids and "tlv_h" not in python_ids


def test_configuration_requires_documented_ignores(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema": 1, "lock": "lock.json", "references": ["native"],
                                "ignore": [{"symbols": ["tlv_x"]}]}))
    with pytest.raises(ValueError, match="reason"):
        api_coverage.load_config(path)


def test_report_scopes_ignores_and_pin_diff(tmp_path):
    core = tmp_path / "core"
    core.mkdir()
    git(core, "init", "-q")
    old = commit(core, {
        "tlv/include/tlv/reader.h": "TLV_API int tlv_read(void);\nTLV_API int tlv_removed(void);\n",
        "tlv/include/tlv/endian.h": "TLV_API int tlv_read_u16_be(void);\n",
        "tlv/include/tlv/builtins/emv/emv.h": "extern TLV_API const tlv_format_t tlv_format_emv;\n"})
    new = commit(core, {
        "tlv/include/tlv/reader.h": "TLV_API int tlv_read(void);\nTLV_API int tlv_added(void);\n"
                                    "TLV_API int tlv_producer(void);\n",
        "tlv/include/tlv/endian.h": None, "tlv/include/tlv/builtins/emv/emv.h": None})
    binding = tmp_path / "binding"
    (binding / "native").mkdir(parents=True)
    git(binding, "init", "-q")
    config = {"schema": 1, "lock": "lock.json", "references": ["native"],
              "ignore": [{"reason": "primitives", "headers": ["tlv/endian.h"]},
                         {"reason": "producers", "symbols": ["tlv_producer", "tlv_gone"]}]}
    lock = {"repository": "OpenTLV/opentlv", "version": "1.0.0", "commit": old}
    base = commit(binding, {"lock.json": json.dumps(lock), "coverage.json": json.dumps(config),
                            "native/module.c": "tlv_read(); tlv_format_emv;\n"
                                               "/* tlv_added */ // tlv_added\n"})
    commit(binding, {"lock.json": json.dumps(lock | {"commit": new})})
    output = tmp_path / "report.json"
    summary = tmp_path / "summary.md"
    summary.write_text("previous\n")
    result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/api_coverage.py"),
                             "--config", "coverage.json", "--core", str(core), "--base", base,
                             "--output", str(output), "--summary", str(summary)],
                            cwd=binding, check=True, capture_output=True, text=True)
    report = json.loads(output.read_text())
    assert report["core"] == {"repository": "OpenTLV/opentlv", "version": "1.0.0", "commit": new}
    assert report["scopes"]["core"]["headers"]["tlv/reader.h"] == {
        "referenced": ["tlv_read"], "missing": ["tlv_added"], "ignored": ["tlv_producer"]}
    assert [report["scopes"]["core"][key] for key in ("referenced", "missing", "ignored")] == [1, 1, 1]
    assert report["scopes"]["builtins"]["headers"] == {}
    assert report["stale_ignores"] == ["tlv/endian.h", "tlv_gone"]
    assert report["diff"]["base"]["commit"] == old
    assert [(item["name"], item.get("status")) for item in report["diff"]["added"]] == [
        ("tlv_added", "missing"), ("tlv_producer", "ignored")]
    assert {item["name"] for item in report["diff"]["removed"]} == {
        "tlv_format_emv", "tlv_read_u16_be", "tlv_removed"}
    assert "| core | 1/2 (50.0 %) | 1 |" in result.stdout
    assert "1.0.0 `" + old[:12] + "` -> OpenTLV/opentlv 1.0.0 `" + new[:12] + "`: 2 added, 3 removed" \
        in result.stdout
    assert summary.read_text() == "previous\n" + result.stdout


def test_repository_configuration_matches_pinned_core_layout():
    config = api_coverage.load_config(ROOT / "cmake/api-coverage.json")
    assert config["lock"] == "cmake/core-artifact.json"
    assert config["references"] == ["native", "src"]
    assert all((ROOT / path).is_dir() for path in config["references"])


def test_coverage_job_is_informational():
    checks = yaml.load((ROOT / ".github/workflows/python-checks.yml").read_text(),
                       Loader=yaml.BaseLoader)
    job = checks["jobs"]["api_coverage"]
    assert job["continue-on-error"] == "true"
    assert job["if"] == "inputs.tier != 'main'"
    assert "api_coverage" not in checks["jobs"]["gate"]["needs"]
    checkout, report, upload = job["steps"]
    assert checkout["with"]["fetch-depth"] == "0"
    assert report["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert "scripts/api_coverage.py" in report["run"] and "$GITHUB_STEP_SUMMARY" in report["run"]
    assert upload["with"]["path"] == "build/api-coverage.json"
