#!/usr/bin/env python3
"""Compare a recording of the Roblox build with the reference clip over time.

REF and REC can each be:
  - motion_track output (side-on: u = horizontal, v = up)
  - camera_solve ground output (third-person track converted to the ground plane)
  - a MeasurementHarness log (REMAKE_MEASURE lines; positions in studs)
  - an extract_frames manifest.json, tracked here with --ref-bbox / --rec-bbox
    (and --ref-px-per-unit / --rec-px-per-unit for world units)

Every input becomes two series in its own unit: "along", the signed distance travelled along the
clip's net horizontal direction (orientation-independent), and "up", the height change (absent
for ground-plane tracks). The two clips are aligned on a shared event (the first motion, found by
back-extrapolating the start of the movement, or a given frame in each), zeroed at that event,
resampled to a common time base, and compared:

  position_rms / position_max   recreation minus reference, per axis and combined
  bias                          mean signed error per axis
  events                        motion_start, speed_90 (90% of steady speed), apex, landing,
                                stop: time since alignment in each clip, and the offset
  floor                         the error that frame quantization alone produces (peak speed x
                                half the coarser frame period); differences below it are noise

Tolerances come from targets.json ("clips": {"default": {...}, "<--clip id>": {...}}) or flags:
  position_rms, position_max (absolute, in the clips' unit) or position_rms_pct,
  position_max_pct (percent of the reference's travel); event_offset_s or event_offset_frames.

Writes --out JSON and --plot PNG (position versus time, both clips, events marked).
Exit: 0 pass (or no tolerances), 1 a tolerance is exceeded, 2 bad input.

Examples:
  python clip_compare.py remake/tracks/run-ref.json remake/logs/run-03.log --targets remake/targets.json \\
      --out remake/diff/run-03/clip.json --plot remake/diff/run-03/clip.png
  python clip_compare.py ref/manifest.json rec/manifest.json --ref-bbox 90,200,20,20 --rec-bbox 88,201,20,20 \\
      --ref-px-per-unit 20 --rec-px-per-unit 20 --align frames --ref-frame 12 --rec-frame 40
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "clip_compare"
SCHEMA = 1
EVENT_NAMES = ("motion_start", "speed_90", "apex", "landing", "stop")


# ----------------------------------------------------------------- loading

class Clip:
    def __init__(self, label, t, along, up, unit, source, kind, index=None, notes=None):
        np = rc.require_numpy()
        order = np.argsort(t)
        self.label, self.unit, self.source, self.kind = label, unit, source, kind
        self.t = np.asarray(t, float)[order]
        self.along = np.asarray(along, float)[order]
        self.up = None if up is None else np.asarray(up, float)[order]
        self.index = None if index is None else [index[i] for i in order]
        self.notes = notes or []
        if len(self.t) < 5:
            rc.fail(f"{label}: needs at least 5 samples (got {len(self.t)})")
        dts = np.diff(self.t)
        if np.any(dts <= 0):
            rc.fail(f"{label}: timestamps are not strictly increasing")
        self.dt = float(np.median(dts))


def _project_along(dx, dz):
    """Signed distance along the net horizontal direction of travel (start to end)."""
    np = rc.require_numpy()
    dx, dz = np.asarray(dx, float), np.asarray(dz, float)
    n = math.hypot(dx[-1], dz[-1])
    if n < 1e-9:
        far = int(np.argmax(np.hypot(dx, dz)))
        n = math.hypot(dx[far], dz[far])
        if n < 1e-9:
            return dx * 0.0
        return (dx * dx[far] + dz * dz[far]) / n
    return (dx * dx[-1] + dz * dz[-1]) / n


def load_clip(path: Path, side: str, args) -> Clip:
    np = rc.require_numpy()
    if not path.exists():
        rc.fail(f"{side}: file not found: {path}")
    if path.is_dir() or path.suffix.lower() == ".json":
        data = rc.read_json(path / "manifest.json" if path.is_dir() else path)
        if isinstance(data, dict) and isinstance(data.get("frames"), list):
            return track_manifest(path, side, args)
        if not isinstance(data, dict):
            rc.fail(f"{side}: {path} is not tool output")
        tool = data.get("tool")
        if tool == "motion_track":
            s = data.get("samples") or []
            u = [r["u"] for r in s]
            sign = 1.0 if (u[-1] - u[0]) >= 0 else -1.0
            notes = []
            if data.get("low_score_samples"):
                notes.append(f"{data['low_score_samples']} low-score samples in the track")
            return Clip(side, [r["t"] for r in s], [sign * (x - u[0]) for x in u], [r["v"] - s[0]["v"] for r in s],
                        data.get("unit", "px"), str(path), "motion_track", [r.get("index") for r in s], notes)
        if tool == "camera_solve" and isinstance(data.get("track"), dict):
            s = data["track"].get("samples") or []
            if not s:
                rc.fail(f"{side}: {path} has no converted track samples")
            along = _project_along([r["X"] - s[0]["X"] for r in s], [r["Z"] - s[0]["Z"] for r in s])
            notes = list(data.get("warnings") or [])
            return Clip(side, [r["t"] for r in s], along, None, data.get("unit", "studs"), str(path), "camera_solve ground",
                        [r.get("index") for r in s], notes)
        rc.fail(f"{side}: {path} is neither motion_track nor camera_solve ground output, nor a frame manifest")
    # Anything else is treated as a harness log.
    import measure_compare

    samples, events, _ = measure_compare.parse_log(path, measure_compare.TAG)
    if len(samples) < 5:
        rc.fail(f"{side}: {path} has fewer than 5 REMAKE_MEASURE samples")
    p = np.array([s["p"] for s in samples], float)
    along = _project_along(p[:, 0] - p[0, 0], p[:, 2] - p[0, 2])
    return Clip(side, [s["t"] for s in samples], along, p[:, 1] - p[0, 1], "studs", str(path), "harness log")


def track_manifest(path: Path, side: str, args) -> Clip:
    import motion_track

    bbox_text = getattr(args, f"{side}_bbox")
    if not bbox_text:
        rc.fail(f"{side}: {path} is a frame manifest; give --{side}-bbox x,y,w,h for the feature to track")
    _, frames, base = rc.load_manifest(path)
    images = [rc.load_gray(base / f["file"]) for f in frames]
    if len(images) < 5:
        rc.fail(f"{side}: needs at least 5 frames")
    times = [float(f.get("pts_time", i / 60.0)) for i, f in enumerate(frames)]
    pts = motion_track.track(images, rc.parse_bbox(bbox_text, f"--{side}-bbox"), args.search, 1, scale_search=args.scale_search)
    ppu = getattr(args, f"{side}_px_per_unit")
    k = 1.0 / ppu if ppu else 1.0
    x0, y0 = pts[0][0], pts[0][1]
    u = [(p[0] - x0) * k for p in pts]
    sign = 1.0 if u[-1] >= 0 else -1.0
    low = sum(1 for p in pts if p[2] < 0.6)
    notes = [f"{low} low-score samples while tracking"] if low else []
    return Clip(side, times, [sign * x for x in u], [(y0 - p[1]) * k for p in pts], args.unit if ppu else "px",
                str(path), "frames tracked here", [f.get("index") for f in frames], notes)


# ----------------------------------------------------------------- events

def magnitude(c: Clip):
    np = rc.require_numpy()
    return np.hypot(c.along, c.up) if c.up is not None else np.abs(c.along)


def motion_start(c: Clip, thresh_frac: float) -> float:
    """Time the clip starts moving: threshold crossing, back-extrapolated to zero displacement."""
    np = rc.require_numpy()
    m = magnitude(c)
    n0 = max(3, len(m) // 10)
    noise = float(np.median(np.abs(m[:n0] - np.median(m[:n0]))) * 1.4826)
    travel = float(m.max())
    if travel <= 0:
        rc.fail(f"{c.label}: no motion in the clip")
    eps = max(4 * noise, thresh_frac * travel)
    above = np.nonzero(m > eps)[0]
    if len(above) == 0:
        rc.fail(f"{c.label}: no motion above the noise floor")
    k = int(above[0])
    if k == 0:
        c.notes.append("moving from the first sample: the motion start is not observed; align on frames instead")
        return float(c.t[0])
    # Fit the first moving samples with a parabola (a start from rest, or a takeoff at speed) and
    # take its zero crossing between the last still sample and the first moving one.
    hi = min(len(m) - 1, k + 3)
    while hi + 1 < len(m) and m[hi + 1] < 3 * eps and hi - k < 8:
        hi += 1
    tt, mm = c.t[k:hi + 1], m[k:hi + 1]
    lo_t, hi_t = max(float(c.t[0]) - c.dt, float(c.t[k]) - 1.0), float(c.t[k])
    roots = []
    if len(tt) >= 4:
        a, b, cc = (float(v) for v in np.polyfit(tt - c.t[k], mm, 2))
        if abs(a) < 1e-12:
            roots = [-cc / b] if abs(b) > 1e-12 else []
        else:
            disc = b * b - 4 * a * cc
            if disc < 0:  # a start from rest is a double root; noise can push it just below zero
                roots = [-b / (2 * a)]
            else:
                roots = [(-b - math.sqrt(disc)) / (2 * a), (-b + math.sqrt(disc)) / (2 * a)]
    elif len(tt) >= 2:
        b, cc = (float(v) for v in np.polyfit(tt - c.t[k], mm, 1))
        roots = [-cc / b] if abs(b) > 1e-12 else []
    cand = [float(c.t[k]) + r for r in roots if lo_t <= float(c.t[k]) + r <= hi_t]
    if cand:
        return max(cand)
    t_cross = float(c.t[k - 1] + (eps - m[k - 1]) / max(1e-12, m[k] - m[k - 1]) * (c.t[k] - c.t[k - 1]))
    c.notes.append("could not back-extrapolate the motion start; using the threshold crossing (late by up to a frame)")
    return t_cross


def _cross_time(t, y, level, start_i, rising=True):
    for i in range(max(1, start_i), len(y)):
        if (y[i] >= level) if rising else (y[i] <= level):
            y0, y1 = y[i - 1], y[i]
            frac = 0.0 if y1 == y0 else (level - y0) / (y1 - y0)
            return float(t[i - 1] + min(1.0, max(0.0, frac)) * (t[i] - t[i - 1]))
    return None


def events(c: Clip, t_align: float, thresh_frac: float) -> dict:
    np = rc.require_numpy()
    out = {"motion_start": motion_start(c, thresh_frac) - t_align}
    v = np.gradient(c.along, c.t)
    if len(v) >= 3:
        v = np.convolve(v, np.ones(3) / 3, mode="same")
        v[0], v[-1] = v[1], v[-2]
    peak = float(np.percentile(v, 95))
    travel_along = float(np.abs(c.along).max())
    if peak > 0 and travel_along > 0.1 * float(magnitude(c).max()):
        tail = v[len(v) * 6 // 10:]
        steady = float(np.median(tail)) if np.median(tail) > 0.5 * peak else peak
        i0 = int(np.searchsorted(c.t, out["motion_start"] + t_align))
        t90 = _cross_time(c.t, v, 0.9 * steady, i0)
        if t90 is not None:
            out["speed_90"] = t90 - t_align
            ipk = int(np.argmax(v))
            t_stop = _cross_time(c.t, v, 0.1 * peak, ipk + 1, rising=False)
            if t_stop is not None:
                out["stop"] = t_stop - t_align
    if c.up is not None:
        m = magnitude(c)
        ia = int(np.argmax(c.up))
        rise = float(c.up[ia] - c.up[0])
        if 0 < ia < len(c.up) - 1 and rise > 0.2 * float(m.max()):
            # Sub-sample apex from a parabola through the three highest samples.
            y0, y1, y2 = c.up[ia - 1], c.up[ia], c.up[ia + 1]
            den = y0 - 2 * y1 + y2
            off = 0.5 * (y0 - y2) / den if abs(den) > 1e-12 else 0.0
            out["apex"] = float(c.t[ia] + max(-0.5, min(0.5, off)) * (c.t[ia + 1] - c.t[ia])) - t_align
            land = _cross_time(c.t, c.up, float(c.up[0]) + 0.05 * rise, ia + 1, rising=False)
            if land is not None:
                out["landing"] = land - t_align
    return out


def frame_time(c: Clip, frame: int) -> float:
    if c.index and frame in c.index:
        return float(c.t[c.index.index(frame)])
    if c.index and any(i is not None for i in c.index):
        rc.fail(f"{c.label}: frame {frame} is not in the clip (frames {c.index[0]}..{c.index[-1]})")
    if not 0 <= frame < len(c.t):
        rc.fail(f"{c.label}: sample {frame} is out of range")
    return float(c.t[frame])


# ----------------------------------------------------------------- comparison

def tolerances(args, ref_travel: float) -> dict:
    spec = {}
    if args.targets:
        data = rc.read_json(args.targets)
        clips = data.get("clips", {}) if isinstance(data, dict) else {}
        spec.update(clips.get("default") or {})
        if args.clip:
            if args.clip not in clips:
                rc.fail(f"--clip {args.clip}: no such entry in {args.targets} 'clips'")
            spec.update(clips[args.clip])
    for key in ("position_rms", "position_max", "event_offset_s"):
        val = getattr(args, f"tol_{key.replace('position_', '')}" if key != "event_offset_s" else "tol_event")
        if val is not None:
            spec[key] = val
    tol = {}
    for key in ("position_rms", "position_max"):
        if spec.get(key) is not None:
            tol[key] = float(spec[key])
        elif spec.get(f"{key}_pct") is not None:
            tol[key] = ref_travel * float(spec[f"{key}_pct"]) / 100.0
    if spec.get("event_offset_s") is not None:
        tol["event_offset_s"] = float(spec["event_offset_s"])
    elif spec.get("event_offset_frames") is not None:
        tol["event_offset_frames"] = float(spec["event_offset_frames"])
    return tol


def compare(ref: Clip, rec: Clip, args) -> dict:
    np = rc.require_numpy()
    if ref.unit != rec.unit:
        rc.fail(f"units differ: reference in {ref.unit}, recreation in {rec.unit}; give both clips a world scale "
                "(--ref-px-per-unit / --rec-px-per-unit, camera_solve ground, or a harness log in studs)")
    if args.align == "first-motion":
        ta_ref, ta_rec = motion_start(ref, args.motion_threshold), motion_start(rec, args.motion_threshold)
        how = "first motion (threshold crossing back-extrapolated to zero displacement)"
    elif args.align == "frames":
        if args.ref_frame is None or args.rec_frame is None:
            rc.fail("--align frames needs --ref-frame and --rec-frame")
        ta_ref, ta_rec = frame_time(ref, args.ref_frame), frame_time(rec, args.rec_frame)
        how = f"reference frame {args.ref_frame} = recreation frame {args.rec_frame}"
    else:
        ta_ref, ta_rec = float(ref.t[0]), float(rec.t[0])
        how = "clip starts"
    axes = ["along"] + (["up"] if ref.up is not None and rec.up is not None else [])
    if args.axis == "auto" and len(axes) == 2:
        # Drop an axis on which neither clip moves (a flat run has no "up"; a standing jump no "along").
        travel = {a: max(float(np.abs(getattr(c, a)).max()) for c in (ref, rec)) for a in axes}
        axes = [a for a in axes if travel[a] >= 0.05 * max(travel.values())]
    if args.axis != "auto":
        axes = [a for a in axes if a == args.axis] if args.axis != "both" else axes
        if not axes:
            rc.fail(f"--axis {args.axis} is not available for both clips (ground-plane tracks have no 'up')")
    t0 = max(ref.t[0] - ta_ref, rec.t[0] - ta_rec)
    t1 = min(ref.t[-1] - ta_ref, rec.t[-1] - ta_rec)
    if args.window:
        a, b = rc.parse_float_list(args.window, "--window")[:2]
        t0, t1 = max(t0, a), min(t1, b)
    if t1 - t0 < 3 * max(ref.dt, rec.dt):
        rc.fail(f"the aligned clips overlap for only {max(0.0, t1 - t0):.3f} s; check the alignment or --window")
    step = 1.0 / args.rate if args.rate else min(ref.dt, rec.dt)
    grid = np.arange(t0, t1 + 1e-9, step)

    def series(c, ta, name):
        y = getattr(c, name)
        y0 = float(np.interp(ta, c.t, y))
        return np.interp(grid + ta, c.t, y) - y0

    res_axes, sq = {}, np.zeros(len(grid))
    curves = {}
    for name in axes:
        r, q = series(ref, ta_ref, name), series(rec, ta_rec, name)
        e = q - r
        sq += e * e
        imax = int(np.argmax(np.abs(e)))
        res_axes[name] = {"rms": round(float(np.sqrt((e * e).mean())), 5), "max": round(float(np.abs(e[imax])), 5),
                          "max_at_s": round(float(grid[imax]), 4), "bias": round(float(e.mean()), 5),
                          "reference_travel": round(float(np.abs(r).max()), 5)}
        curves[name] = (r, q)
    comb = np.sqrt(sq)
    ref_travel = float(np.sqrt(sum(np.abs(curves[n][0]).max() ** 2 for n in axes)))
    speeds = [float(np.abs(np.gradient(getattr(c, n), c.t)).max()) for c in (ref, rec) for n in axes]
    floor = max(speeds) * max(ref.dt, rec.dt) / 2

    ev_ref, ev_rec = events(ref, ta_ref, args.motion_threshold), events(rec, ta_rec, args.motion_threshold)
    ev = {}
    prec = math.hypot(ref.dt, rec.dt)
    for name in EVENT_NAMES:
        if name in ev_ref and name in ev_rec:
            ev[name] = {"reference_s": round(ev_ref[name], 4), "recreation_s": round(ev_rec[name], 4),
                        "offset_s": round(ev_rec[name] - ev_ref[name], 4), "precision_s": round(prec, 4)}
        elif name in ev_ref or name in ev_rec:
            ev[name] = {"reference_s": round(ev_ref[name], 4) if name in ev_ref else None,
                        "recreation_s": round(ev_rec[name], 4) if name in ev_rec else None,
                        "offset_s": None, "note": "found in one clip only"}

    tol = tolerances(args, ref_travel)
    if "event_offset_frames" in tol:
        tol["event_offset_s"] = tol.pop("event_offset_frames") * max(ref.dt, rec.dt)
    failures = []
    rms, mx = float(np.sqrt((comb * comb).mean())), float(comb.max())
    if "position_rms" in tol and rms > tol["position_rms"]:
        failures.append(f"position rms {rms:.4g} > {tol['position_rms']:.4g} {ref.unit}")
    if "position_max" in tol and mx > tol["position_max"]:
        failures.append(f"position max {mx:.4g} > {tol['position_max']:.4g} {ref.unit} at {grid[int(np.argmax(comb))]:.3f} s")
    if "event_offset_s" in tol:
        for name, e in ev.items():
            if name == "motion_start" and args.align == "first-motion":
                continue  # zero by construction
            if e.get("offset_s") is not None and abs(e["offset_s"]) > tol["event_offset_s"]:
                failures.append(f"{name} offset {e['offset_s']:+.4f} s exceeds ±{tol['event_offset_s']:.4f} s")
    warnings = [f"{c.label}: {n}" for c in (ref, rec) for n in c.notes]
    if rms < floor:
        warnings.append(f"the rms error ({rms:.4g}) is below the frame-quantization floor ({floor:.4g}): the clips match "
                        "as closely as these frame rates can show")
    return {
        "tool": TOOL, "schema": SCHEMA,
        "reference": {"source": ref.source, "kind": ref.kind, "fps": round(1 / ref.dt, 3), "align_time_s": round(ta_ref, 4)},
        "recreation": {"source": rec.source, "kind": rec.kind, "fps": round(1 / rec.dt, 3), "align_time_s": round(ta_rec, 4)},
        "unit": ref.unit, "alignment": how, "axes": axes, "window_s": [round(float(t0), 4), round(float(t1), 4)],
        "resample_step_s": round(step, 6), "samples_compared": int(len(grid)),
        "position_rms": round(rms, 5), "position_max": round(mx, 5), "per_axis": res_axes,
        "floor": round(floor, 5), "events": ev, "tolerances": {k: round(v, 5) for k, v in tol.items()},
        "failures": failures, "status": ("fail" if failures else "pass") if tol else "no-tolerance",
        "method": (f"clip_compare: aligned on {how}; zeroed at the alignment event; linear resampling at {step * 1000:.2f} ms; "
                   f"floor = peak speed x half the coarser frame period"),
        "warnings": warnings,
        "_plot": (grid, curves, ev_ref, ev_rec),
    }


def plot(rep: dict, path: Path) -> None:
    grid, curves, ev_ref, ev_rec = rep["_plot"]
    panels = []
    for name, (r, q) in curves.items():
        vlines = [{"x": t, "label": f"{n} ref"} for n, t in ev_ref.items() if n != "motion_start"]
        vlines += [{"x": t, "label": f"{n} rec"} for n, t in ev_rec.items() if n != "motion_start"]
        panels.append({"title": f"{name}: position since the alignment event ({rep['unit']})", "xlabel": "time since alignment (s)",
                       "ylabel": rep["unit"], "vlines": vlines,
                       "series": [{"label": "reference", "x": grid.tolist(), "y": r.tolist()},
                                  {"label": "recreation", "x": grid.tolist(), "y": q.tolist()},
                                  {"label": "error", "x": grid.tolist(), "y": (q - r).tolist(), "color": (200, 40, 40)}]})
    rc.line_plot(path, panels, title=f"clip_compare: rms {rep['position_rms']} max {rep['position_max']} {rep['unit']} ({rep['status']})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reference", type=Path, help="reference: track JSON, camera_solve ground JSON, harness log, or frame manifest")
    ap.add_argument("recreation", type=Path, help="recreation: the same kinds")
    ap.add_argument("--align", choices=["first-motion", "frames", "start"], default="first-motion")
    ap.add_argument("--ref-frame", type=int, help="with --align frames: source frame index (or sample) in the reference")
    ap.add_argument("--rec-frame", type=int, help="with --align frames: source frame index (or sample) in the recreation")
    ap.add_argument("--axis", choices=["auto", "along", "up", "both"], default="auto")
    ap.add_argument("--window", help="a,b: compare only this time range (s since alignment)")
    ap.add_argument("--rate", type=float, help="resampling rate in Hz (default: the finer clip's frame rate)")
    ap.add_argument("--motion-threshold", type=float, default=0.02, help="fraction of the travel that counts as moving (default 0.02)")
    ap.add_argument("--targets", type=Path, help="targets.json with a 'clips' block")
    ap.add_argument("--clip", help="entry in targets.json 'clips' to use (merged over 'default')")
    ap.add_argument("--tol-rms", type=float, help="position rms tolerance (clips' unit)")
    ap.add_argument("--tol-max", type=float, help="position max tolerance (clips' unit)")
    ap.add_argument("--tol-event", type=float, help="event time offset tolerance (s)")
    ap.add_argument("--ref-bbox", help="tracking box when the reference is a frame manifest")
    ap.add_argument("--rec-bbox", help="tracking box when the recreation is a frame manifest")
    ap.add_argument("--ref-px-per-unit", type=float)
    ap.add_argument("--rec-px-per-unit", type=float)
    ap.add_argument("--unit", default="studs", help="unit name for --*-px-per-unit (default studs)")
    ap.add_argument("--search", type=int, default=64, help="tracking search radius for manifests (default 64)")
    ap.add_argument("--scale-search", action="store_true", help="track manifests with scale search")
    ap.add_argument("--out", type=Path, help="write the JSON report here")
    ap.add_argument("--plot", type=Path, help="write the position-versus-time PNG here")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    ref = load_clip(args.reference, "ref", args)
    rec = load_clip(args.recreation, "rec", args)
    rep = compare(ref, rec, args)
    if args.plot:
        plot(rep, args.plot)
        rep["plot"] = str(args.plot)
    rep.pop("_plot")
    if args.out:
        rc.write_json(args.out, rep)
    if args.json:
        print(rc.dump_json(rep))
    else:
        u = rep["unit"]
        print(f"aligned on {rep['alignment']}; compared {rep['samples_compared']} samples over {rep['window_s'][0]}..{rep['window_s'][1]} s")
        print(f"position rms {rep['position_rms']} {u}, max {rep['position_max']} {u} (frame-quantization floor {rep['floor']} {u})")
        for name, a in rep["per_axis"].items():
            print(f"  {name:<5} rms {a['rms']}  max {a['max']} at {a['max_at_s']} s  bias {a['bias']:+}  (reference travel {a['reference_travel']})")
        for name, e in rep["events"].items():
            if e.get("offset_s") is not None:
                print(f"  event {name:<12} ref {e['reference_s']:+.4f} s  rec {e['recreation_s']:+.4f} s  offset {e['offset_s']:+.4f} ± {e['precision_s']} s")
            else:
                print(f"  event {name:<12} {e.get('note')}")
        for w in rep["warnings"]:
            print(f"WARNING: {w}", file=sys.stderr)
        print("result: " + ("FAIL - " + "; ".join(rep["failures"]) if rep["failures"] else rep["status"]))
        for p in (args.out, args.plot):
            if p:
                print(f"wrote {p}")
    return rc.EXIT_FAIL if rep["failures"] else rc.EXIT_OK


if __name__ == "__main__":
    rc.run_main(main)
