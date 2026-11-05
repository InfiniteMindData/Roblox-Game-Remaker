#!/usr/bin/env python3
"""Show where a remake stands: phase gates, open items, and the single next action.

Reads the remake/ workspace (intake, ledgers, breakdown, targets, shots, Config.luau, logs,
comparison reports, diff log, delivery report) and evaluates each phase gate from SKILL.md.
Run it at the start of every session and after each phase. With --write it also saves
remake/STATUS.md, a compact handoff that survives context resets.

Examples:
  python remake_status.py remake
  python remake_status.py remake --write
  python remake_status.py remake --json
  python remake_status.py remake --require-phase 4     # exit 1 unless gates 0-3 pass
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import breakdown_check  # noqa: E402
import remake_common as rc  # noqa: E402

TOOL = "remake_status"
HERE = Path(__file__).resolve().parent


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def section(text: str, heading: str) -> str:
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default
    except json.JSONDecodeError:
        return default


def gate(ok: bool, detail: str, action: str, partial: bool = False) -> dict:
    return {"ok": ok, "partial": partial and not ok, "detail": detail, "action": action}


def evaluate(remake: Path, config: Path | None) -> dict:
    intake = read(remake / "00-intake.md")
    ev = load_json(remake / "evidence.json", {}).get("evidence", [])
    ms = load_json(remake / "measurements.json", {}).get("measurements", [])
    shots = load_json(remake / "shots.json", {}).get("shots", [])
    targets = load_json(remake / "targets.json", {}).get("metrics", {})
    gates: list[dict] = []

    rights = section(intake, "Rights mode")
    checked = re.findall(r"^- \[[xX]\]\s*(.+)$", rights, re.M)
    slice_line = re.search(r"^- Vertical slice[^:]*:\s*(.*)$", section(intake, "Scope"), re.M)
    scoped = bool(slice_line and slice_line.group(1).strip())
    gates.append(gate(len(checked) == 1 and scoped,
                      f"rights mode: {checked[0].split(':')[0] if len(checked) == 1 else ('none' if not checked else 'several ticked')}; "
                      f"slice: {'set' if scoped else 'missing'}",
                      "Fill remake/00-intake.md: tick exactly one rights mode and write the vertical slice."))

    accessible = [e for e in ev if e.get("accessible") and e.get("type") != "user-statement"]
    blocked = [e for e in ev if not e.get("accessible")]
    gates.append(gate(bool(accessible), f"{len(ev)} sources ({len(accessible)} usable, {len(blocked)} inaccessible)",
                      "Research and record sources with ledger.py add-evidence; ask the user for captures (research-protocol.md)."))

    gates.append(gate(bool(ms) and bool(shots), f"{len(ms)} measurements, {len(shots)} shots",
                      "Measure footage (probe_video, extract_frames, find_mover, motion_track), import with ledger.py import-track, "
                      "and add matched shots to shots.json.", partial=bool(ms) or bool(shots)))

    bd_path = remake / "breakdown.md"
    if bd_path.is_file():
        res = breakdown_check.check_workspace(remake)
        summ = res["summary"]
        ne, nw = len(res["errors"]), len(res["warnings"])
        gates.append(gate(ne == 0 and nw == 0,
                          f"{summ['entries']} entries, {ne} errors, {nw} warnings, {len(summ['open_questions'])} open, "
                          f"{len(summ['assumptions'])} assumed",
                          "Run breakdown_check.py remake --strict and fix what it lists; show the user open questions.",
                          partial=ne == 0))
    else:
        summ = {"open_questions": [], "assumptions": [], "by_status": {}}
        gates.append(gate(False, "breakdown.md missing", "Run breakdown_init.py, then write the breakdown."))

    judged = {k: v for k, v in targets.items() if isinstance(v, dict) and v.get("target") is not None}
    gates.append(gate(bool(judged), f"{len(judged)} numeric targets",
                      "Turn measurements into targets: ledger.py targets remake --tier A."))

    cfg_detail, cfg_ok, cfg_json = "Config.luau not found", False, None
    cfg = config or breakdown_check_config(remake)
    if cfg:
        proc = subprocess.run([sys.executable, str(HERE / "config_check.py"), str(remake), "--config", str(cfg), "--json"],
                              capture_output=True, text=True)
        try:
            cfg_json = json.loads(proc.stdout)
            s = cfg_json["summary"]
            sourced = s["direct_matches"] + (s["evidence_entries"] - s["defaults"] - len(s["assumptions"]) - s["direct_matches"])
            cfg_ok = cfg_json["error_count"] == 0 and sourced > 0
            cfg_detail = (f"{cfg_json['error_count']} errors, {s['direct_matches']} direct matches, "
                          f"{len(s['assumptions'])} assumed, {s['unsourced']} unsourced")
        except (json.JSONDecodeError, KeyError):
            cfg_detail = "config_check failed to run"
    gates.append(gate(cfg_ok, cfg_detail,
                      "Put measured values in Config.luau with Config.Evidence entries, then run config_check.py remake."))

    reports = list((remake / "diff").rglob("report.json")) + list((remake / "diff").rglob("summary.json"))
    logs = list((remake / "logs").glob("*.log"))
    diff_log = read(remake / "diff-log.md")
    filled = [m for m in re.findall(r"^- after:[ \t]*(\S.*)$", diff_log, re.M)]
    gates.append(gate(bool(filled) and (bool(reports) or bool(logs)),
                      f"{len(filled)} logged iterations, {len(reports)} comparison reports, {len(logs)} harness logs",
                      "Capture shots and harness logs, run visual_compare.py / measure_compare.py, log the iteration in diff-log.md.",
                      partial=bool(reports) or bool(logs)))

    delivery = section(read(remake / "delivery-report.md"), "Results by breakdown entry")
    rows = [ln for ln in delivery.splitlines() if ln.startswith("|") and not re.match(r"^\|[\s|:-]+\|?$", ln)][1:]
    gates.append(gate(bool(rows), f"{len(rows)} result rows", "Fill delivery-report.md with measured results per entry."))

    names = ["0 Intake and rights", "1 Research", "2 Footage analysis", "3 Breakdown", "4 Translation (targets)",
             "5 Build (Config)", "6 Verify and fix", "7 Deliver"]
    for n, g in zip(names, gates):
        g["phase"] = n
    current = next((i for i, g in enumerate(gates) if not g["ok"]), len(gates))
    return {
        "tool": TOOL, "remake": str(remake), "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "gates": gates, "current_phase": current,
        "next_action": gates[current]["action"] if current < len(gates) else "All gates pass: review gaps with the user.",
        "open_questions": summ.get("open_questions", []), "assumptions": summ.get("assumptions", []),
        "config_assumptions": (cfg_json or {}).get("summary", {}).get("assumptions", []),
        "inaccessible_sources": [f"{e.get('id')} {e.get('title', '')}" for e in blocked],
        "by_status": summ.get("by_status", {}),
    }


def breakdown_check_config(remake: Path) -> Path | None:
    import config_check

    return config_check.find_config(remake)


def render(st: dict) -> str:
    lines = [f"# Remake status", "", f"Generated {st['generated']} by `scripts/remake_status.py`.", ""]
    lines.append("| Phase | Gate | Detail |")
    lines.append("|---|---|---|")
    for g in st["gates"]:
        mark = "pass" if g["ok"] else ("partial" if g["partial"] else "open")
        lines.append(f"| {g['phase']} | {mark} | {g['detail']} |")
    lines += ["", f"**Current phase:** {st['gates'][st['current_phase']]['phase'] if st['current_phase'] < len(st['gates']) else 'done'}",
              f"**Next action:** {st['next_action']}", ""]
    if st["open_questions"]:
        lines.append("## Open questions")
        lines += [f"- {q['id']}: {q['question']}" for q in st["open_questions"]]
        lines.append("")
    if st["assumptions"] or st["config_assumptions"]:
        lines.append("## Assumptions in use")
        lines += [f"- {a['id']}: {a['title']}" for a in st["assumptions"]]
        lines += [f"- Config {k}" for k in st["config_assumptions"]]
        lines.append("")
    if st["inaccessible_sources"]:
        lines.append("## Inaccessible sources (not analyzed)")
        lines += [f"- {s}" for s in st["inaccessible_sources"]]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("remake", type=Path)
    ap.add_argument("--config", type=Path, help="Config.luau (default: found under the project)")
    ap.add_argument("--write", action="store_true", help="also write remake/STATUS.md")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--require-phase", type=int, help="exit 1 unless every gate before this phase passes")
    args = ap.parse_args()
    if not args.remake.is_dir():
        print(f"error: remake directory not found: {args.remake} (run breakdown_init.py first)", file=sys.stderr)
        return rc.EXIT_USAGE
    st = evaluate(args.remake, args.config)
    text = render(st)
    if args.write:
        (args.remake / "STATUS.md").write_text(text + "\n", encoding="utf-8")
    print(json.dumps(st, indent=2) if args.json else text)
    if args.require_phase is not None and st["current_phase"] < args.require_phase:
        return rc.EXIT_FAIL
    return rc.EXIT_OK


if __name__ == "__main__":
    rc.run_main(main)
