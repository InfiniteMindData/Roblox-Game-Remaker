#!/usr/bin/env python3
"""Validate a remake breakdown against its evidence and measurement ledgers.

TARGET is the remake/ directory (or a breakdown.md inside one). Checks, per the format in
references/game-breakdown.md:
  - every entry has a valid ID, status, roblox plan and accept test
  - cited EV-/MS- IDs exist; nothing relies only on inaccessible evidence
  - VERIFIED cites an accessible authoritative source; MEASURED cites an accessible measurement
    or footage and has value lines with +/- uncertainty
  - UNKNOWN entries have an open question; ASSUMED entries are reported
  - every category has an entry or an "n/a" coverage line
  - measurements have value, unit, uncertainty and method

Output: one "ERROR|WARNING path:line: message" plus "fix:" line per issue, then a Summary line.
Exit: 0 no errors (warnings allowed unless --strict), 1 errors (or warnings with --strict),
2 target missing or not a remake workspace.

Examples:
  python breakdown_check.py remake
  python breakdown_check.py remake --strict --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "breakdown_check"
SCHEMA = 1
CATEGORIES = {
    "CTRL": "Controls", "MOVE": "Movement and physics", "CAM": "Camera", "MECH": "Mechanics",
    "CHAR": "Characters", "ANIM": "Animations", "UI": "UI", "ENV": "Environment", "VFX": "Visual effects",
    "AUD": "Audio", "AI": "AI", "SYS": "Systems", "VR": "VR",
}
STATUSES = ("VERIFIED", "MEASURED", "OBSERVED", "INFERRED", "ASSUMED", "UNKNOWN")
AUTHORITATIVE = {"doc", "patch-notes", "talk", "screenshot", "capture", "user-statement"}
FOOTAGE = {"video", "screenshot", "capture"}
EV_TYPES = {"video", "screenshot", "capture", "doc", "patch-notes", "wiki", "community-data", "talk", "forum",
            "user-statement", "measurement"}
HEAD_RE = re.compile(r"^###\s+([A-Z]+)-(\d{3,})\s*[:\-—]\s*(.+?)\s*$")
FIELD_RE = re.compile(r"^-\s*([a-z_]+)\s*:\s*(.*)$")
NA_RE = re.compile(r"^-\s*n/a\s*:\s*([A-Z]+)\b(.*)$", re.IGNORECASE)
VALUE_RE = re.compile(r"^\s*([A-Za-z_][\w.\-]*)\s*=\s*(-?[\d.]+(?:e-?\d+)?)\s*(?:±|\+/-|\+-)\s*([\d.]+(?:e-?\d+)?)\s*(\S.*)?$")
ID_RE = re.compile(r"\b(?:EV|MS)-\d{3,}\b")
TBD = {"", "tbd", "todo", "?", "-"}


class Report:
    def __init__(self, max_issues: int | None):
        self.errors: list[dict] = []
        self.warnings: list[dict] = []
        self.max = max_issues

    def add(self, level: str, path: Path, line: int, msg: str, fix: str) -> None:
        item = {"path": str(path), "line": line, "message": msg, "fix": fix}
        (self.errors if level == "ERROR" else self.warnings).append(item)


def load_ledger(path: Path, key: str, report: Report) -> dict[str, dict]:
    if not path.is_file():
        report.add("WARNING", path, 0, f"{path.name} not found", f"create it (breakdown_init.py) and record every {key[:-1]} there")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.add("ERROR", path, exc.lineno, f"invalid JSON: {exc.msg}", "fix the JSON syntax")
        return {}
    items = data.get(key) if isinstance(data, dict) else data
    if not isinstance(items, list):
        report.add("ERROR", path, 0, f"expected a '{key}' list", f'use {{"{key}": [...]}}')
        return {}
    out: dict[str, dict] = {}
    for i, item in enumerate(items):
        iid = item.get("id") if isinstance(item, dict) else None
        if not iid:
            report.add("ERROR", path, 0, f"{key}[{i}] has no id", "give every entry an id such as EV-001 or MS-001")
            continue
        if iid in out:
            report.add("ERROR", path, 0, f"duplicate id {iid}", "make ids unique")
        out[iid] = item
    return out


def check_ledgers(ev: dict, ms: dict, ev_path: Path, ms_path: Path, report: Report) -> None:
    for iid, e in ev.items():
        if not iid.startswith("EV-"):
            report.add("ERROR", ev_path, 0, f"evidence id {iid} should start with EV-", "rename it EV-###")
        if e.get("type") not in EV_TYPES:
            report.add("WARNING", ev_path, 0, f"{iid}: unknown type {e.get('type')!r}", "use one of: " + ", ".join(sorted(EV_TYPES)))
        if "accessible" not in e:
            report.add("ERROR", ev_path, 0, f"{iid}: missing 'accessible'", "set accessible true or false; never omit it")
        if e.get("accessible") and e.get("type") in FOOTAGE and not e.get("analysis"):
            report.add("WARNING", ev_path, 0, f"{iid}: footage without an 'analysis' description", "record which tools/frames were used")
    for iid, m in ms.items():
        if not iid.startswith("MS-"):
            report.add("ERROR", ms_path, 0, f"measurement id {iid} should start with MS-", "rename it MS-###")
        for field in ("value", "unit", "uncertainty", "method", "evidence"):
            if m.get(field) in (None, "", []):
                report.add("ERROR", ms_path, 0, f"{iid}: missing '{field}'", "measurements need value, unit, uncertainty, method and evidence")
        for ref in m.get("evidence") or []:
            src = ev.get(ref)
            if src is None:
                report.add("ERROR", ms_path, 0, f"{iid}: cites unknown evidence {ref}", "add it to evidence.json or fix the id")
            elif not src.get("accessible"):
                report.add("ERROR", ms_path, 0, f"{iid}: measured from inaccessible evidence {ref}",
                           "a measurement needs footage you actually opened; re-measure or remove it")


def parse_breakdown(path: Path, report: Report):
    entries, na, current = [], {}, None
    lines = path.read_text(encoding="utf-8").splitlines()
    in_comment = False
    for n, raw in enumerate(lines, 1):
        line = raw.rstrip()
        if "<!--" in line:
            in_comment = "-->" not in line
            continue
        if in_comment:
            in_comment = "-->" not in line
            continue
        m = HEAD_RE.match(line)
        if m:
            current = {"prefix": m.group(1), "id": f"{m.group(1)}-{m.group(2)}", "title": m.group(3), "line": n,
                       "fields": {}, "values": [], "field_lines": {}}
            entries.append(current)
            continue
        if line.startswith("### "):
            report.add("ERROR", path, n, f"heading is not a valid entry: {line[4:]!r}", "use '### PREFIX-001: Title'")
            current = None
            continue
        if line.startswith("## "):
            current = None
        nm = NA_RE.match(line)
        if nm:
            na[nm.group(1).upper()] = (n, nm.group(2).strip())
            continue
        fm = FIELD_RE.match(line)
        if fm and current is not None:
            key, val = fm.group(1), fm.group(2).strip()
            if key == "value":
                current["values"].append((n, val))
            else:
                if key in current["fields"]:
                    report.add("WARNING", path, n, f"{current['id']}: duplicate '{key}' line", "keep one; only 'value' may repeat")
                current["fields"][key] = val
                current["field_lines"][key] = n
    return entries, na


def check_entries(entries, na, ev, ms, path: Path, report: Report) -> dict:
    seen = {}
    counts = {s: 0 for s in STATUSES}
    by_cat = {c: 0 for c in CATEGORIES}
    assumptions, questions = [], []
    for e in entries:
        eid, ln, f = e["id"], e["line"], e["fields"]
        if e["prefix"] not in CATEGORIES:
            report.add("ERROR", path, ln, f"{eid}: unknown prefix {e['prefix']}", "use one of: " + ", ".join(CATEGORIES))
        else:
            by_cat[e["prefix"]] += 1
        if eid in seen:
            report.add("ERROR", path, ln, f"duplicate id {eid} (first at line {seen[eid]})", "renumber one of them")
        seen[eid] = ln
        status = f.get("status", "").upper()
        if status not in STATUSES:
            report.add("ERROR", path, ln, f"{eid}: status {f.get('status')!r} is not valid", "use " + ", ".join(STATUSES))
            continue
        counts[status] += 1
        for key in ("roblox", "accept"):
            val = f.get(key)
            if val is None:
                report.add("ERROR", path, ln, f"{eid}: missing '{key}:' line", f"add '- {key}: ...'")
            elif val.strip().lower() in TBD:
                what = "the Roblox implementation plan" if key == "roblox" else "a checkable acceptance test with a tolerance"
                report.add("WARNING", path, e["field_lines"].get(key, ln), f"{eid}: '{key}' is TBD", f"write {what} before building this entry")
        ref_ids = ID_RE.findall(f.get("evidence", ""))
        accessible_sources = []
        for rid in ref_ids:
            if rid.startswith("EV-"):
                src = ev.get(rid)
                if src is None:
                    report.add("ERROR", path, ln, f"{eid}: cites unknown evidence {rid}", "add it to evidence.json or fix the id")
                elif src.get("accessible"):
                    accessible_sources.append(("EV", src))
                else:
                    report.add("WARNING", path, ln, f"{eid}: cites inaccessible evidence {rid}", "it cannot support a claim; find an accessible source")
            else:
                meas = ms.get(rid)
                if meas is None:
                    report.add("ERROR", path, ln, f"{eid}: cites unknown measurement {rid}", "add it to measurements.json or fix the id")
                    continue
                backing = [ev.get(x) for x in meas.get("evidence") or []]
                if any(b and b.get("accessible") for b in backing):
                    accessible_sources.append(("MS", meas))
        if status in ("VERIFIED", "MEASURED", "OBSERVED", "INFERRED"):
            if not ref_ids:
                report.add("ERROR", path, ln, f"{eid}: {status} without evidence", "add '- evidence: EV-###, MS-###' or change the status")
            elif not accessible_sources:
                report.add("ERROR", path, ln, f"{eid}: {status} but none of its evidence is accessible",
                           "cite evidence you actually opened, or mark it ASSUMED/UNKNOWN")
        if status == "VERIFIED" and accessible_sources and not any(k == "EV" and s.get("type") in AUTHORITATIVE for k, s in accessible_sources):
            report.add("ERROR", path, ln, f"{eid}: VERIFIED needs an authoritative source (doc, patch-notes, talk, screenshot, capture, user-statement)",
                       "cite one, or use MEASURED/INFERRED")
        if status == "MEASURED":
            if accessible_sources and not any(k == "MS" or s.get("type") in FOOTAGE for k, s in accessible_sources):
                report.add("ERROR", path, ln, f"{eid}: MEASURED needs a measurement (MS-###) or accessible footage",
                           "cite the MS entry or the footage you measured")
            if not e["values"]:
                report.add("ERROR", path, ln, f"{eid}: MEASURED without '- value:' lines", "add '- value: name = 1.0 ± 0.1 unit'")
        for vln, val in e["values"]:
            if not VALUE_RE.match(val):
                level = "ERROR" if status == "MEASURED" else "WARNING"
                report.add(level, path, vln, f"{eid}: value {val!r} is not 'name = number ± uncertainty unit'",
                           "write values like 'apex_height = 7.4 ± 0.3 studs'")
        if status == "UNKNOWN":
            if not f.get("open") or f["open"].strip().lower() in TBD:
                report.add("ERROR", path, ln, f"{eid}: UNKNOWN without an 'open:' question", "state the question and what would resolve it")
            questions.append({"id": eid, "question": f.get("open", "")})
        if status == "ASSUMED":
            assumptions.append({"id": eid, "title": e["title"]})
            report.add("WARNING", path, ln, f"{eid}: ASSUMED value in the breakdown", "tell the user; replace it with evidence when possible")
    for cat, name in CATEGORIES.items():
        if by_cat[cat] == 0 and cat not in na:
            report.add("ERROR", path, 0, f"category {cat} ({name}) has no entries", f"add a {cat}-### entry or a '- n/a: {cat} (reason)' coverage line")
        if by_cat[cat] and cat in na:
            report.add("WARNING", path, na[cat][0], f"{cat} declared n/a but has {by_cat[cat]} entries", "remove the n/a line or the entries")
    return {"entries": len(entries), "by_status": counts, "by_category": by_cat, "not_applicable": sorted(na),
            "open_questions": questions, "assumptions": assumptions}


def check_workspace(root: Path, bpath: Path | None = None) -> dict:
    """Run every check on a remake/ workspace; returns errors, warnings and the summary."""
    bpath = bpath or root / "breakdown.md"
    report = Report(None)
    ev = load_ledger(root / "evidence.json", "evidence", report)
    ms = load_ledger(root / "measurements.json", "measurements", report)
    check_ledgers(ev, ms, root / "evidence.json", root / "measurements.json", report)
    entries, na = parse_breakdown(bpath, report)
    if not entries:
        report.add("ERROR", bpath, 0, "no entries found", "add '### PREFIX-001: Title' entries (see game-breakdown.md)")
    summary = check_entries(entries, na, ev, ms, bpath, report)
    return {"errors": report.errors, "warnings": report.warnings, "summary": summary, "entries": entries,
            "evidence": ev, "measurements": ms}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path, help="remake/ directory or its breakdown.md")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="warnings also fail")
    ap.add_argument("--max-issues", type=int, help="limit printed issues (totals unchanged)")
    args = ap.parse_args()

    target = args.target
    if target.is_file():
        root, bpath = target.parent, target
    elif target.is_dir():
        root, bpath = target, target / "breakdown.md"
    else:
        print(f"error: target not found: {target}", file=sys.stderr)
        return rc.EXIT_USAGE
    if not bpath.is_file():
        print(f"error: {bpath} not found (run breakdown_init.py first)", file=sys.stderr)
        return rc.EXIT_USAGE

    result = check_workspace(root, bpath)
    report = Report(args.max_issues)
    report.errors, report.warnings = result["errors"], result["warnings"]
    summary = result["summary"]
    failed = bool(report.errors) or (args.strict and bool(report.warnings))
    files = [str(p) for p in (bpath, root / "evidence.json", root / "measurements.json") if p.is_file()]

    issues = [("ERROR", i) for i in report.errors] + [("WARNING", i) for i in report.warnings]
    shown = issues if args.max_issues is None else issues[: args.max_issues]
    if args.json:
        print(json.dumps({
            "tool": TOOL, "schema": SCHEMA, "root": str(root), "files_checked": files,
            "error_count": len(report.errors), "warning_count": len(report.warnings),
            "errors": [i for lvl, i in shown if lvl == "ERROR"], "warnings": [i for lvl, i in shown if lvl == "WARNING"],
            "truncated": len(shown) < len(issues), "summary": summary, "pass": not failed,
        }, indent=2))
    else:
        for lvl, i in shown:
            loc = f"{i['path']}:{i['line']}" if i["line"] else i["path"]
            print(f"{lvl} {loc}: {i['message']}")
            print(f"  fix: {i['fix']}")
        if len(shown) < len(issues):
            print(f"... {len(issues) - len(shown)} more issues not shown")
        st = ", ".join(f"{k} {v}" for k, v in summary["by_status"].items() if v)
        print(f"Summary: {summary['entries']} entries ({st}); {len(summary['open_questions'])} open questions; "
              f"{len(summary['assumptions'])} assumptions; {len(report.errors)} errors, {len(report.warnings)} warnings"
              + (" [strict]" if args.strict else "") + f" -> {'FAIL' if failed else 'pass'}")
    return rc.EXIT_FAIL if failed else rc.EXIT_OK


if __name__ == "__main__":
    rc.run_main(main)
