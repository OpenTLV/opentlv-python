# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Report which pinned-Core TLV_API symbols a binding references.

Uses only the standard library and one JSON configuration, so other bindings
can reuse it unchanged. Run it from the binding's Git checkout.
"""

import argparse
import fnmatch
import io
import json
from pathlib import Path
import re
import subprocess
import tokenize

HEADERS = "tlv/include"
BUILTINS = "tlv/builtins/"
C_LIKE = {".c", ".h", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx", ".rs"}
# Literals are matched so that comment markers inside them are not comments.
C_TOKENS = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.[^\'\n]{0,8}|[^\'\\\n])\'|//[^\n]*|/\*.*?\*/',
                      re.S)
PREPROCESSOR = re.compile(r"^[ \t]*#(?:[^\n]*\\\n)*[^\n]*", re.M)
# Attribute-like macro invocations such as TLV_PRINTF(2, 3) are not part of a symbol's shape.
MACRO_CALL = re.compile(r"\b[A-Z][A-Z0-9_]*\s*\((?:[^()]|\([^()]*\))*\)")
# Parameters may nest one level, as in function-pointer parameters.
FUNCTION = re.compile(r"[^()]*?\b([A-Za-z_]\w*)\s*\([^()]*(?:\([^()]*\)[^()]*)*\)")
DATA = re.compile(r"[^()\[\]]*?\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)*")
IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


def git(repository, *args, data=None):
    result = subprocess.run(["git", "-C", str(repository), *map(str, args)], input=data,
                            capture_output=True, check=False)
    if result.returncode:
        raise ValueError(f"git {' '.join(map(str, args))} failed: "
                         + result.stderr.decode(errors="replace").strip())
    return result.stdout


def strip_comments(path, text, literals=True):
    if path.suffix in C_LIKE:
        return C_TOKENS.sub(lambda match: match.group() if literals and match.group()[0] in "\"'"
                            else " ", text)
    if path.suffix == ".py":
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        return " ".join(token.string for token in tokens if token.type != tokenize.COMMENT)
    return text


def declarations(path, text):
    """Yield (name, kind) for each TLV_API declaration; unknown shapes fail closed."""
    text = PREPROCESSOR.sub(" ", strip_comments(Path(path), text, literals=False))
    for statement in re.split(r"[;{}]", text):
        if not re.search(r"\bTLV_API\b", statement):
            continue
        statement = MACRO_CALL.sub(" ", " ".join(statement.split())).strip()
        for kind, shape in (("function", FUNCTION), ("data", DATA)):
            match = shape.fullmatch(statement)
            if match:
                yield match.group(1), kind
                break
        else:
            raise ValueError(f"Unrecognized TLV_API declaration in {path}: {statement}")


def core_symbols(repository, commit):
    listing = git(repository, "ls-tree", "-r", "-z", "--name-only", commit, "--", HEADERS)
    paths = [path for path in listing.decode().split("\0") if path.endswith(".h")]
    if not paths:
        raise ValueError(f"Core {commit} has no headers under {HEADERS}")
    blobs = git(repository, "cat-file", "--batch",
                data="".join(f"{commit}:{path}\n" for path in paths).encode())
    symbols = {}
    for path in paths:
        header, _, blobs = blobs.partition(b"\n")
        size = int(header.split()[2])
        text, blobs = blobs[:size].decode("utf-8"), blobs[size + 1:]
        for name, kind in declarations(path, text):
            symbols.setdefault(name, {"kind": kind, "header": path[len(HEADERS) + 1:]})
    return symbols


def references(root, directories):
    found = set()
    for directory in directories:
        if not (root / directory).is_dir():
            raise ValueError(f"Reference directory is missing: {directory}")
        for path in sorted((root / directory).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            found.update(IDENTIFIER.findall(strip_comments(path, text)))
    return found


def load_config(path):
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema") != 1 or not config.get("lock") or not config.get("references"):
        raise ValueError("API coverage configuration needs schema 1, lock and references")
    for entry in config.get("ignore", []):
        if not entry.get("reason") or not (entry.get("headers") or entry.get("symbols")):
            raise ValueError("Each ignore entry needs a reason and headers or symbols")
    return config


def ignored(config, symbols):
    """Map ignored symbols to their reason and list patterns that match nothing."""
    result, used = {}, set()
    for entry in config.get("ignore", []):
        for field, key in (("headers", "header"), ("symbols", None)):
            for pattern in entry.get(field, []):
                for name, symbol in symbols.items():
                    if fnmatch.fnmatchcase(symbol[key] if key else name, pattern):
                        result.setdefault(name, entry["reason"])
                        used.add(pattern)
    stale = [pattern for entry in config.get("ignore", [])
             for pattern in entry.get("headers", []) + entry.get("symbols", []) if pattern not in used]
    return result, stale


def status(name, found, ignore):
    return "ignored" if name in ignore else "referenced" if name in found else "missing"


def coverage(symbols, found, ignore):
    scopes = {scope: {"referenced": 0, "missing": 0, "ignored": 0, "headers": {}}
              for scope in ("core", "builtins")}
    for name, symbol in sorted(symbols.items()):
        scope = scopes["builtins" if symbol["header"].startswith(BUILTINS) else "core"]
        header = scope["headers"].setdefault(symbol["header"],
                                             {"referenced": [], "missing": [], "ignored": []})
        header[status(name, found, ignore)].append(name)
        scope[status(name, found, ignore)] += 1
    scopes = {name: {**scope, "headers": dict(sorted(scope["headers"].items()))}
              for name, scope in scopes.items()}
    return scopes


def pin(root, lock, ref=None):
    text = (root / lock).read_text(encoding="utf-8") if ref is None else git(root, "show", f"{ref}:{lock}")
    data = json.loads(text)
    return {"repository": data["repository"], "version": data.get("version"), "commit": data["commit"]}


def core_repository(root, local, pins):
    """Return a repository containing every pinned commit, fetching shallowly if needed."""
    repository = local.resolve() if local else root / "build/api-coverage/core.git"
    if not local and not repository.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(repository)], check=True)
    for item in pins:
        revision = item["commit"]
        exists = subprocess.run(["git", "-C", str(repository), "cat-file", "-e",
                                 revision + "^{commit}"], capture_output=True).returncode == 0
        if not exists:
            if local:
                raise ValueError(f"Core {revision} is not in {repository}; fetch it first")
            git(repository, "fetch", "-q", "--depth=1", "--no-tags",
                f"https://github.com/{item['repository']}.git", revision)
            revision = "FETCH_HEAD"
        item["commit"] = git(repository, "rev-parse", "--verify",
                             revision + "^{commit}").decode().strip()
    return repository


def ratio(scope):
    considered = scope["referenced"] + scope["missing"]
    if not considered:
        return "-"
    return f"{scope['referenced']}/{considered} ({100 * scope['referenced'] / considered:.1f} %)"


def describe(item):
    version = f" {item['version']}" if item.get("version") else ""
    return f"{item['repository']}{version} `{item['commit'][:12]}`"


def markdown(report):
    lines = ["## Core API coverage", "",
             f"{describe(report['core'])}; references in "
             + ", ".join(f"`{path}`" for path in report["references"]) + ".", "",
             "| Scope | Referenced | Ignored |", "| --- | ---: | ---: |"]
    lines += [f"| {name} | {ratio(scope)} | {scope['ignored']} |"
              for name, scope in report["scopes"].items()]
    if report["stale_ignores"]:
        lines += ["", "Ignore patterns matching no symbol: "
                  + ", ".join(f"`{pattern}`" for pattern in report["stale_ignores"])]
    diff = report.get("diff")
    if diff is not None:
        lines += ["", "### Core pin change", ""]
        if diff["base"]["commit"] == report["core"]["commit"]:
            lines.append(f"Core pin unchanged from base {describe(diff['base'])}.")
        else:
            lines += [f"{describe(diff['base'])} -> {describe(report['core'])}: "
                      f"{len(diff['added'])} added, {len(diff['removed'])} removed."]
            changes = [("added", item) for item in diff["added"]] + \
                      [("removed", item) for item in diff["removed"]]
            if changes:
                lines += ["", "| Change | Symbol | Kind | Header | Status |",
                          "| --- | --- | --- | --- | --- |"]
                lines += [f"| {change} | `{item['name']}` | {item['kind']} | `{item['header']}` "
                          f"| {item.get('status', '-')} |" for change, item in changes]
    for name, scope in report["scopes"].items():
        lines += ["", f"<details><summary>{name} headers</summary>", "",
                  "| Header | Referenced | Ignored | Not referenced |", "| --- | ---: | ---: | --- |"]
        for header, entry in scope["headers"].items():
            counts = {key: len(entry[key]) for key in ("referenced", "missing", "ignored")}
            lines.append(f"| `{header}` | {ratio(counts)} | {counts['ignored']} | "
                         + ", ".join(f"`{symbol}`" for symbol in entry["missing"]) + " |")
        lines += ["", "</details>"]
    return "\n".join(lines) + "\n"


def report(root, config, core=None, commit=None, base=None, base_commit=None):
    head = pin(root, config["lock"])
    if commit:
        head.update(commit=commit, version=None)
    previous = None
    if base:
        previous = pin(root, config["lock"], base)
    elif base_commit:
        previous = {"repository": head["repository"], "version": None, "commit": base_commit}
    repository = core_repository(root, core, [head] + ([previous] if previous else []))
    symbols = core_symbols(repository, head["commit"])
    found = references(root, config["references"])
    ignore, stale = ignored(config, symbols)
    result = {"schema": 1, "core": head, "references": config["references"],
              "scopes": coverage(symbols, found, ignore), "stale_ignores": stale}
    if previous:
        old = core_symbols(repository, previous["commit"])
        result["diff"] = {
            "base": previous,
            "added": [{"name": name, **symbols[name], "status": status(name, found, ignore)}
                      for name in sorted(symbols.keys() - old.keys())],
            "removed": [{"name": name, **old[name]} for name in sorted(old.keys() - symbols.keys())]}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("cmake/api-coverage.json"))
    parser.add_argument("--core", type=Path,
                        help="existing Core Git repository; default: shallow fetch under build/")
    parser.add_argument("--commit", help="Core revision to measure instead of the locked commit")
    previous = parser.add_mutually_exclusive_group()
    previous.add_argument("--base", help="binding revision whose Core lock is the previous pin")
    previous.add_argument("--base-commit", help="previous Core revision")
    parser.add_argument("--output", type=Path, help="write the JSON report")
    parser.add_argument("--summary", type=Path, help="append the Markdown summary")
    args = parser.parse_args()
    try:
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
        result = report(root, load_config(args.config), args.core, args.commit,
                        args.base, args.base_commit)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        parser.exit(1, f"API coverage failed: {error}\n")
    text = markdown(result)
    print(text, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as summary:
            summary.write(text)


if __name__ == "__main__":
    main()
