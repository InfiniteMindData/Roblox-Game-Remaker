#!/usr/bin/env python3
"""Statistics for game systems logged from footage: intervals, rates, state machines, curves.

Input: an event table (CSV with a header) that you log while stepping through frames, one row
per event:
  frame or t   source frame index (converted with --fps, or exactly with --manifest) or seconds
  event        what happened: spawn, attack, drop, level_up, state name, ...
  entity       optional: which enemy, spawner or player (intervals and states are per entity)
  other        any extra columns (outcome, item, value, ...) used by --rate and --series

Analyses (combine freely; with none given, every event type with 3 or more rows gets intervals):
  --intervals EVENT      gaps between consecutive EVENT rows (per entity): mean with a Student-t
                         confidence interval, spread, min and max, each ±1 frame of quantization;
                         says whether the gap looks fixed (spread within quantization) or random,
                         and gives the shortest gap as an upper bound for a cooldown
  --rate A/B             successes A per trial B (for example drop/kill)
  --rate EVENT:col=val   share of EVENT rows whose column col equals val (for example kill:loot=rare)
  --counts K/N           a rate from counts you already have
                         rates are reported as k of n with an exact (Clopper-Pearson) interval and
                         the Wilson interval, never as a bare percentage; with --plan-halfwidth,
                         how many trials the interval needs to shrink to that half-width
  --states a,b,c         reconstruct a state machine from those events (or --state-column):
                         transition counts and dwell time per state
  --series EVENT:col     fit col against occurrence number (level 1, 2, ...) with linear,
                         quadratic, exponential and power curves (progression and economy)

Every result carries its sample size, a method, and an uncertainty; small samples are flagged.

Examples:
  python event_stats.py remake/systems/wave1.csv --fps 60 --intervals spawn --by entity
  python event_stats.py remake/systems/loot.csv --fps 60 --rate drop/kill --plan-halfwidth 0.05
  python event_stats.py --counts 3/20
  python event_stats.py remake/systems/boss.csv --manifest remake/frames/boss/manifest.json --states idle,windup,attack,recover
  python event_stats.py remake/systems/levels.csv --fps 60 --series level_up:xp --out remake/systems/levels.json
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "event_stats"
SCHEMA = 1


# ----------------------------------------------------------------- distributions (no SciPy)

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c if abs(1 + aa / c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c if abs(1 + aa / c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-14:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1 - math.exp(lbt) * _betacf(b, a, 1 - x) / b


def _invert(f, target: float, lo: float, hi: float) -> float:
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def beta_ppf(q: float, a: float, b: float) -> float:
    return _invert(lambda x: betainc(a, b, x), q, 0.0, 1.0)


def t_ppf(q: float, df: float) -> float:
    """Student t quantile (q > 0.5)."""
    def cdf(t):
        x = df / (df + t * t)
        tail = 0.5 * betainc(df / 2, 0.5, x)
        return 1 - tail if t >= 0 else tail
    return _invert(cdf, q, -1e3, 1e3)


def clopper_pearson(k: int, n: int, conf: float) -> tuple[float, float]:
    a = 1 - conf
    lo = 0.0 if k == 0 else beta_ppf(a / 2, k, n - k + 1)
    hi = 1.0 if k == n else beta_ppf(1 - a / 2, k + 1, n - k)
    return lo, hi


def z_ppf(q: float) -> float:
    return _invert(lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2))), q, -40.0, 40.0)


def wilson(k: int, n: int, conf: float) -> tuple[float, float]:
    z = z_ppf(1 - (1 - conf) / 2)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def trials_for_halfwidth(p: float, halfwidth: float, conf: float) -> int:
    """Smallest n whose exact interval around n*p successes has a half-width <= halfwidth."""
    z = z_ppf(1 - (1 - conf) / 2)
    n = max(2, int(z * z * max(p * (1 - p), 0.25 / 100) / halfwidth ** 2 * 0.8))
    while n < 10_000_000:
        k = int(round(p * n))
        lo, hi = clopper_pearson(k, n, conf)
        if (hi - lo) / 2 <= halfwidth:
            return n
        n = int(n * 1.05) + 1
    return n


# ----------------------------------------------------------------- input

def load_events(path: Path, fps: float | None, manifest: Path | None):
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except FileNotFoundError:
        rc.fail(f"file not found: {path}")
    if not rows:
        rc.fail(f"{path} has no rows")
    cols = set(rows[0].keys())
    if "event" not in cols or not ({"frame", "t"} & cols):
        rc.fail(f"{path} needs an 'event' column and a 'frame' or 't' column (has: {', '.join(sorted(cols))})")
    pts = None
    if manifest:
        _, frames, _ = rc.load_manifest(manifest)
        pts = {int(f["index"]): float(f["pts_time"]) for f in frames if f.get("index") is not None}
    out = []
    for i, r in enumerate(rows, 2):
        ev = (r.get("event") or "").strip()
        if not ev:
            rc.fail(f"{path}:{i}: empty event")
        if r.get("t") not in (None, ""):
            try:
                t = float(r["t"])
            except ValueError:
                rc.fail(f"{path}:{i}: t must be a number")
            frame = None
        else:
            try:
                frame = int(float(r["frame"]))
            except (TypeError, ValueError):
                rc.fail(f"{path}:{i}: frame must be a number")
            if pts is not None:
                if frame not in pts:
                    rc.fail(f"{path}:{i}: frame {frame} is not in the manifest")
                t = pts[frame]
            elif fps:
                t = frame / fps
            else:
                rc.fail("frames need --fps or --manifest to become times")
        out.append({**{k: (v or "").strip() for k, v in r.items()}, "event": ev, "_t": t, "_frame": frame, "_line": i})
    out.sort(key=lambda r: r["_t"])
    return out


# ----------------------------------------------------------------- analyses

def interval_stats(rows, event: str, by: str | None, frame_s: float, conf: float) -> dict:
    groups: dict[str, list[float]] = {}
    for r in rows:
        if r["event"] == event:
            groups.setdefault(r.get(by, "") if by else "", []).append(r["_t"])
    gaps = []
    for ts in groups.values():
        gaps += [b - a for a, b in zip(ts, ts[1:])]
    n = len(gaps)
    res = {"event": event, "by": by, "groups": len(groups), "occurrences": sum(len(v) for v in groups.values()), "gaps": n}
    if n == 0:
        res["note"] = "fewer than two occurrences in every group: no gaps"
        return res
    mean = sum(gaps) / n
    sd = math.sqrt(sum((g - mean) ** 2 for g in gaps) / (n - 1)) if n > 1 else 0.0
    quant = frame_s  # each event is known to about half a frame either side, so each gap to about one frame
    half = t_ppf(1 - (1 - conf) / 2, n - 1) * sd / math.sqrt(n) if n > 1 else float("inf")
    srt = sorted(gaps)
    res.update({"mean_s": round(mean, 5), "sd_s": round(sd, 5), "median_s": round(srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2, 5),
                "min_s": round(srt[0], 5), "max_s": round(srt[-1], 5), "quantization_s": round(quant, 5),
                "mean_ci_halfwidth_s": round(math.hypot(half, quant / math.sqrt(n)) if math.isfinite(half) else half, 5),
                "confidence": conf})
    fixed = sd <= quant
    res["pattern"] = "fixed" if fixed else "variable"
    notes = []
    if n < 2:
        notes.append("one gap only: no spread can be estimated; log more occurrences")
    elif fixed:
        notes.append(f"the gaps vary by no more than one frame: a fixed interval of {mean:.4f} s ± {quant:.4f} s")
    else:
        cv = sd / mean if mean > 0 else float("inf")
        notes.append(f"the gaps vary (sd {sd:.4f} s, {100 * cv:.0f}% of the mean): a random or state-dependent interval; "
                     f"model the range {srt[0]:.4f}..{srt[-1]:.4f} s, not only the mean")
    notes.append(f"a cooldown on {event} is at most {srt[0]:.4f} s + {quant:.4f} s (the shortest gap); "
                 "it equals that only if the input was pressed as fast as possible")
    if n < 10:
        notes.append(f"only {n} gaps: the mean's interval is wide; log at least 10 for a stable mean, 30 for the spread")
    res["notes"] = notes
    return res


def rate_from_rows(rows, spec: str) -> tuple[str, int, int]:
    m = re.match(r"^([\w.-]+)/([\w.-]+)$", spec)
    if m:
        a, b = m.groups()
        k = sum(1 for r in rows if r["event"] == a)
        n = sum(1 for r in rows if r["event"] == b)
        if k > n:
            rc.fail(f"--rate {spec}: {k} {a} rows but only {n} {b} rows; a rate needs successes <= trials")
        return f"{a} per {b}", k, n
    m = re.match(r"^([\w.-]+):([\w.-]+)=(.+)$", spec)
    if m:
        ev, col, val = m.groups()
        sel = [r for r in rows if r["event"] == ev]
        if sel and col not in sel[0]:
            rc.fail(f"--rate {spec}: no column {col!r}")
        return f"{ev} with {col}={val}", sum(1 for r in sel if r.get(col) == val), len(sel)
    rc.fail(f"--rate {spec!r}: use SUCCESS/TRIAL or EVENT:column=value")


def rate_stats(name: str, k: int, n: int, conf: float, plan: float | None) -> dict:
    if n <= 0:
        rc.fail(f"{name}: no trials")
    lo, hi = clopper_pearson(k, n, conf)
    wl, wh = wilson(k, n, conf)
    res = {"name": name, "successes": k, "trials": n, "confidence": conf,
           "interval": [round(lo, 5), round(hi, 5)], "wilson_interval": [round(wl, 5), round(wh, 5)],
           "method": f"exact binomial (Clopper-Pearson) {int(conf * 100)}% interval from {k} of {n}"}
    notes = []
    width = hi - lo
    if width > 0.2:
        notes.append(f"{k} of {n} only narrows the rate to {lo:.3f}..{hi:.3f}: treat the build value as ASSUMED inside this "
                     "range, and log more trials before calling it measured")
    if k == 0:
        notes.append(f"zero successes in {n}: the rate is at most {hi:.3f} ({int(conf * 100)}% confidence), not zero")
    if plan:
        p = max(k / n, 1e-6) if 0 < k < n else (0.5 if k else 1 / (n + 1))
        res["trials_needed"] = {"halfwidth": plan, "trials": trials_for_halfwidth(min(max(p, 1e-6), 1 - 1e-6), plan, conf),
                                "assumed_rate_center": round((lo + hi) / 2, 4)}
        notes.append(f"about {res['trials_needed']['trials']} trials give an interval half-width of {plan} at this rate")
    res["notes"] = notes
    return res


def state_stats(rows, states: list[str] | None, column: str | None, by: str | None) -> dict:
    seq: dict[str, list[tuple[float, str]]] = {}
    for r in rows:
        st = r.get(column) if column else (r["event"] if r["event"] in states else None)
        if st:
            seq.setdefault(r.get(by, "") if by else "", []).append((r["_t"], st))
    trans: dict[tuple[str, str], int] = {}
    dwell: dict[str, list[float]] = {}
    for items in seq.values():
        for (t0, a), (t1, b) in zip(items, items[1:]):
            trans[(a, b)] = trans.get((a, b), 0) + 1
            dwell.setdefault(a, []).append(t1 - t0)
    out_tr = []
    for (a, b), c in sorted(trans.items()):
        total = sum(v for (x, _), v in trans.items() if x == a)
        out_tr.append({"from": a, "to": b, "count": c, "of": total})
    out_dw = {}
    for s, v in sorted(dwell.items()):
        mean = sum(v) / len(v)
        sd = math.sqrt(sum((x - mean) ** 2 for x in v) / (len(v) - 1)) if len(v) > 1 else 0.0
        out_dw[s] = {"n": len(v), "mean_s": round(mean, 5), "sd_s": round(sd, 5), "min_s": round(min(v), 5), "max_s": round(max(v), 5)}
    names = sorted({s for items in seq.values() for _, s in items})
    unseen = [s for s in (states or []) if s not in names]
    notes = [f"never observed: {', '.join(unseen)}"] if unseen else []
    notes += [f"{a} -> {b} seen once: a rare branch or a logging mistake; confirm it on the frames"
              for (a, b), c in trans.items() if c == 1 and sum(v for (x, _), v in trans.items() if x == a) > 3]
    return {"states": names, "transitions": out_tr, "dwell": out_dw, "notes": notes}


def series_stats(rows, spec: str) -> dict:
    np = rc.require_numpy()
    if ":" not in spec:
        rc.fail("--series is EVENT:column")
    ev, col = spec.split(":", 1)
    vals = []
    for r in rows:
        if r["event"] == ev:
            try:
                vals.append(float(r[col]))
            except (KeyError, ValueError):
                rc.fail(f"--series {spec}: row {r['_line']} has no numeric {col!r}")
    n = len(vals)
    if n < 3:
        rc.fail(f"--series {spec}: needs at least 3 rows (got {n})")
    x = np.arange(1, n + 1, dtype=float)
    y = np.array(vals)
    fits = []

    def add(name, pred, params, k):
        rms = float(np.sqrt(((y - pred) ** 2).mean()))
        fits.append({"model": name, "params": {a: round(float(b), 6) for a, b in params.items()}, "rms": round(rms, 6), "k": k})

    b, a = np.polyfit(x, y, 1)
    add("linear", a + b * x, {"a": a, "b": b}, 2)
    if n >= 4:
        c2, c1, c0 = np.polyfit(x, y, 2)
        add("quadratic", c0 + c1 * x + c2 * x * x, {"a": c0, "b": c1, "c": c2}, 3)
    if np.all(y > 0):
        lb, la = np.polyfit(x, np.log(y), 1)
        add("exponential", np.exp(la + lb * x), {"a": math.exp(la), "ratio": math.exp(lb)}, 2)
        pb, pa = np.polyfit(np.log(x), np.log(y), 1)
        add("power", np.exp(pa) * x ** pb, {"a": math.exp(pa), "exponent": pb}, 2)
    fits.sort(key=lambda f: f["rms"])
    notes = []
    if n < 6:
        notes.append(f"only {n} points: several curves fit; log more levels before choosing")
    if len(fits) > 1 and fits[1]["rms"] < 1.5 * fits[0]["rms"]:
        notes.append(f"{fits[0]['model']} and {fits[1]['model']} fit about equally well; extrapolate neither far")
    return {"series": spec, "n": n, "values": vals, "fits": fits, "best": fits[0]["model"], "notes": notes}


# ----------------------------------------------------------------- cli

def measurement(metric, what, value, unc, unit, method, **extra):
    return {"metric": metric, "what": what, "value": round(value, 6), "uncertainty": round(unc, 6), "unit": unit,
            "method": method, **extra}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("events", type=Path, nargs="?", help="event table CSV")
    ap.add_argument("--fps", type=float, help="frame rate to turn frame numbers into seconds")
    ap.add_argument("--manifest", type=Path, help="extract_frames manifest: exact pts_time per frame (variable frame rate)")
    ap.add_argument("--intervals", action="append", default=[], help="event whose gaps to analyze (repeatable)")
    ap.add_argument("--by", help="column that groups rows (entity) for intervals and states")
    ap.add_argument("--rate", action="append", default=[], help="SUCCESS/TRIAL or EVENT:column=value (repeatable)")
    ap.add_argument("--counts", action="append", default=[], help="K/N from counts you already have (repeatable)")
    ap.add_argument("--states", help="comma-separated events that are states")
    ap.add_argument("--state-column", help="column holding the state name")
    ap.add_argument("--series", action="append", default=[], help="EVENT:column to fit against occurrence number")
    ap.add_argument("--confidence", type=float, default=0.95)
    ap.add_argument("--plan-halfwidth", type=float, help="report trials needed for this rate interval half-width")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if not 0.5 < args.confidence < 1:
        rc.fail("--confidence must be between 0.5 and 1")
    if not args.events and not args.counts:
        rc.fail("give an event table, or --counts K/N")

    rows = load_events(args.events, args.fps, args.manifest) if args.events else []
    frame_s = 1 / args.fps if args.fps else 0.0
    if args.manifest and rows:
        ts = sorted({r["_t"] for r in rows})
        _, frames, _ = rc.load_manifest(args.manifest)
        pt = sorted(float(f["pts_time"]) for f in frames)
        frame_s = max((b - a for a, b in zip(pt, pt[1:])), default=0.0)
    if rows and frame_s == 0 and all(r["_frame"] is None for r in rows):
        frame_s = 0.0  # times given in seconds: quantization unknown; say so below
    report = {"tool": TOOL, "schema": SCHEMA, "source": str(args.events) if args.events else None,
              "rows": len(rows), "events": {}, "intervals": [], "rates": [], "states": None, "series": [],
              "measurements": [], "warnings": []}
    for r in rows:
        report["events"][r["event"]] = report["events"].get(r["event"], 0) + 1
    if rows and frame_s == 0:
        report["warnings"].append("times were given in seconds without --fps: frame quantization is not included in the uncertainties")

    targets = args.intervals or ([e for e, c in report["events"].items() if c >= 3]
                                 if not (args.rate or args.counts or args.states or args.state_column or args.series) else [])
    src = Path(args.events).name if args.events else "counts"
    for ev in targets:
        st = interval_stats(rows, ev, args.by, frame_s, args.confidence)
        report["intervals"].append(st)
        if st["gaps"] >= 2:
            method = (f"event_stats {src}: {st['gaps']} gaps between {ev} rows"
                      + (f" per {args.by}" if args.by else "") + f"; mean with a {int(args.confidence * 100)}% Student-t interval "
                      f"and ±1 frame quantization; {st['pattern']} pattern")
            report["measurements"].append(measurement(f"event_interval_{ev}", f"interval between {ev} events ({st['pattern']}; "
                                                      f"range {st['min_s']}..{st['max_s']} s)", st["mean_s"], st["mean_ci_halfwidth_s"],
                                                      "s", method, n=st["gaps"]))
    for spec in args.rate + args.counts:
        if spec in args.counts:
            m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", spec)
            if not m:
                rc.fail(f"--counts {spec!r}: use K/N, for example 3/20")
            name, k, n = f"counts {spec}", int(m.group(1)), int(m.group(2))
            if k > n:
                rc.fail(f"--counts {spec}: successes exceed trials")
        else:
            if not rows:
                rc.fail("--rate needs an event table")
            name, k, n = rate_from_rows(rows, spec)
        st = rate_stats(name, k, n, args.confidence, args.plan_halfwidth)
        report["rates"].append(st)
        lo, hi = st["interval"]
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        report["measurements"].append(measurement(
            f"rate_{slug}", f"{name}: {k} of {n} ({int(args.confidence * 100)}% interval {lo:.4f}..{hi:.4f}); value = interval midpoint",
            (lo + hi) / 2, (hi - lo) / 2, "probability", f"event_stats {src}: {st['method']}", successes=k, trials=n, interval=[lo, hi]))
    if args.states or args.state_column:
        if not rows:
            rc.fail("--states needs an event table")
        states = [s.strip() for s in args.states.split(",")] if args.states else None
        report["states"] = state_stats(rows, states, args.state_column, args.by)
        for s, d in report["states"]["dwell"].items():
            if d["n"] >= 2:
                half = t_ppf(1 - (1 - args.confidence) / 2, d["n"] - 1) * d["sd_s"] / math.sqrt(d["n"])
                report["measurements"].append(measurement(
                    f"event_dwell_{s}", f"time in state {s} (range {d['min_s']}..{d['max_s']} s)", d["mean_s"],
                    math.hypot(half, frame_s / math.sqrt(d["n"])), "s",
                    f"event_stats {src}: {d['n']} visits to {s}; mean with a Student-t interval and frame quantization", n=d["n"]))
    for spec in args.series:
        if not rows:
            rc.fail("--series needs an event table")
        report["series"].append(series_stats(rows, spec))
    if args.out:
        rc.write_json(args.out, report)
    if args.json:
        print(rc.dump_json(report))
        return 0
    if rows:
        print(f"{len(rows)} events: " + ", ".join(f"{k} {v}" for k, v in sorted(report["events"].items())))
    for st in report["intervals"]:
        if st["gaps"] == 0:
            print(f"intervals {st['event']}: {st['note']}")
            continue
        print(f"intervals {st['event']}: {st['gaps']} gaps; mean {st['mean_s']} ± {st['mean_ci_halfwidth_s']} s "
              f"({int(args.confidence * 100)}%); sd {st['sd_s']}; range {st['min_s']}..{st['max_s']} s; {st['pattern']}")
        for n_ in st["notes"]:
            print(f"  - {n_}")
    for st in report["rates"]:
        lo, hi = st["interval"]
        print(f"rate {st['name']}: {st['successes']} of {st['trials']}; {int(st['confidence'] * 100)}% interval "
              f"{lo:.4f}..{hi:.4f} (Wilson {st['wilson_interval'][0]:.4f}..{st['wilson_interval'][1]:.4f})")
        for n_ in st["notes"]:
            print(f"  - {n_}")
    if report["states"]:
        s = report["states"]
        for tr in s["transitions"]:
            print(f"transition {tr['from']} -> {tr['to']}: {tr['count']} of {tr['of']}")
        for name, d in s["dwell"].items():
            print(f"dwell {name}: n {d['n']}, mean {d['mean_s']} s, sd {d['sd_s']}, range {d['min_s']}..{d['max_s']} s")
        for n_ in s["notes"]:
            print(f"  - {n_}")
    for st in report["series"]:
        print(f"series {st['series']} (n {st['n']}): " + "; ".join(f"{f['model']} rms {f['rms']} {f['params']}" for f in st["fits"]))
        for n_ in st["notes"]:
            print(f"  - {n_}")
    for w in report["warnings"]:
        print(f"WARNING: {w}", file=sys.stderr)
    if args.out:
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    rc.run_main(main)
