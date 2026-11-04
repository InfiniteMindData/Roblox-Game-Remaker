#!/usr/bin/env python3
"""Cross-check Roblox API references in Luau and Markdown against the official API reference.

The Roblox engine API reference is published as YAML in the open-source creator-docs repo
(github.com/Roblox/creator-docs, content/en-us/reference/engine). This tool loads it and checks:

  Luau files (.luau, .lua)
    - Enum.<Enum>.<Item> exist (ERROR) and are not deprecated (WARNING)
    - game:GetService("X") names a service; Instance.new("X") names a creatable, current class
    - :IsA("X") / FindFirstChildOfClass("X") / FindFirstAncestorOfClass("X") name real classes
    - <ServiceVar>.Member / <ServiceVar>:Method where the variable is named after its service
      (local Lighting = game:GetService("Lighting")) refer to real, current members
    - PascalCase members that exist nowhere in the API and are not declared in the checked code
      (WARNING; catches typos)
    Inline markers: "-- api-check: ignore" skips the unknown-member check on that line (for
    non-engine APIs such as PlayerModule methods); "-- api-check: allow-deprecated" accepts a
    deliberate deprecated service (for example a documented fallback).
  Markdown files (.md)
    - Enum.<Enum>.<Item> and `Class.Member` mentions exist; deprecated ones are only flagged when
      the line does not say "deprecated" or "superseded"

Usage:
  python tools/check_roblox_api.py --docs /path/to/creator-docs/content/en-us/reference/engine PATH...
Exit: 0 clean, 1 errors (or warnings with --strict), 2 bad arguments.
Requires PyYAML (pip install pyyaml).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("error: PyYAML is required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

ENUM_RE = re.compile(r"\bEnum\.([A-Za-z][A-Za-z0-9]*)(?:\.([A-Za-z_][A-Za-z0-9_]*))?")
GETSERVICE_RE = re.compile(r"GetService\(\s*\"([A-Za-z]+)\"\s*\)")
NEW_RE = re.compile(r"Instance\.new\(\s*\"([A-Za-z]+)\"")
CLASSARG_RE = re.compile(r"(?:IsA|FindFirstChildOfClass|FindFirstAncestorOfClass|FindFirstChildWhichIsA)\(\s*\"([A-Za-z]+)\"")
MEMBER_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*([.:])\s*([A-Z][A-Za-z0-9]*)\b")
DECL_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\s*(?:=|:)")
MD_MEMBER_RE = re.compile(r"`([A-Z][A-Za-z0-9]+)[.:]([A-Z][A-Za-z0-9]*)(?:\(\))?`")
COMMENT_RE = re.compile(r"--.*$")
DEPRECATION_WORDS = ("deprecated", "superseded", "replace", "→", "->")


class Api:
    def __init__(self, root: Path):
        if not (root / "classes").is_dir() or not (root / "enums").is_dir():
            raise SystemExit(f"error: {root} does not look like content/en-us/reference/engine")
        self.classes: dict[str, dict] = {}
        self.enums: dict[str, dict] = {}
        self.datatypes: dict[str, dict] = {}
        for p in (root / "classes").glob("*.yaml"):
            d = yaml.safe_load(p.read_text(encoding="utf-8"))
            members = {}
            for sec in ("properties", "methods", "events", "callbacks"):
                for m in d.get(sec) or []:
                    name = re.split(r"[.:]", m["name"])[-1]
                    members[name] = members.get(name, True) and bool(m.get("deprecation_message"))
            self.classes[d["name"]] = {"members": members, "inherits": d.get("inherits") or [],
                                       "tags": d.get("tags") or [], "deprecated": bool(d.get("deprecation_message"))}
        for p in (root / "enums").glob("*.yaml"):
            d = yaml.safe_load(p.read_text(encoding="utf-8"))
            self.enums[d["name"]] = {"items": {i["name"]: bool(i.get("deprecation_message")) for i in d.get("items") or []},
                                     "deprecated": bool(d.get("deprecation_message"))}
        dt_dir = root / "datatypes"
        if dt_dir.is_dir():
            for p in dt_dir.glob("*.yaml"):
                d = yaml.safe_load(p.read_text(encoding="utf-8"))
                members = {}
                for sec in ("constructors", "properties", "methods", "constants", "functions"):
                    for m in d.get(sec) or []:
                        members[re.split(r"[.:]", m["name"])[-1]] = bool(m.get("deprecation_message"))
                self.datatypes[d["name"]] = {"members": members}
        self.all_members: dict[str, bool] = {}
        for c in self.classes.values():
            for name, dep in c["members"].items():
                self.all_members[name] = self.all_members.get(name, True) and dep
        for d in self.datatypes.values():
            for name, dep in d["members"].items():
                self.all_members[name] = self.all_members.get(name, True) and dep
        for e in self.enums.values():
            for name in e["items"]:
                self.all_members.setdefault(name, False)
        for extra in ("Name", "Value", "EnumType"):  # EnumItem members
            self.all_members[extra] = False

    def lineage(self, cls: str) -> list[str]:
        seen, order, stack = set(), [], [cls]
        while stack:
            c = stack.pop(0)
            if c in seen or c not in self.classes:
                continue
            seen.add(c)
            order.append(c)
            stack.extend(self.classes[c]["inherits"])
        return order

    def member(self, cls: str, name: str) -> bool | None:
        """None if missing; otherwise True when deprecated everywhere it is defined in the lineage."""
        if cls in self.datatypes:
            m = self.datatypes[cls]["members"]
            return m[name] if name in m else None
        found = None
        for c in self.lineage(cls):
            if name in self.classes[c]["members"]:
                dep = self.classes[c]["members"][name]
                found = dep if found is None else (found and dep)
        return found


BLOCK_COMMENT_RE = re.compile(r"--\[(=*)\[.*?\]\1\]", re.DOTALL)
STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"|`[^`]*`|\'(?:[^\'\\]|\\.)*\'')


def strip_block_comments(text: str) -> str:
    """Remove --[[ ]] comments but keep line numbers stable."""
    return BLOCK_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def scan_luau(path: Path, text: str, api: Api, declared: set[str], issues: list[dict]) -> None:
    for n, raw in enumerate(strip_block_comments(text).splitlines(), 1):
        code = COMMENT_RE.sub("", raw)
        line = STRING_RE.sub('""', code)

        def add(level, msg):
            issues.append({"level": level, "path": str(path), "line": n, "message": msg})

        for m in ENUM_RE.finditer(line):
            enum, item = m.group(1), m.group(2)
            if enum not in api.enums:
                add("ERROR", f"unknown enum Enum.{enum}")
                continue
            if api.enums[enum]["deprecated"]:
                add("WARNING", f"deprecated enum Enum.{enum}")
            if item and item not in ("Name", "Value", "GetEnumItems", "FromName", "FromValue"):
                if item not in api.enums[enum]["items"]:
                    add("ERROR", f"unknown enum item Enum.{enum}.{item}")
                elif api.enums[enum]["items"][item]:
                    add("WARNING", f"deprecated enum item Enum.{enum}.{item}")
        for m in GETSERVICE_RE.finditer(code):
            c = api.classes.get(m.group(1))
            if not c:
                add("ERROR", f"GetService: unknown class {m.group(1)}")
            elif "Service" not in c["tags"]:
                add("WARNING", f"GetService: {m.group(1)} is not tagged as a service")
            elif c["deprecated"] and "api-check: allow-deprecated" not in raw:
                add("WARNING", f"deprecated service {m.group(1)}")
        for m in NEW_RE.finditer(code):
            c = api.classes.get(m.group(1))
            if not c:
                add("ERROR", f"Instance.new: unknown class {m.group(1)}")
            elif "NotCreatable" in c["tags"]:
                add("ERROR", f"Instance.new: {m.group(1)} is not creatable")
            elif c["deprecated"]:
                add("WARNING", f"Instance.new: {m.group(1)} is deprecated")
        for m in CLASSARG_RE.finditer(code):
            if m.group(1) not in api.classes:
                add("ERROR", f"unknown class name {m.group(1)!r}")
        ignore_unknown = "api-check: ignore" in raw
        for m in MEMBER_RE.finditer(line):
            obj, sep, name = m.group(1), m.group(2), m.group(3)
            if obj == "Enum" or line[max(0, m.start() - 5):m.start()].endswith("Enum."):
                continue
            if sep == ":" and not re.match(r"\s*[(\"'{`]", line[m.end():]):
                continue  # a type annotation (x: Type), not a method call
            if ignore_unknown:
                continue
            if obj in api.classes and obj in SERVICE_VARS:
                dep = api.member(obj, name)
                if dep is None:
                    add("ERROR", f"{obj}{sep}{name}: no such member on {obj}")
                elif dep:
                    add("WARNING", f"{obj}{sep}{name} is deprecated")
                continue
            if obj in api.datatypes:
                dep = api.member(obj, name)
                if dep is None:
                    add("ERROR", f"{obj}.{name}: no such member on datatype {obj}")
                continue
            if name in declared:
                continue
            if name not in api.all_members:
                add("WARNING", f"{obj}{sep}{name}: '{name}' is not a Roblox API member and is not declared in the checked code")
            elif api.all_members[name]:
                add("WARNING", f"{obj}{sep}{name}: '{name}' only exists as a deprecated API member")


def scan_md(path: Path, text: str, api: Api, issues: list[dict]) -> None:
    in_code = False
    section_dep = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
        if not in_code and line.startswith("#"):
            section_dep = "deprecated" in line.lower()
        lower = line.lower()
        mentions_dep = section_dep or any(w in lower for w in DEPRECATION_WORDS)

        def add(level, msg):
            issues.append({"level": level, "path": str(path), "line": n, "message": msg})

        for m in ENUM_RE.finditer(line):
            enum, item = m.group(1), m.group(2)
            if enum not in api.enums:
                add("ERROR", f"unknown enum Enum.{enum}")
            elif item and item not in api.enums[enum]["items"] and item not in ("Name", "Value"):
                add("ERROR", f"unknown enum item Enum.{enum}.{item}")
            elif item and api.enums[enum]["items"].get(item) and not mentions_dep:
                add("WARNING", f"deprecated enum item Enum.{enum}.{item} mentioned without saying so")
        if in_code:
            continue
        for m in MD_MEMBER_RE.finditer(line):
            cls, name = m.group(1), m.group(2)
            if cls not in api.classes and cls not in api.datatypes:
                continue
            dep = api.member(cls, name)
            if dep is None:
                add("ERROR", f"`{cls}.{name}`: no such member")
            elif dep and not mentions_dep:
                add("WARNING", f"`{cls}.{name}` is deprecated but the line does not say so")


SERVICE_VARS: set[str] = set()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", type=Path, required=True, help="creator-docs content/en-us/reference/engine directory")
    ap.add_argument("paths", type=Path, nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    api = Api(args.docs)
    files: list[Path] = []
    for p in args.paths:
        if p.is_dir():
            files += sorted(x for x in p.rglob("*") if x.suffix in (".luau", ".lua", ".md"))
        elif p.is_file():
            files.append(p)
        else:
            print(f"error: not found: {p}", file=sys.stderr)
            return 2
    luau = [f for f in files if f.suffix in (".luau", ".lua")]
    declared: set[str] = set()
    for f in luau:
        text = f.read_text(encoding="utf-8")
        body = "\n".join(COMMENT_RE.sub("", ln) for ln in strip_block_comments(text).splitlines())
        declared.update(DECL_RE.findall(STRING_RE.sub('""', body)))
        for m in re.finditer(r"local\s+([A-Z][A-Za-z]+)\s*=\s*game:GetService\(\"([A-Za-z]+)\"\)", text):
            if m.group(1) == m.group(2):
                SERVICE_VARS.add(m.group(1))
    issues: list[dict] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        if f.suffix == ".md":
            scan_md(f, text, api, issues)
        else:
            scan_luau(f, text, api, declared, issues)
    errors = [i for i in issues if i["level"] == "ERROR"]
    warnings = [i for i in issues if i["level"] == "WARNING"]
    if args.json:
        print(json.dumps({"files_checked": len(files), "errors": errors, "warnings": warnings}, indent=2))
    else:
        for i in issues:
            print(f"{i['level']} {i['path']}:{i['line']}: {i['message']}")
        print(f"Summary: {len(files)} files, {len(api.classes)} classes / {len(api.enums)} enums loaded; "
              f"{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
