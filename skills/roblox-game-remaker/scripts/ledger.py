#!/usr/bin/env python3
"""Add evidence and measurements to a remake/ workspace without hand-editing JSON.

Assigns the next free ID, fills today's date, validates references, and writes atomically.

Subcommands:
  add-evidence REMAKE --type video --title "..." --source PATH_OR_URL [--inaccessible] ...
  add-measurement REMAKE --what "..." --evidence EV-003 --method "..." --value 8 --uncertainty 0.05 --unit studs
  import-track REMAKE TRACK.json --evidence EV-003      motion_track output -> measurements
  targets REMAKE [--tier A] [--map metric=MS-001,...]   measurements -> targets.json for measure_compare
  list REMAKE                                           show both ledgers

Measurements created by import-track carry a "metric" field (jump_apex, accel_t90, ...), which
`targets` uses automatically. Existing targets with a non-null value are kept unless --replace.

Examples:
  python ledger.py add-evidence remake --type video --title "Standing jump, side-on" --source remake/media/jump.mp4 --analysis "probe+extract+track"
  python ledger.py add-evidence remake --type video --title "Speedrun" --source https://example.com/v --inaccessible --notes "HTTP 403"
  python ledger.py import-track remake remake/tracks/jump01.json --evidence EV-003
  python ledger.py targets remake --tier A
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "ledger"
EV_TYPES = ("video", "screenshot", "capture", "doc", "patch-notes", "wiki", "community-data", "talk", "forum",
            "user-statement", "measurement")
TIME_METRICS = {"accel_t90", "decel_t10", "jump_rise_time", "jump_fall_time", "jump_airtime"}
# Tier tolerances (roblox-translation.md section 9): timings in source frames, lengths/speeds in percent.
TIERS = {"S": {"frames": 1, "pct": 3.0}, "A": {"frames": 2, "pct": 7.0}, "B": {"frames": None, "pct": 15.0}}


def ledger_path(remake: Path, kind: str) -> Path:
    if not remake.is_dir():
        rc.fail(f"remake directory not found: {remake} (run breakdown_init.py first)")
    return remake / ("evidence.json" if kind == "evidence" else "measurements.json")


def load(remake: Path, kind: str) -> tuple[Path, dict, list]:
    path = ledger_path(remake, kind)
    key = "evidence" if kind == "evidence" else "measurements"
    data = rc.read_json(path) if path.exists() else {"schema": 1, key: []}
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        rc.fail(f"{path} has no '{key}' list")
    return path, data, data[key]


def save(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".ledger-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def next_id(items: list, prefix: str) -> str:
    nums = [int(m.group(1)) for i in items if (m := re.match(rf"{prefix}-(\d+)$", str(i.get("id", ""))))]
    return f"{prefix}-{(max(nums) + 1 if nums else 1):03d}"


def today() -> str:
    return _dt.date.today().isoformat()


def require_accessible_evidence(remake: Path, ids: list[str]) -> None:
    _, _, ev = load(remake, "evidence")
    by = {e.get("id"): e for e in ev}
    for i in ids:
        if i not in by:
            rc.fail(f"evidence {i} does not exist in evidence.json")
        if not by[i].get("accessible"):
            rc.fail(f"evidence {i} is marked inaccessible; a measurement needs footage you actually opened")


def cmd_add_evidence(args) -> int:
    path, data, items = load(args.remake, "evidence")
    if args.type not in EV_TYPES:
        rc.fail(f"--type must be one of: {', '.join(EV_TYPES)}")
    if not args.inaccessible and args.type in ("video", "screenshot", "capture") and not args.analysis:
        print("note: accessible footage without --analysis; record which tools and frames you used when you analyze it", file=sys.stderr)
    entry = {"id": next_id(items, "EV"), "type": args.type, "title": args.title, "source": args.source,
             "version": args.version or data.get("version", "TBD"), "accessed": args.date or today(),
             "accessible": not args.inaccessible, "analysis": args.analysis or "", "rights": args.rights or "",
             "notes": args.notes or ""}
    items.append(entry)
    save(path, data)
    print(entry["id"])
    return 0


def add_measurement(remake: Path, entry: dict) -> str:
    path, data, items = load(remake, "measurements")
    entry = {"id": next_id(items, "MS"), **entry}
    items.append(entry)
    save(path, data)
    return entry["id"]


def cmd_add_measurement(args) -> int:
    ids = [i.strip() for i in args.evidence.split(",") if i.strip()]
    require_accessible_evidence(args.remake, ids)
    try:
        value = float(args.value)
    except ValueError:
        value = args.value
    entry = {"what": args.what, "evidence": ids, "method": args.method, "value": value,
             "uncertainty": args.uncertainty, "unit": args.unit}
    if args.metric:
        entry["metric"] = args.metric
    if args.frames:
        a, b = (int(v) for v in args.frames.split(","))
        entry["frames"] = [a, b]
    print(add_measurement(args.remake, entry))
    return 0


def cmd_import_track(args) -> int:
    require_accessible_evidence(args.remake, [args.evidence])
    track = rc.read_json(args.track)
    if track.get("tool") != "motion_track":
        rc.fail(f"{args.track} is not motion_track output")
    unit = track.get("unit", "px")
    ppu = track.get("px_per_unit")
    base = f"motion_track {args.track.name}: bbox {track.get('bbox')}" + (f", {ppu} px/{unit}" if ppu else ", pixels")
    if track.get("anchor_bbox"):
        base += f", camera motion cancelled with anchor {track['anchor_bbox']}"
    samples = track.get("samples", [])
    px = 1.0 / ppu if ppu else 1.0
    if "jump" in track:
        j = track["jump"]
        dt = j.get("time_precision_s") or 1 / 60
        seg = j.get("segment_samples") or [0, len(samples) - 1]
        frames = [samples[seg[0]].get("index"), samples[seg[1]].get("index")] if samples else None
        method = f"{base}; jump fit ({j.get('method', 'piecewise')}), fit rms {j.get('fit_rms')}"
        rows = [
            ("jump_apex", "jump apex height", j["apex_height"], round(max(2 * j.get("fit_rms", 0), px), 4), unit),
            ("jump_rise_time", "jump rise time", j["rise_time_s"], round(dt, 5), "s"),
            ("jump_fall_time", "jump fall time", j["fall_time_s"], round(dt, 5), "s"),
            ("jump_airtime", "jump airtime", j["airtime_s"], round(dt, 5), "s"),
            ("g_rise", "rise gravity", j["g_rise"], j.get("g_rise_std", j.get("gravity_single_fit_std")), f"{unit}/s^2"),
            ("g_fall", "fall gravity", j["g_fall"], j.get("g_fall_std", j.get("gravity_single_fit_std")), f"{unit}/s^2"),
        ]
    elif "speed" in track:
        s = track["speed"]
        dt = s.get("time_precision_s") or 1 / 60
        model = s.get("preferred_model")
        ramp = s["linear_ramp"]["time_to_full_s"] if model == "linear_ramp" else s["exponential"]["tau_s"]
        frames = [samples[0].get("index"), samples[-1].get("index")] if samples else None
        method = f"{base}; standing-start fit, preferred model {model}"
        rows = [
            ("ground_speed", "steady ground speed", s["steady_speed"],
             round(max(2 * s.get("steady_speed_std", 0.0), 0.005 * s["steady_speed"]), 4), f"{unit}/s"),
            ("accel_t90", "time to 90% speed", s["t90_s"], round(dt, 5), "s"),
            ("accel_ramp" if model == "linear_ramp" else "accel_tau",
             "linear ramp duration" if model == "linear_ramp" else "exponential time constant", ramp, round(dt, 5), "s"),
        ]
    else:
        rc.fail(f"{args.track} has no jump or speed analysis; run motion_track with --analyze jump|speed")
    for metric, what, value, unc, u in rows:
        entry = {"what": what, "metric": metric, "evidence": [args.evidence], "method": method,
                 "value": value, "uncertainty": unc if unc is not None else round(dt, 5), "unit": u}
        if frames and None not in frames:
            entry["frames"] = frames
        mid = add_measurement(args.remake, entry)
        print(f"{mid}  {metric:<15} {value} ± {entry['uncertainty']} {u}")
    return 0


def cmd_targets(args) -> int:
    _, _, ms = load(args.remake, "measurements")
    by_id = {m["id"]: m for m in ms}
    mapping: dict[str, str] = {}
    for m in ms:
        if m.get("metric"):
            mapping[m["metric"]] = m["id"]  # later measurements of the same metric win
    if args.map:
        for pair in args.map.split(","):
            if "=" not in pair:
                rc.fail("--map entries look like metric=MS-001")
            k, v = (x.strip() for x in pair.split("=", 1))
            if v not in by_id:
                rc.fail(f"--map: unknown measurement {v}")
            mapping[k] = v
    if not mapping:
        rc.fail("no measurements carry a 'metric'; use import-track or pass --map metric=MS-001")
    tier = TIERS[args.tier]
    path = args.remake / "targets.json"
    data = rc.read_json(path) if path.exists() else {"schema": 1, "metrics": {}}
    metrics = data.setdefault("metrics", {})
    written = []
    for metric, mid in sorted(mapping.items()):
        if metric in ("g_rise", "g_fall", "accel_ramp", "accel_tau"):
            continue  # inputs to Config, not observable by measure_compare
        existing = metrics.get(metric) or {}
        if existing.get("target") is not None and not args.replace:
            continue
        m = by_id[mid]
        try:
            value = float(m["value"])
            unc = float(m.get("uncertainty") or 0)
        except (TypeError, ValueError):
            continue
        spec = {"target": value, "unit": m.get("unit"), "source": mid}
        if metric in TIME_METRICS and tier["frames"]:
            frame = unc if unc >= 1 / 240 else 1 / 60  # time uncertainties are one source frame
            tol = max(unc, tier["frames"] * frame)
        else:
            tol = max(unc, abs(value) * tier["pct"] / 100)
        spec["tolerance"] = round(tol, 5)
        metrics[metric] = spec
        written.append(f"{metric} = {value} ± {spec['tolerance']} ({mid})")
    save(path, data)
    for w in written:
        print(w)
    print(f"wrote {len(written)} targets to {path} (tier {args.tier})")
    return 0


def cmd_list(args) -> int:
    _, _, ev = load(args.remake, "evidence")
    _, _, ms = load(args.remake, "measurements")
    for e in ev:
        flag = "" if e.get("accessible") else "  [INACCESSIBLE]"
        print(f"{e.get('id')}  {e.get('type', ''):<14} {e.get('title', '')}{flag}")
    for m in ms:
        metric = f" [{m['metric']}]" if m.get("metric") else ""
        print(f"{m.get('id')}  {m.get('what', '')}{metric} = {m.get('value')} ± {m.get('uncertainty')} {m.get('unit', '')}  <- {', '.join(m.get('evidence', []))}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add-evidence")
    p.add_argument("remake", type=Path)
    p.add_argument("--type", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--version")
    p.add_argument("--date")
    p.add_argument("--inaccessible", action="store_true", help="you could not open it (dead link, blocked, unsupported codec)")
    p.add_argument("--analysis")
    p.add_argument("--rights")
    p.add_argument("--notes")
    p.set_defaults(fn=cmd_add_evidence)
    p = sub.add_parser("add-measurement")
    p.add_argument("remake", type=Path)
    p.add_argument("--what", required=True)
    p.add_argument("--evidence", required=True, help="comma-separated EV ids")
    p.add_argument("--method", required=True)
    p.add_argument("--value", required=True)
    p.add_argument("--uncertainty", required=True)
    p.add_argument("--unit", required=True)
    p.add_argument("--metric", help="measure_compare metric name, for targets")
    p.add_argument("--frames", help="first,last source frame")
    p.set_defaults(fn=cmd_add_measurement)
    p = sub.add_parser("import-track")
    p.add_argument("remake", type=Path)
    p.add_argument("track", type=Path)
    p.add_argument("--evidence", required=True)
    p.set_defaults(fn=cmd_import_track)
    p = sub.add_parser("targets")
    p.add_argument("remake", type=Path)
    p.add_argument("--tier", choices=sorted(TIERS), default="A")
    p.add_argument("--map", help="metric=MS-id pairs, comma-separated")
    p.add_argument("--replace", action="store_true", help="overwrite targets that already have a value")
    p.set_defaults(fn=cmd_targets)
    p = sub.add_parser("list")
    p.add_argument("remake", type=Path)
    p.set_defaults(fn=cmd_list)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    rc.run_main(main)
