#!/usr/bin/env python3
"""Compare in-game measurements (from the template's MeasurementHarness) with reference targets.

LOG is a copy of the Studio Output (or MCP get_console_output) that contains harness lines:
  REMAKE_MEASURE {"k":"b","s":[[t,x,y,z,vx,vy,vz,state,mv], ...]}   batched samples
  REMAKE_MEASURE {"k":"s","t":..,"p":[x,y,z],"v":[vx,vy,vz],"st":"Running","mv":1}  single sample
  REMAKE_MEASURE {"k":"e","t":..,"n":"jump"}   events: jump, land, move_start, move_stop
Other text on the line (timestamps, script names) is ignored.

Derived metrics:
  ground_speed     median horizontal speed at full input, >= 0.5 s after move_start
  accel_t90        time from move_start to 90% of ground_speed (median over starts)
  decel_t10        time from move_stop to below 10% of ground_speed
  jump_apex        apex height above the takeoff height (per jump)
  jump_rise_time   takeoff to apex
  jump_fall_time   apex to landing
  jump_airtime     takeoff to landing
  fall_speed_max   largest downward speed

TARGETS (JSON): {"metrics": {"jump_apex": {"target": 7.4, "tolerance": 0.3},
                             "ground_speed": {"target": 20, "tolerance_pct": 3}}}
Metrics with a null target are reported but not judged.

Exit: 0 all judged metrics pass; 1 a metric fails or a targeted metric was not observed
(unless --allow-missing); 2 bad input.

Examples:
  python measure_compare.py remake/logs/run-01.log --targets remake/targets.json
  python measure_compare.py run.log --json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "measure_compare"
TAG = "REMAKE_MEASURE"
STATE_CODES = {0: "Unknown", 1: "Running", 2: "Jumping", 3: "Freefall", 4: "Landed", 5: "Climbing",
               6: "Swimming", 7: "Seated", 8: "Dead", 9: "Other"}
GROUNDED = {"Running", "RunningNoPhysics", "Landed"}


def parse_log(path: Path, tag: str):
    samples, events = [], []
    decoder = json.JSONDecoder()
    bad = 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        rc.fail(f"log not found: {path}")
    for line in text.splitlines():
        pos = line.find(tag)
        if pos < 0:
            continue
        brace = line.find("{", pos)
        if brace < 0:
            bad += 1
            continue
        try:
            obj, _ = decoder.raw_decode(line[brace:])
        except json.JSONDecodeError:
            bad += 1
            continue
        kind = obj.get("k")
        if kind == "b":
            for row in obj.get("s", []):
                if len(row) >= 9:
                    t, x, y, z, vx, vy, vz, st, mv = row[:9]
                    samples.append({"t": t, "p": (x, y, z), "v": (vx, vy, vz),
                                    "st": STATE_CODES.get(int(st), str(st)) if isinstance(st, (int, float)) else st, "mv": mv})
        elif kind == "s":
            samples.append({"t": obj["t"], "p": tuple(obj["p"]), "v": tuple(obj["v"]), "st": obj.get("st", "Unknown"), "mv": obj.get("mv", 0)})
        elif kind == "e":
            events.append({"t": obj["t"], "n": obj.get("n", "")})
    samples.sort(key=lambda s: s["t"])
    events.sort(key=lambda e: e["t"])
    return samples, events, bad


def hspeed(s) -> float:
    return math.hypot(s["v"][0], s["v"][2])


def derive(samples, events) -> dict:
    out: dict[str, list[float]] = {k: [] for k in (
        "ground_speed", "accel_t90", "decel_t10", "jump_apex", "jump_rise_time", "jump_fall_time", "jump_airtime", "fall_speed_max")}
    if not samples:
        return out
    starts = [e["t"] for e in events if e["n"] == "move_start"]
    stops = [e["t"] for e in events if e["n"] == "move_stop"]

    # Input-active windows: [move_start, next move_stop). Steady state starts 0.5 s into a window.
    windows = []
    for t0 in starts:
        t1 = next((t for t in stops if t > t0), float("inf"))
        windows.append((t0 + 0.5, t1))
    if windows:
        full = [hspeed(s) for s in samples if s["st"] in GROUNDED and s["mv"] >= 0.99
                and any(a <= s["t"] < b for a, b in windows)]
    else:
        full = [hspeed(s) for s in samples if s["st"] in GROUNDED and s["mv"] >= 0.99]
    steady = statistics.median(full) if full else None
    if steady:
        out["ground_speed"].append(steady)
        for t0 in starts:
            nxt = next((s for s in samples if s["t"] >= t0 and hspeed(s) >= 0.9 * steady), None)
            if nxt:
                out["accel_t90"].append(nxt["t"] - t0)
        for t0 in stops:
            nxt = next((s for s in samples if s["t"] >= t0 and hspeed(s) <= 0.1 * steady), None)
            if nxt:
                out["decel_t10"].append(nxt["t"] - t0)

    jumps = [e["t"] for e in events if e["n"] == "jump"]
    lands = [e["t"] for e in events if e["n"] == "land"]
    if not jumps:  # derive from state transitions
        prev = None
        for s in samples:
            if prev and prev["st"] in GROUNDED and s["st"] == "Jumping":
                jumps.append(s["t"])
            if prev and prev["st"] in ("Jumping", "Freefall") and s["st"] in GROUNDED:
                lands.append(s["t"])
            prev = s
    for tj in jumps:
        tl = next((t for t in lands if t > tj), None)
        if tl is None:
            continue
        seg = [s for s in samples if tj <= s["t"] <= tl]
        before = [s for s in samples if s["t"] < tj]  # last grounded sample before takeoff
        if len(seg) < 3 or not before:
            continue
        y0 = before[-1]["p"][1]
        top = max(seg, key=lambda s: s["p"][1])
        out["jump_apex"].append(top["p"][1] - y0)
        out["jump_rise_time"].append(top["t"] - tj)
        out["jump_fall_time"].append(tl - top["t"])
        out["jump_airtime"].append(tl - tj)
    vys = [-s["v"][1] for s in samples]
    if vys and max(vys) > 0:
        out["fall_speed_max"].append(max(vys))
    return out


def judge(values: list[float], spec: dict | None):
    if not values:
        return {"n": 0, "status": "not-observed"}
    mean = statistics.fmean(values)
    res = {"n": len(values), "mean": round(mean, 4), "std": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
           "min": round(min(values), 4), "max": round(max(values), 4)}
    if not spec or spec.get("target") is None:
        res["status"] = "no-target"
        return res
    target = float(spec["target"])
    if spec.get("tolerance_pct") is not None:
        tol = abs(target) * float(spec["tolerance_pct"]) / 100.0
    elif spec.get("tolerance") is not None:
        tol = float(spec["tolerance"])
    else:
        rc.fail("each target needs 'tolerance' or 'tolerance_pct'")
    err = mean - target
    res.update({"target": target, "tolerance": round(tol, 5), "error": round(err, 4),
                "error_pct": round(100 * err / target, 3) if target else None,
                "status": "pass" if abs(err) <= tol else "fail", "source": spec.get("source")})
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", type=Path)
    ap.add_argument("--targets", type=Path, help="targets JSON (remake/targets.json)")
    ap.add_argument("--tag", default=TAG)
    ap.add_argument("--allow-missing", action="store_true", help="do not fail when a targeted metric was not observed")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    samples, events, bad = parse_log(args.log, args.tag)
    if not samples and not events:
        rc.fail(f"no {args.tag} lines found in {args.log}; enable the MeasurementHarness and copy the full Output", rc.EXIT_FAIL)
    targets = {}
    if args.targets:
        data = rc.read_json(args.targets)
        targets = data.get("metrics", {}) if isinstance(data, dict) else {}
    derived = derive(samples, events)
    results = {name: judge(vals, targets.get(name)) for name, vals in derived.items()}
    failed = [n for n, r in results.items() if r["status"] == "fail"]
    missing = [n for n, r in results.items() if r["status"] == "not-observed" and targets.get(n, {}).get("target") is not None]
    ok = not failed and (args.allow_missing or not missing)
    report = {"tool": TOOL, "log": str(args.log), "samples": len(samples), "events": len(events), "unparsed_lines": bad,
              "metrics": results, "failed": failed, "missing": missing, "pass": ok}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{len(samples)} samples, {len(events)} events from {args.log}" + (f" ({bad} unparsed lines)" if bad else ""))
        for name, r in results.items():
            if r["status"] in ("pass", "fail"):
                print(f"{r['status'].upper():<5} {name:<15} {r['mean']} (n={r['n']}, std {r['std']}) target {r['target']} ± {r['tolerance']}  error {r['error']:+}")
            elif r["status"] == "no-target":
                print(f"info  {name:<15} {r['mean']} (n={r['n']}, std {r['std']})")
            elif name in missing:
                print(f"MISS  {name:<15} not observed (reproduce this test in the playtest)")
        print("result: " + ("pass" if ok else "FAIL"))
    return rc.EXIT_OK if ok else rc.EXIT_FAIL


if __name__ == "__main__":
    rc.run_main(main)
