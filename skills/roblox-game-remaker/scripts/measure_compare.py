#!/usr/bin/env python3
"""Compare in-game measurements (from the template's MeasurementHarness) with reference targets.

LOG is a copy of the Studio Output (or MCP get_console_output) that contains harness lines:
  REMAKE_MEASURE {"k":"b","s":[[t,x,y,z,vx,vy,vz,state,mv], ...]}   batched samples
  REMAKE_MEASURE {"k":"s","t":..,"p":[x,y,z],"v":[vx,vy,vz],"st":"Running","mv":1}  single sample
  REMAKE_MEASURE {"k":"e","t":..,"n":"jump"}   events: jump, land, move_start, move_stop
  REMAKE_MEASURE {"k":"l","t":..,"in":"Space","f":2,"fd":0.0167,"dt":0.025}   input latency
                 (DevTools.MeasureLatency): rendered frames from a press to the first visible change
  REMAKE_MEASURE {"k":"sim","id":"p1","hz":60,"grounded":["idle","walkF"]}   simulation header
Other text on the line (timestamps, script names) is ignored.

Simulation-driven games (fighting games, custom controllers, anything without a Humanoid) log through
the template's Remake/SimRecorder module: samples and events carry an "id" (one per fighter or body),
and times are sim ticks / hz, so frame counts are exact. With several ids, pick one with --subject.
States are the game's own strings; the header's "grounded" list says which count as on the ground.

Derived metrics:
  ground_speed     median horizontal speed at full input, >= 0.5 s after move_start
  accel_t90        time from move_start to 90% of ground_speed (median over starts)
  decel_t10        time from move_stop to below 10% of ground_speed
  jump_apex        apex height above the takeoff height (per jump)
  jump_rise_time   takeoff to apex
  jump_fall_time   apex to landing
  jump_airtime     takeoff to landing
  fall_speed_max   largest downward speed
  input_latency    seconds from a press to the first rendered frame that shows a change
                   (frames x frame duration, per press); --latency-key limits it to one key.
                   input_latency_frames gives the same in the build's frames (info only).
                   Presses with no change before the timeout are counted, not averaged.
  NAME (--interval NAME=A..B)  time from each event A to the first event B before the next A,
                   for frame data (startup = attack..active, recovery = active..idle). An A
                   with no B before the next A (a whiffed jab for attack..hit) is counted as
                   unpaired, not averaged. Repeatable.
  ground_speed[S]  simulation logs: median speed in each grounded state S at full input
                   (walkF and walkB separately; ground_speed mixes them).

Frames: when the log has a simulation header (or --hz is given), every time metric also reports
mean_frames, and a target with "unit": "frames" is judged in frames:
  {"metrics": {"startup": {"target": 7, "tolerance": 0, "unit": "frames"}}}

TARGETS (JSON): {"metrics": {"jump_apex": {"target": 7.4, "tolerance": 0.3},
                             "ground_speed": {"target": 20, "tolerance_pct": 3}}}
Metrics with a null target are reported but not judged.

Exit: 0 all judged metrics pass; 1 a metric fails, a targeted metric was not observed (unless
--allow-missing), or the log has no motion samples at all; 2 bad input. With no targets nothing is
judged and the result is "unchecked", not "pass".

Examples:
  python measure_compare.py remake/logs/run-01.log --targets remake/targets.json
  python measure_compare.py run.log --json
  python measure_compare.py fight.log --subject p1 --interval startup=attack..active --targets t.json
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


TIME_METRICS = {"accel_t90", "decel_t10", "jump_rise_time", "jump_fall_time", "jump_airtime", "input_latency"}


def parse_log(path: Path, tag: str, latency: list | None = None, subject: str | None = None, meta: dict | None = None):
    """Samples and events for one subject. meta (optional dict) receives {"ids", "hz", "grounded"}."""
    samples, events = [], []
    sims: dict[str, dict] = {}
    seen: set[str] = set()
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
        oid = obj.get("id")
        if kind == "sim":
            sims[str(oid or "")] = obj
            continue
        if oid is not None:
            seen.add(str(oid))
        if subject is not None and kind in ("b", "s", "e") and str(oid) != subject:
            continue
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
        elif kind == "l" and latency is not None:
            latency.append({"t": obj.get("t"), "key": obj.get("in", ""), "f": obj.get("f", -1), "fd": obj.get("fd"),
                            "dt": obj.get("dt")})
    ids = sorted(seen | {k for k in sims if k})
    if subject is None and len(ids) > 1:
        rc.fail(f"{path} has samples for several subjects ({', '.join(ids)}); pick one with --subject")
    if subject is not None and subject not in ids:
        rc.fail(f"subject {subject!r} not in {path} (subjects: {', '.join(ids) or 'none'})")
    head = sims.get(subject if subject is not None else (ids[0] if ids else "")) or sims.get("") or {}
    if meta is not None:
        meta.update({"ids": ids, "hz": head.get("hz"), "grounded": list(head.get("grounded") or [])})
    samples.sort(key=lambda s: s["t"])
    events.sort(key=lambda e: e["t"])
    return samples, events, bad


def hspeed(s) -> float:
    return math.hypot(s["v"][0], s["v"][2])


def parse_intervals(specs: list[str] | None) -> dict[str, tuple[str, str]]:
    out = {}
    for spec in specs or []:
        name, sep, rest = spec.partition("=")
        a, sep2, b = rest.partition("..")
        if not (sep and sep2 and name.strip() and a.strip() and b.strip()):
            rc.fail(f"--interval must look like NAME=EVENT_A..EVENT_B, got {spec!r}")
        out[name.strip()] = (a.strip(), b.strip())
    return out


def derive(samples, events, latency=None, latency_key=None, grounded=None, intervals=None) -> dict:
    grounded_states = GROUNDED | set(grounded or ())
    out: dict[str, list[float]] = {k: [] for k in (
        "ground_speed", "accel_t90", "decel_t10", "jump_apex", "jump_rise_time", "jump_fall_time", "jump_airtime", "fall_speed_max",
        "input_latency", "input_latency_frames")}
    for lat in latency or []:
        if latency_key and lat["key"] != latency_key:
            continue
        if lat["f"] is not None and lat["f"] >= 0:
            fd = lat["fd"] if lat.get("fd") else 1 / 60
            out["input_latency"].append(lat["f"] * fd)
            out["input_latency_frames"].append(float(lat["f"]))
    for name, (a, b) in (intervals or {}).items():
        vals = out.setdefault(name, [])
        starts_a = [e["t"] for e in events if e["n"] == a]
        ends_b = [e["t"] for e in events if e["n"] == b]
        unpaired = 0
        for i, ta in enumerate(starts_a):
            # B closes this A only if it comes before the next A: a whiffed jab must not borrow a later jab's hit.
            limit = starts_a[i + 1] if i + 1 < len(starts_a) else float("inf")
            tb = next((x for x in ends_b if ta < x <= limit), None)
            if tb is None:
                unpaired += 1
            else:
                vals.append(tb - ta)
        if unpaired:
            out.setdefault("_unpaired", {})[name] = unpaired  # type: ignore[assignment]
    if not samples:
        return out
    starts = [e["t"] for e in events if e["n"] == "move_start"]
    stops = [e["t"] for e in events if e["n"] == "move_stop"]

    def is_full(s) -> bool:
        return s["st"] in grounded_states and s["mv"] >= 0.99

    # Input-active windows: [move_start, next move_stop). Steady state starts 0.5 s into a window.
    windows = []
    for t0 in starts:
        t1 = next((t for t in stops if t > t0), float("inf"))
        windows.append((t0, t1))
    if windows:
        full = [hspeed(s) for s in samples if is_full(s) and any(a + 0.5 <= s["t"] < b for a, b in windows)]
    else:
        full = [hspeed(s) for s in samples if is_full(s)]
    steady = statistics.median(full) if full else None
    if steady:
        out["ground_speed"].append(steady)
    # Acceleration and deceleration use each window's own steady speed, so walks at different speeds
    # (forward and backward, walk and run) do not distort each other.
    for t0, t1 in windows:
        own = [hspeed(s) for s in samples if is_full(s) and t0 + 0.5 <= s["t"] < t1]
        ref = statistics.median(own) if own else steady
        if not ref:
            continue
        nxt = next((s for s in samples if t0 <= s["t"] < t1 and hspeed(s) >= 0.9 * ref), None)
        if nxt:
            out["accel_t90"].append(nxt["t"] - t0)
        if t1 != float("inf"):
            nxt = next((s for s in samples if s["t"] >= t1 and hspeed(s) <= 0.1 * ref), None)
            if nxt:
                out["decel_t10"].append(nxt["t"] - t1)
    # Simulation logs: one speed per grounded state the game declared (walkF, walkB, run ...).
    for state in sorted(set(grounded or ())):
        sp = [hspeed(s) for s in samples if s["st"] == state and s["mv"] >= 0.99 and hspeed(s) > 0]
        if sp:
            out[f"ground_speed[{state}]"] = [statistics.median(sp)]

    jumps = [e["t"] for e in events if e["n"] == "jump"]
    lands = [e["t"] for e in events if e["n"] == "land"]
    if not jumps:  # derive from state transitions
        prev = None
        for s in samples:
            if prev and prev["st"] in grounded_states and s["st"] == "Jumping":
                jumps.append(s["t"])
            if prev and prev["st"] in ("Jumping", "Freefall") and s["st"] in grounded_states:
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


def judge(values: list[float], spec: dict | None, hz: float | None = None, timed: bool = False):
    if not values:
        return {"n": 0, "status": "not-observed"}
    unit = (spec or {}).get("unit")
    if unit == "frames":
        if not (timed and hz):
            rc.fail("a target with unit 'frames' needs a time metric and a tick rate (simulation header or --hz)")
        values = [round(v * hz, 3) for v in values]  # log times carry 5 decimals; frames are whole ticks
    mean = statistics.fmean(values)
    res = {"n": len(values), "mean": round(mean, 4), "std": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
           "min": round(min(values), 4), "max": round(max(values), 4)}
    if unit == "frames":
        res["unit"] = "frames"
    elif timed and hz:
        res["mean_frames"] = round(mean * hz, 2)
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
    ap.add_argument("--latency-key", help="only time presses of this KeyCode name (for example Space)")
    ap.add_argument("--subject", help="simulation logs: the id to measure (for example p1)")
    ap.add_argument("--interval", action="append", metavar="NAME=A..B",
                    help="time from each event A to the next event B, as metric NAME (repeatable)")
    ap.add_argument("--hz", type=float, help="tick rate for frame counts when the log has no simulation header")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    latency: list = []
    meta: dict = {}
    samples, events, bad = parse_log(args.log, args.tag, latency, subject=args.subject, meta=meta)
    if not samples and not events and not latency:
        rc.fail(f"no {args.tag} lines found in {args.log}; enable the MeasurementHarness and copy the full Output", rc.EXIT_FAIL)
    intervals = parse_intervals(args.interval)
    hz = args.hz or meta.get("hz")
    if not samples and not latency and not intervals:
        rc.fail(f"{args.log} has events but no motion samples: the harness never bound a character. Games without "
                "a Humanoid (custom simulations, fighting games) must log through SimRecorder (assets/rojo-template/src/shared/Remake/SimRecorder.luau).",
                rc.EXIT_FAIL)
    targets = {}
    if args.targets:
        data = rc.read_json(args.targets)
        targets = data.get("metrics", {}) if isinstance(data, dict) else {}
    derived = derive(samples, events, latency, args.latency_key, meta.get("grounded"), intervals)
    unpaired = derived.pop("_unpaired", {})
    timed = TIME_METRICS | set(intervals)
    results = {name: judge(vals, targets.get(name), hz, name in timed) for name, vals in derived.items()}
    failed = [n for n, r in results.items() if r["status"] == "fail"]
    missing = [n for n, r in results.items() if r["status"] == "not-observed" and targets.get(n, {}).get("target") is not None]
    ok = not failed and (args.allow_missing or not missing)
    judged = [n for n, r in results.items() if r["status"] in ("pass", "fail")]
    status = "fail" if not ok else ("pass" if judged else "unchecked")
    timeouts = sum(1 for lat in latency if (lat["f"] is None or lat["f"] < 0) and (not args.latency_key or lat["key"] == args.latency_key))
    report = {"tool": TOOL, "log": str(args.log), "subject": args.subject, "subjects": meta.get("ids") or [], "hz": hz,
              "samples": len(samples), "events": len(events), "unparsed_lines": bad, "status": status,
              "unpaired_intervals": unpaired,
              "latency_presses": len(latency), "latency_timeouts": timeouts,
              "metrics": results, "failed": failed, "missing": missing, "pass": ok}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{len(samples)} samples, {len(events)} events from {args.log}" + (f" ({bad} unparsed lines)" if bad else ""))
        if latency:
            print(f"{len(latency)} timed presses" + (f", {timeouts} with no visible change before the timeout" if timeouts else ""))
        for name, r in results.items():
            unit = " frames" if r.get("unit") == "frames" else ""
            fr = f" = {r['mean_frames']} frames" if r.get("mean_frames") is not None else ""
            if r["status"] in ("pass", "fail"):
                print(f"{r['status'].upper():<5} {name:<15} {r['mean']}{unit}{fr} (n={r['n']}, std {r['std']}) "
                      f"target {r['target']} ± {r['tolerance']}  error {r['error']:+}")
            elif r["status"] == "no-target":
                print(f"info  {name:<15} {r['mean']}{unit}{fr} (n={r['n']}, std {r['std']})")
            elif name in missing:
                print(f"MISS  {name:<15} not observed (reproduce this test in the playtest)")
        for name, n in unpaired.items():
            print(f"note  {name:<15} {n} start event(s) had no end before the next start (not averaged)")
        if status == "unchecked":
            print("result: unchecked - no metric has a target, nothing was judged (pass --targets)")
        else:
            print("result: " + ("pass" if ok else "FAIL"))
    return rc.EXIT_OK if ok else rc.EXIT_FAIL


if __name__ == "__main__":
    rc.run_main(main)
