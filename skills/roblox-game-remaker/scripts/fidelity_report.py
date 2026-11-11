#!/usr/bin/env python3
"""Score the remake against its tolerances after each iteration, and catch regressions.

Collects the latest comparison results in a remake/ workspace:
  shots     visual_compare batch summary (remake/diff/**/summary.json, newest), or single-pair
            report.json files when there is no summary
  metrics   measure_compare on the newest harness log (remake/logs/*.log) against targets.json
  clips     every clip_compare JSON under remake/diff/ (newest per reference/recreation pair)
  ui        every ui_measure --compare report saved with --out under remake/diff/ (newest per
            reference boxes file): HUD and menu layout
then appends one line to remake/history.jsonl and writes remake/scorecard.md.

Every system gets a normalized error r, where r <= 1 passes:
  metric (target ± tolerance)         r = |error| / tolerance
  shot threshold "at most T"          r = value / T                  (delta_e_mean)
  shot threshold "at least T"         r = (1 - value) / (1 - T)       (ssim, edge_iou)
  clip                                r = the largest of rms/tol_rms, max/tol_max, |offset|/tol_event
  ui layout                           r = worst element error / tolerance (% of screen); a reference
                                      element missing from the recreation fails
Systems without a tolerance are listed as info.

A regression is a system that passed in the previous history entry and fails now, or that still
fails with r larger by more than --margin (default 0.1). Exit: 0 no regression, 1 a regression
(or --fail-on-fail and something fails), 2 bad input.

Examples:
  python fidelity_report.py remake --label "it7: ExposureCompensation 0.35"
  python fidelity_report.py remake --log remake/logs/run-07.log --diff-log --label "it7: exposure"
  python fidelity_report.py remake --dry-run --json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "fidelity_report"
SCHEMA = 1
HERE = Path(__file__).resolve().parent
MIN_KEYS = ("ssim", "edge_iou")  # thresholds that must be at least T
MAX_KEYS = ("delta_e_mean",)  # thresholds that must be at most T


def newest(paths):
    paths = [p for p in paths if p.is_file()]
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def shot_ratio(metrics: dict, thresholds: dict) -> tuple[float | None, dict]:
    parts = {}
    for k, thr in (thresholds or {}).items():
        v = metrics.get(k)
        if thr is None or v is None:
            continue
        if k in MIN_KEYS:
            parts[k] = (1 - v) / max(1e-9, 1 - thr)
        elif k in MAX_KEYS:
            parts[k] = v / max(1e-9, thr)
    return (max(parts.values()) if parts else None), {k: round(v, 4) for k, v in parts.items()}


def collect_shots(remake: Path, shots_file: Path | None) -> tuple[dict, list[str]]:
    sources, out = [], {}
    summary = shots_file or newest(list((remake / "diff").rglob("summary.json")))
    thresholds = {}
    shots_json = load(remake / "shots.json") or {}
    for s in shots_json.get("shots", []):
        thresholds[s.get("id")] = s.get("thresholds") or {}
    if summary:
        data = load(summary) or {}
        if data.get("tool") != "visual_compare":
            rc.fail(f"{summary} is not a visual_compare summary")
        sources.append(str(summary))
        for s in data.get("shots", []):
            sid = s.get("id")
            if s.get("status") in ("missing-capture", "missing-reference"):
                out[f"shot:{sid}"] = {"kind": "shot", "status": "missing", "r": None, "detail": s.get("status")}
                continue
            m = s.get("metrics") or {}
            r, parts = shot_ratio(m, thresholds.get(sid, {}))
            out[f"shot:{sid}"] = {"kind": "shot", "r": None if r is None else round(r, 4), "parts": parts,
                                  "values": {k: m.get(k) for k in ("ssim", "delta_e_mean", "edge_iou")},
                                  "status": "info" if r is None else ("pass" if r <= 1 else "fail")}
            if s.get("aspect_mismatch"):  # a stretched comparison is not a measurement
                out[f"shot:{sid}"].update({"status": "fail", "detail": "aspect mismatch: recapture at the reference aspect ratio"})
    else:
        for rep in sorted((remake / "diff").rglob("report.json")):
            data = load(rep) or {}
            if data.get("tool") != "visual_compare":
                continue
            sources.append(str(rep))
            key = f"shot:{rep.parent.relative_to(remake / 'diff')}"
            r, parts = shot_ratio(data.get("metrics", {}), data.get("thresholds") or {})
            out[key] = {"kind": "shot", "r": None if r is None else round(r, 4), "parts": parts,
                        "values": {k: data.get("metrics", {}).get(k) for k in ("ssim", "delta_e_mean", "edge_iou")},
                        "status": "info" if r is None else ("pass" if r <= 1 else "fail")}
            if any(f.startswith("aspect mismatch") for f in data.get("failures") or []):
                out[key].update({"status": "fail", "detail": "aspect mismatch: recapture at the reference aspect ratio"})
    return out, sources


def collect_metrics(remake: Path, log: Path | None) -> tuple[dict, list[str]]:
    log = log or newest(list((remake / "logs").glob("*.log")))
    if not log:
        return {}, []
    targets = remake / "targets.json"
    cmd = [sys.executable, str(HERE / "measure_compare.py"), str(log), "--json", "--allow-missing"]
    if targets.is_file():
        cmd += ["--targets", str(targets)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode not in (0, 1):
        return {}, [f"{log} (measure_compare failed: {proc.stderr.strip()[-200:]})"]
    data = json.loads(proc.stdout)
    out = {}
    for name, m in data.get("metrics", {}).items():
        if m.get("status") == "not-observed":
            continue
        if m.get("status") in ("pass", "fail"):
            r = abs(m["error"]) / max(1e-12, m["tolerance"])
            out[f"metric:{name}"] = {"kind": "metric", "r": round(r, 4), "status": m["status"], "value": m["mean"],
                                     "target": m["target"], "tolerance": m["tolerance"], "error": m["error"]}
        else:
            out[f"metric:{name}"] = {"kind": "metric", "r": None, "status": "info", "value": m.get("mean")}
    return out, [str(log)]


def collect_clips(remake: Path, clip_files: list[Path]) -> tuple[dict, list[str]]:
    files = clip_files or [p for p in (remake / "diff").rglob("*.json") if p.name not in ("summary.json", "report.json")]
    latest: dict[str, tuple[float, Path, dict]] = {}
    for p in files:
        data = load(p)
        if not isinstance(data, dict) or data.get("tool") != "clip_compare":
            continue
        # Group the same comparison across iterations: the clip id when clip_compare had --clip,
        # otherwise the reference source (the recreation's file name changes every iteration).
        key = data.get("clip_id") or Path(data["reference"]["source"]).name
        mt = p.stat().st_mtime
        if key not in latest or mt > latest[key][0]:
            latest[key] = (mt, p, data)
    out = {}
    for key, (_, p, data) in sorted(latest.items()):
        tol = data.get("tolerances") or {}
        parts = {}
        if tol.get("position_rms"):
            parts["rms"] = data["position_rms"] / tol["position_rms"]
        if tol.get("position_max"):
            parts["max"] = data["position_max"] / tol["position_max"]
        if tol.get("event_offset_s"):
            offs = [abs(e["offset_s"]) for n, e in data.get("events", {}).items()
                    if e.get("offset_s") is not None and not (n == "motion_start" and "first motion" in data.get("alignment", ""))]
            if offs:
                parts["events"] = max(offs) / tol["event_offset_s"]
        r = max(parts.values()) if parts else None
        out[f"clip:{key}"] = {"kind": "clip", "r": None if r is None else round(r, 4), "parts": {k: round(v, 4) for k, v in parts.items()},
                              "value": {"rms": data.get("position_rms"), "max": data.get("position_max")}, "file": str(p),
                              "status": "info" if r is None else ("pass" if r <= 1 else "fail")}
    return out, [str(v[1]) for v in latest.values()]


def collect_ui(remake: Path) -> tuple[dict, list[str]]:
    latest: dict[str, tuple[float, Path, dict]] = {}
    for p in (remake / "diff").rglob("*.json"):
        data = load(p)
        if not isinstance(data, dict) or data.get("tool") != "ui_measure" or data.get("mode") != "compare":
            continue
        # The same layout across iterations shares its reference boxes file.
        key = Path(str(data.get("reference") or p.stem)).stem
        mt = p.stat().st_mtime
        if key not in latest or mt > latest[key][0]:
            latest[key] = (mt, p, data)
    out = {}
    for key, (_, p, data) in sorted(latest.items()):
        tol = data.get("tolerance_pct")
        missing = data.get("missing") or []
        r = (data.get("worst_pct", 0.0) / tol) if tol else None
        worst = max(data.get("elements") or [{}], key=lambda e: e.get("max_pct", 0.0)).get("name")
        status = "fail" if missing else ("info" if r is None else ("pass" if r <= 1 else "fail"))
        out[f"ui:{key}"] = {"kind": "ui", "r": None if r is None else round(r, 4),
                            "value": {"worst_pct": data.get("worst_pct"), "worst_element": worst, "missing": missing},
                            "file": str(p), "status": status}
    return out, [str(v[1]) for v in latest.values()]


def previous_entry(history: Path) -> dict | None:
    if not history.is_file():
        return None
    last = None
    for line in history.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
    return last


def compare(systems: dict, prev: dict | None, margin: float) -> list[str]:
    regressions = []
    old = (prev or {}).get("systems", {})
    for name, s in systems.items():
        p = old.get(name)
        if not p or s.get("r") is None or p.get("r") is None:
            s["change"] = None
            continue
        s["change"] = round(s["r"] - p["r"], 4)
        if p.get("status") == "pass" and s["status"] == "fail":
            regressions.append(f"{name}: passed before (r {p['r']}), fails now (r {s['r']})")
        elif p.get("status") == "fail" and s["status"] == "fail" and s["change"] > margin:
            regressions.append(f"{name}: still failing and worse (r {p['r']} -> {s['r']})")
    for name, p in old.items():
        if name not in systems and p.get("status") == "pass":
            s = {"kind": p.get("kind"), "status": "missing", "r": None, "change": None, "detail": "not measured this iteration"}
            systems[name] = s
    return regressions


def render(entry: dict, regressions: list[str]) -> str:
    lines = [f"# Fidelity scorecard: iteration {entry['iteration']}", "",
             f"Generated {entry['time']} by `scripts/fidelity_report.py`." + (f" Change: {entry['label']}." if entry.get("label") else ""), "",
             "r is the error as a fraction of its tolerance (r <= 1 passes). Change is r minus the previous iteration's r.", "",
             "| System | Status | r | Change | Detail |", "|---|---|---|---|---|"]
    for name, s in sorted(entry["systems"].items(), key=lambda kv: (kv[1]["status"] != "fail", kv[0])):
        if s["kind"] == "metric" and s.get("target") is not None:
            detail = f"{s['value']} vs {s['target']} ± {s['tolerance']} (error {s['error']:+})"
        elif s["kind"] == "metric":
            detail = f"{s.get('value')} (no target)"
        elif s["kind"] == "shot":
            v = s.get("values") or {}
            detail = s.get("detail") or ", ".join(f"{k} {v[k]}" for k in ("ssim", "delta_e_mean", "edge_iou") if v.get(k) is not None)
        elif s["kind"] == "ui":
            v = s.get("value") or {}
            detail = f"worst {v.get('worst_pct')}% of screen ({v.get('worst_element')})"
            if v.get("missing"):
                detail += f"; missing: {', '.join(v['missing'])}"
        else:
            detail = s.get("detail") or f"rms {s['value']['rms']}, max {s['value']['max']}; {s.get('parts')}"
        ch = "" if s.get("change") is None else f"{s['change']:+.3f}"
        r = "" if s.get("r") is None else f"{s['r']:.3f}"
        lines.append(f"| {name} | {s['status']} | {r} | {ch} | {detail} |")
    c = entry["counts"]
    lines += ["", f"**{c['pass']} pass, {c['fail']} fail, {c['info']} info, {c['missing']} missing; "
                  f"{len(regressions)} regressions.**", ""]
    if regressions:
        lines.append("## Regressions")
        lines += [f"- {r}" for r in regressions]
        lines.append("")
    lines.append("Sources: " + ", ".join(f"`{s}`" for s in entry["sources"]) if entry["sources"] else "Sources: none")
    return "\n".join(lines) + "\n"


def diff_log_block(entry: dict, prev: dict | None, regressions: list[str]) -> str:
    def summary(e):
        if not e:
            return "none recorded"
        parts = [f"{n} r {s['r']}" for n, s in sorted(e["systems"].items()) if s.get("r") is not None]
        return "; ".join(parts) or "no judged systems"

    c = entry["counts"]
    return (f"\n## Iteration {entry['iteration']} — {entry['time'][:10]} — {entry.get('label') or 'fidelity_report'}\n"
            f"- change: {entry.get('label') or '(describe the one subsystem you changed)'}\n"
            f"- before: {summary(prev)}\n"
            f"- after: {summary(entry)}\n"
            f"- status: {c['pass']} pass, {c['fail']} fail" + (f"; REGRESSIONS: {'; '.join(regressions)}" if regressions else "") + "\n"
            f"- evidence: remake/scorecard.md, remake/history.jsonl line {entry['iteration']}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("remake", type=Path)
    ap.add_argument("--log", type=Path, help="harness log for measure_compare (default: newest remake/logs/*.log)")
    ap.add_argument("--shots-summary", type=Path, help="visual_compare summary.json (default: newest under remake/diff)")
    ap.add_argument("--clip", type=Path, action="append", default=[], help="clip_compare JSON (default: all under remake/diff)")
    ap.add_argument("--label", help="what changed in this iteration (recorded in history and the scorecard)")
    ap.add_argument("--margin", type=float, default=0.1, help="worsening of r that counts as a regression for failing systems")
    ap.add_argument("--diff-log", action="store_true", help="also append an iteration block to remake/diff-log.md")
    ap.add_argument("--dry-run", action="store_true", help="print the scorecard without writing history or files")
    ap.add_argument("--fail-on-fail", action="store_true", help="exit 1 when any system fails, not only on regressions")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if not args.remake.is_dir():
        rc.fail(f"remake directory not found: {args.remake}")
    for p in [args.log, args.shots_summary, *args.clip]:
        if p is not None and not p.is_file():
            rc.fail(f"file not found: {p}")

    shots, s1 = collect_shots(args.remake, args.shots_summary)
    metrics, s2 = collect_metrics(args.remake, args.log)
    clips, s3 = collect_clips(args.remake, args.clip)
    ui, s4 = collect_ui(args.remake)
    systems = {**shots, **metrics, **clips, **ui}
    if not systems:
        rc.fail("nothing to score: no visual_compare summary, harness log, clip_compare output or saved "
                "ui_measure --compare report (--out remake/diff/...) in the workspace", rc.EXIT_FAIL)
    history = args.remake / "history.jsonl"
    prev = previous_entry(history)
    regressions = compare(systems, prev, args.margin)
    counts = {k: sum(1 for s in systems.values() if s["status"] == k) for k in ("pass", "fail", "info", "missing")}
    entry = {"tool": TOOL, "schema": SCHEMA, "iteration": (prev or {}).get("iteration", 0) + 1,
             "time": _dt.datetime.now().isoformat(timespec="seconds"), "label": args.label or "",
             "counts": counts, "regressions": regressions, "systems": systems, "sources": s1 + s2 + s3 + s4}
    text = render(entry, regressions)
    if not args.dry_run:
        with open(history, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
        (args.remake / "scorecard.md").write_text(text, encoding="utf-8")
        if args.diff_log:
            with open(args.remake / "diff-log.md", "a", encoding="utf-8") as fh:
                fh.write(diff_log_block(entry, prev, regressions))
    if args.json:
        print(rc.dump_json(entry))
    else:
        print(text)
        if not args.dry_run:
            print(f"appended iteration {entry['iteration']} to {history}; wrote {args.remake / 'scorecard.md'}")
    if regressions:
        print("REGRESSION: " + "; ".join(regressions), file=sys.stderr)
        return rc.EXIT_FAIL
    if args.fail_on_fail and counts["fail"]:
        return rc.EXIT_FAIL
    return rc.EXIT_OK


if __name__ == "__main__":
    rc.run_main(main)
