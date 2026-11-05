#!/usr/bin/env python3
"""Check that the remake's Config.luau still matches the measurement ledger.

Reads Config.luau (the template's single source of constants) and its Config.Evidence map:
  ["Movement.WalkSpeed"] = "MS-004"                      direct: value must equal the measurement
  ["World.Gravity"] = "derived: MS-001, MS-002 (remake_calc jump)"   derived: IDs must exist
  ["Camera.FieldOfView"] = "Roblox default (creator docs)"           documented default
  ["Movement.CoyoteTime"] = "ASSUMED: preset platformer"             assumption (warning)

Reports:
  ERROR    an Evidence entry cites a missing or inaccessible EV/MS id; a direct entry's value
           differs from its measurement by more than max(uncertainty, 1%)
  WARNING  ASSUMED values; Evidence for a key that Config does not define; values whose comment
           cites an id but which have no Evidence entry; with --require-sourced, unsourced numbers
           in World, Movement and Camera
  NOTE     measurements that neither Config nor the breakdown uses

Usage:
  python config_check.py remake [--config path/to/Config.luau] [--json] [--strict] [--require-sourced]
Exit: 0 no errors (warnings allowed unless --strict), 1 errors, 2 bad input.
Without --config, the first */Remake/Config.luau under the project (remake/..) is used.
"""

from __future__ import annotations

import argparse
import ast
import json
import operator
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "config_check"
SCHEMA = 1
ID_RE = re.compile(r"\b(?:EV|MS)-\d{3,}\b")
KEY_TABLE_RE = re.compile(r"^\s*(?:Config\.)?([A-Za-z_]\w*)\s*=\s*\{")
KEY_VALUE_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*,?\s*$")
EVIDENCE_RE = re.compile(r'^\s*\[\s*"([^"]+)"\s*\]\s*=\s*"((?:[^"\\]|\\.)*)"')
SOURCED_SECTIONS = ("World", "Movement", "Camera")
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def safe_number(expr: str):
    """Evaluate a numeric literal or simple arithmetic (1 / 0.28); None for anything else."""
    try:
        node = ast.parse(expr.strip(), mode="eval").body
    except SyntaxError:
        return None

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return float(n.value)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            v = ev(n.operand)
            return None if v is None else -v
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            a, b = ev(n.left), ev(n.right)
            if a is None or b is None or (isinstance(n.op, ast.Div) and b == 0):
                return None
            return OPS[type(n.op)](a, b)
        return None

    return ev(node)


def strip_strings(line: str) -> str:
    return re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)


def parse_config(path: Path) -> tuple[dict, dict, list[str]]:
    """Return (values, evidence, problems). values: path -> {value, raw, line, comment}."""
    values: dict[str, dict] = {}
    evidence: dict[str, dict] = {}
    problems: list[str] = []
    stack: list[str] = []
    in_block_comment = False
    text = path.read_text(encoding="utf-8")
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw
        if in_block_comment:
            if "]]" in line:
                in_block_comment = False
                line = line.split("]]", 1)[1]
            else:
                continue
        if "--[[" in line:
            before = line.split("--[[", 1)[0]
            if "]]" not in line.split("--[[", 1)[1]:
                in_block_comment = True
            line = before
        code, _, comment = strip_strings(line).partition("--")
        comment = raw.partition("--")[2] if "--" in raw else ""
        opens, closes = code.count("{"), code.count("}")
        if stack and stack[0] == "Evidence":
            m = EVIDENCE_RE.match(raw)
            if m:
                evidence[m.group(1)] = {"text": m.group(2), "line": n}
        m = KEY_TABLE_RE.match(code)
        if m and opens > closes:
            if code.strip().startswith("Config.") or stack:
                stack.append(m.group(1))
            continue
        if stack and stack[0] != "Evidence" and opens == closes:
            kv = KEY_VALUE_RE.match(code.rstrip())
            if kv:
                key, expr = kv.group(1), kv.group(2).strip().rstrip(",")
                expr = re.sub(r"\s*::.*$", "", expr)
                full = ".".join(stack + [key])
                values[full] = {"value": safe_number(expr), "raw": expr, "line": n, "comment": comment.strip()}
        for _ in range(max(0, closes - opens)):
            if stack:
                stack.pop()
    if not values:
        problems.append("no Config.<Section> = { ... } values found; is this the template's Config.luau?")
    return values, evidence, problems


def find_config(remake: Path) -> Path | None:
    project = remake.resolve().parent
    for p in sorted(project.rglob("Config.luau")):
        if p.parent.name == "Remake" and "node_modules" not in p.parts:
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("remake", type=Path)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--require-sourced", action="store_true", help="unsourced World/Movement/Camera numbers are warnings")
    args = ap.parse_args()
    if not args.remake.is_dir():
        print(f"error: remake directory not found: {args.remake}", file=sys.stderr)
        return rc.EXIT_USAGE
    cfg = args.config or find_config(args.remake)
    if not cfg or not cfg.is_file():
        print("error: Config.luau not found; pass --config", file=sys.stderr)
        return rc.EXIT_USAGE

    def ledger(name, key):
        p = args.remake / name
        if not p.is_file():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return {i["id"]: i for i in data.get(key, []) if isinstance(i, dict) and "id" in i}

    ev = ledger("evidence.json", "evidence")
    ms = ledger("measurements.json", "measurements")
    values, evidence, problems = parse_config(cfg)
    errors, warnings, notes = [], [], []

    def add(bucket, line, msg, fix):
        bucket.append({"path": str(cfg), "line": line, "message": msg, "fix": fix})

    for p in problems:
        add(errors, 0, p, "point --config at src/shared/Remake/Config.luau")
    used: set[str] = set()
    assumptions, defaults, direct_ok = [], [], 0
    for key, entry in evidence.items():
        text, line = entry["text"], entry["line"]
        ids = ID_RE.findall(text)
        used.update(ids)
        if key not in values and not any(k.startswith(key + ".") for k in values):
            add(warnings, line, f"Evidence for {key}, which Config does not define", "fix the key path or remove the entry")
        if text.strip().upper().startswith("ASSUMED"):
            assumptions.append(key)
            add(warnings, line, f"{key} is ASSUMED ({text})", "measure it and replace the evidence with an MS id")
            continue
        if not ids:
            defaults.append(key)
            continue
        for i in ids:
            src = ms.get(i) if i.startswith("MS-") else ev.get(i)
            if src is None:
                add(errors, line, f"{key} cites {i}, which is not in the ledgers", "fix the id or add it with ledger.py")
                continue
            backing = [ev.get(x) for x in (src.get("evidence") or [])] if i.startswith("MS-") else [src]
            if not any(b and b.get("accessible") for b in backing):
                add(errors, line, f"{key} cites {i}, which rests on inaccessible evidence", "cite evidence you actually opened")
        direct = re.match(r"^\s*(MS-\d{3,})\b", text) and len(ids) == 1 and "derived" not in text.lower()
        if direct and key in values and ids[0] in ms:
            cv, m = values[key]["value"], ms[ids[0]]
            try:
                mv, unc = float(m["value"]), float(m.get("uncertainty") or 0)
            except (TypeError, ValueError):
                continue
            if cv is None:
                continue
            tol = max(unc, 0.01 * abs(mv), 1e-9)
            if abs(cv - mv) > tol:
                add(errors, values[key]["line"], f"{key} = {cv:g} but {ids[0]} measured {mv:g} ± {unc:g} {m.get('unit', '')}",
                    "update Config (or the measurement); if the value is converted, write 'derived: MS-…' in Config.Evidence")
            else:
                direct_ok += 1
    for key, v in values.items():
        cids = ID_RE.findall(v["comment"])
        used.update(cids)
        if cids and key not in evidence:
            add(warnings, v["line"], f"{key} comment cites {', '.join(cids)} but Config.Evidence has no entry for it",
                f'add ["{key}"] = "{cids[0]}" to Config.Evidence')
        for i in cids:
            if i not in ms and i not in ev:
                add(errors, v["line"], f"{key} comment cites {i}, which is not in the ledgers", "fix the id")
    unsourced = [k for k, v in values.items() if k.split(".")[0] in SOURCED_SECTIONS and v["value"] is not None
                 and k not in evidence and not ID_RE.search(v["comment"])]
    if args.require_sourced:
        for k in unsourced:
            add(warnings, values[k]["line"], f"{k} has no evidence", "measure it, cite a default, or mark it ASSUMED")
    bd = args.remake / "breakdown.md"
    if bd.is_file():
        used.update(ID_RE.findall(bd.read_text(encoding="utf-8")))
    unused = [mid for mid in sorted(ms) if mid not in used]
    if unused:
        add(notes, 0, f"{len(unused)} measurements not used by Config or the breakdown: {', '.join(unused)}",
            "cite them in Config.Evidence / breakdown entries, or drop them")

    failed = bool(errors) or (args.strict and bool(warnings))
    summary = {"config": str(cfg), "values": len(values), "evidence_entries": len(evidence), "direct_matches": direct_ok,
               "defaults": len(defaults), "assumptions": assumptions, "unsourced": len(unsourced), "unused_measurements": unused}
    if args.json:
        print(json.dumps({"tool": TOOL, "schema": SCHEMA, "root": str(args.remake), "files_checked": [str(cfg)],
                          "error_count": len(errors), "warning_count": len(warnings), "errors": errors,
                          "warnings": warnings, "note_count": len(notes), "notes": notes, "truncated": False,
                          "summary": summary, "pass": not failed}, indent=2))
    else:
        for lvl, bucket in (("ERROR", errors), ("WARNING", warnings), ("NOTE", notes)):
            for i in bucket:
                loc = f"{i['path']}:{i['line']}" if i["line"] else i["path"]
                print(f"{lvl} {loc}: {i['message']}")
                print(f"  fix: {i['fix']}")
        print(f"Summary: {len(values)} values, {len(evidence)} evidence entries ({direct_ok} direct matches, "
              f"{len(defaults)} defaults, {len(assumptions)} assumed), {len(unsourced)} unsourced in "
              f"{'/'.join(SOURCED_SECTIONS)}; {len(errors)} errors, {len(warnings)} warnings"
              + (" [strict]" if args.strict else "") + f" -> {'FAIL' if failed else 'pass'}")
    return rc.EXIT_FAIL if failed else rc.EXIT_OK


if __name__ == "__main__":
    rc.run_main(main)
