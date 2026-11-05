#!/usr/bin/env python3
"""Track a feature across extracted frames and derive motion parameters.

Template matching uses FFT-based normalized cross-correlation with sub-pixel peak refinement.
An optional static anchor feature cancels translational camera motion. With --px-per-unit, the
results are in world units (studs or meters); otherwise they are in pixels.

Analyses:
  jump   parabola fit of the airborne segment: apex height, rise and fall times, gravity
         (overall and separately for rise and fall), takeoff speed
  speed  standing-start run: steady speed, time to 90% speed, and linear-ramp versus
         exponential-approach model fits
  none   positions only

Perspective caution: pixel motion is only metric when the motion is roughly parallel to the
image plane at a constant camera distance. Use side-on test clips.

Examples:
  python motion_track.py frames/jump/manifest.json --bbox 912,604,48,96 --px-per-unit 31.5 --unit studs --analyze jump --out tracks/jump.json
  python motion_track.py frames/run/manifest.json --bbox 300,500,40,80 --anchor-bbox 50,900,64,64 --analyze speed --out tracks/run.json
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "motion_track"
SCHEMA = 1


# ----------------------------------------------------------------- matching

def _integral(a):
    np = rc.require_numpy()
    return np.pad(a, ((1, 0), (1, 0))).cumsum(0).cumsum(1)


def _box_sum(ii, th, tw):
    return ii[th:, tw:] - ii[:-th, tw:] - ii[th:, :-tw] + ii[:-th, :-tw]


def ncc_map(search, tmpl):
    """Normalized cross-correlation of tmpl over every valid position in search."""
    np = rc.require_numpy()
    th, tw = tmpl.shape
    sh, sw = search.shape
    if sh < th or sw < tw:
        rc.fail("search window is smaller than the template; increase --search or move the bbox inside the frame")
    t = tmpl.astype(np.float64) - tmpl.mean()
    tnorm = math.sqrt(float((t * t).sum()))
    if tnorm < 1e-9:
        rc.fail("the template has no texture (flat color); choose a bbox with visible detail")
    s = search.astype(np.float64)
    F = np.fft.rfft2(s)
    T = np.fft.rfft2(t[::-1, ::-1], s.shape)
    full = np.fft.irfft2(F * T, s.shape)
    num = full[th - 1:sh, tw - 1:sw]
    n = th * tw
    s1 = _box_sum(_integral(s), th, tw)
    s2 = _box_sum(_integral(s * s), th, tw)
    var = np.maximum(s2 - s1 * s1 / n, 1e-9)
    return num / (np.sqrt(var) * tnorm)


def _subpixel(m, y, x):
    def refine(a, b, c):
        denom = a - 2 * b + c
        return 0.0 if abs(denom) < 1e-12 else 0.5 * (a - c) / denom

    dy = refine(m[y - 1, x], m[y, x], m[y + 1, x]) if 0 < y < m.shape[0] - 1 else 0.0
    dx = refine(m[y, x - 1], m[y, x], m[y, x + 1]) if 0 < x < m.shape[1] - 1 else 0.0
    return max(-0.5, min(0.5, dy)), max(-0.5, min(0.5, dx))


def track(frames, bbox, search: int, downscale: int, predict: bool = True):
    """Return [(cx, cy, score)] in full-resolution pixels for each frame."""
    np = rc.require_numpy()
    d = max(1, downscale)
    x, y, w, h = bbox
    xs, ys, ws, hs = x // d, y // d, max(2, w // d), max(2, h // d)
    first = frames[0]
    if ys + hs > first.shape[0] or xs + ws > first.shape[1]:
        rc.fail(f"bbox {bbox} lies outside the first frame")
    tmpl = first[ys:ys + hs, xs:xs + ws]
    r = max(2, search // d)
    out = []
    cx, cy = xs + ws / 2.0, ys + hs / 2.0
    prev = (cx, cy)
    for i, img in enumerate(frames):
        if i == 0:
            out.append((cx * d, cy * d, 1.0))
            continue
        px, py = (2 * cx - prev[0], 2 * cy - prev[1]) if predict and i > 1 else (cx, cy)
        x0 = int(max(0, math.floor(px - ws / 2.0 - r)))
        y0 = int(max(0, math.floor(py - hs / 2.0 - r)))
        x1 = int(min(img.shape[1], math.ceil(px + ws / 2.0 + r)))
        y1 = int(min(img.shape[0], math.ceil(py + hs / 2.0 + r)))
        m = ncc_map(img[y0:y1, x0:x1], tmpl)
        iy, ix = np.unravel_index(int(np.argmax(m)), m.shape)
        sdy, sdx = _subpixel(m, iy, ix)
        prev = (cx, cy)
        cx = x0 + ix + sdx + ws / 2.0
        cy = y0 + iy + sdy + hs / 2.0
        out.append((cx * d, cy * d, float(m[iy, ix])))
    return out


# ----------------------------------------------------------------- analyses

def _runs(mask):
    runs, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(mask) - 1))
    return runs


def analyze_jump(t, v, unit: str, px_unit: float, fps: float, air_range=None) -> dict:
    np = rc.require_numpy()
    t = np.asarray(t, float)
    v = np.asarray(v, float)
    n0 = max(3, len(v) // 10)
    ground = float(np.median(v[:n0]))
    noise = float(np.median(np.abs(v[:n0] - ground)) * 1.4826)
    eps = max(3 * noise, 1.5 * px_unit)
    if air_range:
        i0, i1 = air_range
    else:
        runs = _runs(v > ground + eps)
        if not runs:
            rc.fail("no airborne segment found; pass --air-range first,last (sample indexes) or check the track", rc.EXIT_FAIL)
        i0, i1 = max(runs, key=lambda r: r[1] - r[0])
    if i1 - i0 + 1 < 5:
        rc.fail("airborne segment has fewer than 5 samples; extract every frame of the jump", rc.EXIT_FAIL)
    ts, vs = t[i0:i1 + 1] - t[i0], v[i0:i1 + 1]
    # Include one grounded sample on each side so takeoff and landing are bracketed.
    if i0 > 0:
        ts = np.concatenate([[t[i0 - 1] - t[i0]], ts])
        vs = np.concatenate([[v[i0 - 1]], vs])
    if i1 + 1 < len(v):
        ts = np.concatenate([ts, [t[i1 + 1] - t[i0]]])
        vs = np.concatenate([vs, [v[i1 + 1]]])
    (a, b, c), cov = np.polyfit(ts, vs, 2, cov=True)
    if a >= 0:
        rc.fail("airborne segment is not concave (no deceleration); the tracked feature may be wrong", rc.EXIT_FAIL)

    def roots(pa, pb, pc):
        disc = pb * pb - 4 * pa * (pc - ground)
        if disc <= 0:
            rc.fail("could not intersect the jump parabola with the ground level", rc.EXIT_FAIL)
        r1 = (-pb + math.sqrt(disc)) / (2 * pa)
        r2 = (-pb - math.sqrt(disc)) / (2 * pa)
        return min(r1, r2), max(r1, r2)

    # Iterated piecewise fit: rise and fall get separate parabolas whose vertices meet at the apex.
    # This is unbiased for games that fall faster than they rise.
    ta = -b / (2 * a)
    piece = None
    for _ in range(4):
        up, down = ts <= ta, ts >= ta
        if up.sum() < 4 or down.sum() < 4:
            break
        (ar, br, cr), cov_r = np.polyfit(ts[up], vs[up], 2, cov=True)
        (af, bf, cf), cov_f = np.polyfit(ts[down], vs[down], 2, cov=True)
        if ar >= 0 or af >= 0:
            break
        ta_r, ta_f = -br / (2 * ar), -bf / (2 * af)
        piece = (ar, br, cr, af, bf, cf, ta_r, ta_f, cov_r, cov_f)
        ta = 0.5 * (ta_r + ta_f)

    res = {"segment_samples": [int(i0), int(i1)], "ground_level": round(ground, 4), "unit": unit}
    if piece:
        ar, br, cr, af, bf, cf, ta_r, ta_f, cov_r, cov_f = piece
        h_r = cr - br * br / (4 * ar) - ground
        h_f = cf - bf * bf / (4 * af) - ground
        h = 0.5 * (h_r + h_f)
        t_take = roots(ar, br, cr)[0]
        t_land = roots(af, bf, cf)[1]
        rise, fall = ta_r - t_take, t_land - ta_f
        model = np.where(ts <= ta, ar * ts * ts + br * ts + cr, af * ts * ts + bf * ts + cf)
        res.update({
            "method": "piecewise",
            "apex_height": round(h, 4),
            "apex_height_rise_fit": round(h_r, 4),
            "apex_height_fall_fit": round(h_f, 4),
            "rise_time_s": round(rise, 4),
            "fall_time_s": round(fall, 4),
            "airtime_s": round(t_land - t_take, 4),
            "g_rise": round(-2 * ar, 4),
            "g_rise_std": round(2 * math.sqrt(max(cov_r[0, 0], 0.0)), 4),
            "g_fall": round(-2 * af, 4),
            "g_fall_std": round(2 * math.sqrt(max(cov_f[0, 0], 0.0)), 4),
            "takeoff_speed": round(-2 * ar * (ta_r - t_take), 4),
        })
    else:
        h = c - b * b / (4 * a) - ground
        t_take, t_land = roots(a, b, c)
        ta = -b / (2 * a)
        rise, fall = ta - t_take, t_land - ta
        model = a * ts * ts + b * ts + c
        res.update({
            "method": "single-parabola (too few samples for separate rise/fall fits; assumes symmetric gravity)",
            "apex_height": round(h, 4),
            "rise_time_s": round(rise, 4),
            "fall_time_s": round(fall, 4),
            "airtime_s": round(t_land - t_take, 4),
            "g_rise": round(-2 * a, 4),
            "g_fall": round(-2 * a, 4),
            "takeoff_speed": round(-2 * a * rise, 4),
        })
    res["gravity_single_fit"] = round(-2 * a, 4)
    res["gravity_single_fit_std"] = round(2 * math.sqrt(max(cov[0, 0], 0.0)), 4)
    res["fit_rms"] = round(float(np.sqrt(((vs - model) ** 2).mean())), 5)
    res["time_precision_s"] = round(1.0 / fps, 5) if fps else None
    if res["g_rise"] and res["g_fall"]:
        ratio = res["g_fall"] / res["g_rise"]
        res["fall_gravity_multiplier"] = round(ratio, 4)
        res["asymmetric"] = bool(abs(ratio - 1.0) > 0.1)
    return res


def _fit_onset_model(tt, ss, V, kind: str, dt: float, t_hint: float):
    """Grid-fit (start time, ramp parameter) for a standing-start displacement curve."""
    np = rc.require_numpy()

    def model(ts, P):
        x = np.clip(tt[None, None, :] - ts[:, None, None], 0.0, None)
        if kind == "linear":
            T = P[None, :, None]
            return np.where(x < T, V * x * x / (2 * T), V * (x - T / 2))
        tau = P[None, :, None]
        return V * (x - tau * (1 - np.exp(-x / tau)))

    def search(ts_grid, p_grid):
        err = np.sqrt(((model(ts_grid, p_grid) - ss[None, None, :]) ** 2).mean(axis=2))
        i, j = np.unravel_index(int(np.argmin(err)), err.shape)
        return float(ts_grid[i]), float(p_grid[j]), float(err[i, j])

    ts_grid = np.arange(t_hint - 1.0, t_hint + dt, dt / 2)
    p_grid = np.arange(dt / 2, 2.0, dt / 2)
    t_s, P, _ = search(ts_grid, p_grid)
    ts_fine = np.arange(t_s - dt, t_s + dt, dt / 16)
    p_fine = np.arange(max(dt / 16, P - dt), P + dt, dt / 16)
    return search(ts_fine, p_fine)


def analyze_speed(t, u, unit: str, px_unit: float, fps: float) -> dict:
    np = rc.require_numpy()
    t = np.asarray(t, float)
    u = np.asarray(u, float)
    direction = 1.0 if u[-1] >= u[0] else -1.0
    s = (u - u[0]) * direction
    n0 = max(3, len(s) // 10)
    noise = float(np.median(np.abs(s[:n0] - np.median(s[:n0]))) * 1.4826)
    eps = max(3 * noise, 1.5 * px_unit)
    moving = np.nonzero(s > eps)[0]
    if len(moving) == 0:
        rc.fail("no motion detected", rc.EXIT_FAIL)
    k = int(moving[0])
    notes = []
    if k <= 1:
        notes.append("motion starts at the first samples: the start time is extrapolated, so treat t90 with care")
    if len(t) - k < 8:
        rc.fail("too few samples after motion starts; extract more frames", rc.EXIT_FAIL)
    tail = max(4, int((len(t) - k) * 0.4))
    if tail >= 4:
        (V, _), vcov = np.polyfit(t[-tail:], s[-tail:], 1, cov=True)
        v_std = float(np.sqrt(max(vcov[0, 0], 0.0)))
    else:
        V, _ = np.polyfit(t[-tail:], s[-tail:], 1)
        v_std = 0.0
    V = float(V)
    if V <= 0:
        rc.fail("could not fit a positive steady speed", rc.EXIT_FAIL)
    dt = 1.0 / (fps or 60.0)
    lin_ts, lin_T, lin_rms = _fit_onset_model(t, s, V, "linear", dt, float(t[k]))
    exp_ts, exp_tau, exp_rms = _fit_onset_model(t, s, V, "exponential", dt, float(t[k]))
    preferred = "linear_ramp" if lin_rms <= exp_rms else "exponential"
    t_start = lin_ts if preferred == "linear_ramp" else exp_ts
    t90_model = 0.9 * lin_T if preferred == "linear_ramp" else exp_tau * math.log(10)
    vel = np.gradient(s, t)
    if len(vel) >= 3:
        vel = np.convolve(vel, np.ones(3) / 3, mode="same")
    reach = np.nonzero((vel >= 0.9 * V) & (t > t_start))[0]
    t90_samples = float(t[reach[0]] - t_start) if len(reach) else None
    return {
        "unit": unit,
        "first_moving_sample": k,
        "motion_start_s": round(t_start, 4),
        "steady_speed": round(V, 4),
        "steady_speed_std": round(v_std, 5),
        "t90_s": round(t90_model, 4),
        "t90_from_samples_s": round(t90_samples, 4) if t90_samples is not None else None,
        "linear_ramp": {"start_s": round(lin_ts, 4), "time_to_full_s": round(lin_T, 4),
                        "acceleration": round(V / lin_T, 4), "rms": round(lin_rms, 5)},
        "exponential": {"start_s": round(exp_ts, 4), "tau_s": round(exp_tau, 4), "rms": round(exp_rms, 5)},
        "preferred_model": preferred,
        "time_precision_s": round(dt, 5),
        "notes": notes,
    }


# ----------------------------------------------------------------- cli

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path, help="extract_frames manifest.json (or its directory)")
    ap.add_argument("--bbox", required=True, help="x,y,w,h of the tracked feature on the first frame")
    ap.add_argument("--anchor-bbox", help="x,y,w,h of a static background feature, to cancel camera motion")
    ap.add_argument("--search", type=int, default=64, help="search radius in pixels around the predicted position (default 64)")
    ap.add_argument("--downscale", type=int, default=1, help="integer downscale for speed (default 1)")
    ap.add_argument("--px-per-unit", type=float, help="pixels per world unit at the subject's depth")
    ap.add_argument("--unit", default="studs", help="name of the world unit (default studs)")
    ap.add_argument("--analyze", choices=["jump", "speed", "none"], default="none")
    ap.add_argument("--air-range", help="first,last sample indexes of the airborne segment (jump analysis override)")
    ap.add_argument("--min-score", type=float, default=0.6, help="warn when match scores fall below this (default 0.6)")
    ap.add_argument("--out", type=Path, help="write JSON results here")
    ap.add_argument("--csv", type=Path, help="also write per-frame samples as CSV")
    args = ap.parse_args()

    np = rc.require_numpy()
    manifest, frames_meta, base = rc.load_manifest(args.manifest)
    bbox = rc.parse_bbox(args.bbox, "--bbox")
    if manifest.get("crop"):
        cx0, cy0 = manifest["crop"][0], manifest["crop"][1]
        print(f"note: frames were cropped at {cx0},{cy0}; --bbox is relative to the cropped frames", file=sys.stderr)
    images = [rc.load_gray(base / fr["file"], args.downscale) for fr in frames_meta]
    times = [float(fr.get("pts_time", i / 60.0)) for i, fr in enumerate(frames_meta)]
    if len(images) < 3:
        rc.fail("need at least 3 frames")
    pts = track(images, bbox, args.search, args.downscale)
    anchor = None
    if args.anchor_bbox:
        anchor = track(images, rc.parse_bbox(args.anchor_bbox, "--anchor-bbox"), args.search, args.downscale)

    ppu = args.px_per_unit
    unit = args.unit if ppu else "px"
    scale = 1.0 / ppu if ppu else 1.0
    x0, y0 = pts[0][0], pts[0][1]
    samples = []
    low = 0
    for i, (fr, (x, y, sc)) in enumerate(zip(frames_meta, pts)):
        dx = dy = 0.0
        if anchor:
            dx, dy = anchor[i][0] - anchor[0][0], anchor[i][1] - anchor[0][1]
        xc, yc = x - dx, y - dy
        u = (xc - x0) * scale
        v = (y0 - yc) * scale
        low += sc < args.min_score
        samples.append({"sample": i, "index": fr.get("index"), "t": round(times[i], 6),
                        "x_px": round(x, 3), "y_px": round(y, 3), "score": round(sc, 4),
                        "u": round(u, 5), "v": round(v, 5),
                        "anchor_score": round(anchor[i][2], 4) if anchor else None})

    if len(times) > 1 and times[-1] > times[0]:
        fps = (len(times) - 1) / (times[-1] - times[0])
    else:
        fps = 60.0
    result = {
        "tool": TOOL, "schema": SCHEMA, "manifest": str(args.manifest), "bbox": list(bbox),
        "anchor_bbox": args.anchor_bbox, "px_per_unit": ppu, "unit": unit,
        "fps_from_samples": round(fps, 4), "low_score_samples": int(low), "samples": samples,
    }
    tt = [s["t"] for s in samples]
    if args.analyze == "jump":
        air = None
        if args.air_range:
            a, b = (int(v) for v in args.air_range.split(","))
            air = (a, b)
        result["jump"] = analyze_jump(tt, [s["v"] for s in samples], unit, scale, fps, air)
    elif args.analyze == "speed":
        result["speed"] = analyze_speed(tt, [s["u"] for s in samples], unit, scale, fps)

    if args.out:
        rc.write_json(args.out, result)
    if args.csv:
        rc.ensure_parent(args.csv)
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(samples[0].keys()))
            w.writeheader()
            w.writerows(samples)

    print(f"tracked {len(samples)} frames; {low} below score {args.min_score}; unit {unit}")
    if low:
        print("WARNING: low match scores - the feature changed appearance or left the search window; "
              "check the track or use a smaller, more rigid feature", file=sys.stderr)
    for key in ("jump", "speed"):
        if key in result:
            for k, val in result[key].items():
                print(f"  {k}: {val}")
    if args.out:
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    rc.run_main(main)
