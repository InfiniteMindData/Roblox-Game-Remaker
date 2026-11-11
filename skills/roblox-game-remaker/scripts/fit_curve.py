#!/usr/bin/env python3
"""Identify a tween, ease or ramp from tracked samples: fit every easing curve, a spring and an
exponential approach, and rank them.

Candidates (formulas identical to the template's Easing.luau and Spring.luau):
  Linear, and Sine, Quad, Cubic, Quart, Quint, Exponential, Circular, Back, Elastic, Bounce,
  each In, Out and InOut          value = from + (to - from) * curve((t - start) / duration)
  Spring                          a critically or under-damped spring released at "start"
                                  (angular frequency, damping ratio), as Spring.luau steps it
  ExpApproach                     value = to + (from - to) * exp(-(t - start) / tau)

Each fit is a grid search over start and duration (or the spring's parameters) with the end
values solved by least squares, then refined. The table ranks fits by rms residual. A fit counts
as distinguishable from the best only when its residual sum of squares is worse by more than 9
noise variances (a 3-sigma likelihood ratio; noise = the best fit's rms corrected for degrees of
freedom, or --noise if larger). The tool says plainly when the top fits are not distinguishable,
and estimates the frame rate at which they would be.

Duration and start uncertainties come from refitting the best curve to residual-resampled data
(40 draws), and are never smaller than half a frame.

Input (one of):
  --track TRACK.json --field u      motion_track, pose_track or camera_solve ground output; any
                                    per-sample numeric field (u, v, x_px, y_px, scale, knee, ...)
  --csv FILE.csv --columns t,y      two columns of a CSV with a header row
  --points "t,y;t,y;..."            inline samples

Examples:
  python fit_curve.py --track remake/tracks/menu-open.json --field x_px --plot remake/ui/menu-open-fit.png --luau
  python fit_curve.py --track remake/tracks/cam-lag.json --field u --window 0.2,1.4 --json
  python fit_curve.py --points "0,0;0.05,0.1;0.1,0.36;0.15,0.64;0.2,0.84;0.25,0.96;0.3,1;0.35,1"
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "fit_curve"
SCHEMA = 1
STYLES = ("Sine", "Quad", "Cubic", "Quart", "Quint", "Exponential", "Circular", "Back", "Elastic", "Bounce")
C1 = 1.70158
C2 = C1 * 1.525
C3 = C1 + 1


# ----------------------------------------------------------------- curves (Easing.luau)

def _bounce_out(t):
    np = rc.require_numpy()
    n1, d1 = 7.5625, 2.75
    return np.where(t < 1 / d1, n1 * t * t,
                    np.where(t < 2 / d1, n1 * (t - 1.5 / d1) ** 2 + 0.75,
                             np.where(t < 2.5 / d1, n1 * (t - 2.25 / d1) ** 2 + 0.9375, n1 * (t - 2.625 / d1) ** 2 + 0.984375)))


def ease_in(style: str, t):
    np = rc.require_numpy()
    if style == "Linear":
        return t
    if style == "Sine":
        return 1 - np.cos(t * math.pi / 2)
    if style == "Quad":
        return t * t
    if style == "Cubic":
        return t ** 3
    if style == "Quart":
        return t ** 4
    if style == "Quint":
        return t ** 5
    if style == "Exponential":
        return np.where(t == 0, 0.0, 2.0 ** (10 * t - 10))
    if style == "Circular":
        return 1 - np.sqrt(np.clip(1 - t * t, 0, None))
    if style == "Back":
        return C3 * t ** 3 - C1 * t * t
    if style == "Elastic":
        v = -(2.0 ** (10 * t - 10)) * np.sin((t * 10 - 10.75) * (2 * math.pi) / 3)
        return np.where((t == 0) | (t == 1), t, v)
    if style == "Bounce":
        return 1 - _bounce_out(1 - t)
    raise ValueError(style)


def ease(style: str, direction: str, t):
    np = rc.require_numpy()
    t = np.clip(t, 0.0, 1.0)
    if style == "Back" and direction == "InOut":
        a = ((2 * t) ** 2 * ((C2 + 1) * 2 * t - C2)) / 2
        b = ((2 * t - 2) ** 2 * ((C2 + 1) * (t * 2 - 2) + C2) + 2) / 2
        return np.where(t < 0.5, a, b)
    if direction == "In":
        return ease_in(style, t)
    if direction == "Out":
        return 1 - ease_in(style, 1 - t)
    return np.where(t < 0.5, ease_in(style, 2 * t) / 2, 1 - ease_in(style, 2 - 2 * t) / 2)


def spring_progress(x, omega, zeta):
    """Progress 0 -> 1 of Spring.luau released from rest at x = 0 (x <= 0 is 0)."""
    np = rc.require_numpy()
    x = np.clip(x, 0.0, None)
    if abs(zeta - 1) < 1e-4:
        return 1 - np.exp(-omega * x) * (1 + omega * x)
    wd = omega * math.sqrt(1 - zeta * zeta)
    return 1 - np.exp(-zeta * omega * x) * (np.cos(wd * x) + zeta * omega / wd * np.sin(wd * x))


def curve_names() -> list[tuple[str, str]]:
    return [("Linear", "In")] + [(s, d) for s in STYLES for d in ("In", "Out", "InOut")]


# ----------------------------------------------------------------- fitting

def _lsq(basis, y):
    """Best a + b * basis[k] for every row k of basis; returns (a, b, rms)."""
    np = rc.require_numpy()
    fm = basis.mean(axis=1, keepdims=True)
    ym = y.mean()
    fc = basis - fm
    var = (fc * fc).sum(axis=1)
    cov = (fc * (y - ym)).sum(axis=1)
    ok = var > 1e-12
    b = np.where(ok, cov / np.where(ok, var, 1.0), 0.0)
    a = ym - b * fm[:, 0]
    res = y[None, :] - (a[:, None] + b[:, None] * basis)
    rms = np.sqrt((res * res).mean(axis=1))
    return a, b, np.where(ok, rms, np.inf)


def fit_ease(t, y, style, direction, ts_grid, d_grid):
    np = rc.require_numpy()
    TS, D = np.meshgrid(ts_grid, d_grid, indexing="ij")
    TS, D = TS.ravel(), D.ravel()
    basis = ease(style, direction, (t[None, :] - TS[:, None]) / D[:, None])
    a, b, rms = _lsq(basis, y)
    i = int(np.argmin(rms))
    return {"start_s": float(TS[i]), "duration_s": float(D[i]), "from": float(a[i]), "to": float(a[i] + b[i]), "rms": float(rms[i])}


def fit_spring(t, y, ts_grid, w_grid, z_grid):
    np = rc.require_numpy()
    best = None
    for z in z_grid:
        TS, W = np.meshgrid(ts_grid, w_grid, indexing="ij")
        TS, W = TS.ravel(), W.ravel()
        x = np.clip(t[None, :] - TS[:, None], 0.0, None)
        if abs(z - 1) < 1e-4:
            basis = 1 - np.exp(-W[:, None] * x) * (1 + W[:, None] * x)
        else:
            wd = W[:, None] * math.sqrt(1 - z * z)
            basis = 1 - np.exp(-z * W[:, None] * x) * (np.cos(wd * x) + z * W[:, None] / wd * np.sin(wd * x))
        a, b, rms = _lsq(basis, y)
        i = int(np.argmin(rms))
        if best is None or rms[i] < best["rms"]:
            best = {"start_s": float(TS[i]), "omega": float(W[i]), "zeta": float(z), "from": float(a[i]),
                    "to": float(a[i] + b[i]), "rms": float(rms[i])}
    return best


def fit_exp(t, y, ts_grid, tau_grid):
    np = rc.require_numpy()
    TS, TAU = np.meshgrid(ts_grid, tau_grid, indexing="ij")
    TS, TAU = TS.ravel(), TAU.ravel()
    basis = 1 - np.exp(-np.clip(t[None, :] - TS[:, None], 0.0, None) / TAU[:, None])
    a, b, rms = _lsq(basis, y)
    i = int(np.argmin(rms))
    return {"start_s": float(TS[i]), "tau_s": float(TAU[i]), "from": float(a[i]), "to": float(a[i] + b[i]), "rms": float(rms[i])}


def model_values(fit: dict, t):
    np = rc.require_numpy()
    t = np.asarray(t, float)
    a, b = fit["from"], fit["to"] - fit["from"]
    if fit["family"] == "spring":
        return a + b * spring_progress(t - fit["start_s"], fit["omega"], fit["zeta"])
    if fit["family"] == "exponential":
        return a + b * (1 - np.exp(-np.clip(t - fit["start_s"], 0, None) / fit["tau_s"]))
    return a + b * ease(fit["style"], fit["direction"], (t - fit["start_s"]) / fit["duration_s"])


def transition_window(t, y):
    """Rough start and end of the change (2% / 98% of the net progress)."""
    np = rc.require_numpy()
    n = max(2, len(y) // 10)
    y0, y1 = float(np.median(y[:n])), float(np.median(y[-n:]))
    amp = y1 - y0
    if abs(amp) < 1e-12:
        return None
    p = (y - y0) / amp
    moving = np.nonzero(np.abs(p) > 0.02)[0]
    settled = np.nonzero(np.abs(p - 1) > 0.02)[0]
    if len(moving) == 0 or len(settled) == 0:
        return None
    return float(t[moving[0]]), float(t[settled[-1]])


def pattern_search(fit_fn, params: dict, steps: dict, tol: dict, lower: dict, iters: int = 80):
    """Minimize a grid fitter by moving a 5-point-per-axis stencil: recenter on the best point,
    halve the steps when the center wins. Handles long diagonal valleys that one local grid misses."""
    np = rc.require_numpy()
    cur = dict(params)
    best = None
    for _ in range(iters):
        grids = {k: np.linspace(cur[k] - 2 * steps[k], cur[k] + 2 * steps[k], 5) for k in steps}
        for k, lo in lower.items():
            grids[k] = np.clip(grids[k], lo[0], lo[1])
        f = fit_fn(grids)
        if best is None or f["rms"] < best["rms"] - 1e-15:
            best = f
        moved = any(abs(f[k] - cur[k]) > 1e-12 for k in steps)
        cur = {k: f[k] for k in steps}
        if not moved:
            steps = {k: v / 2 for k, v in steps.items()}
            if all(steps[k] < tol[k] for k in steps):
                break
    return best


def fit_all(t, y, dt):
    np = rc.require_numpy()
    win = transition_window(t, y)
    if win is None:
        rc.fail("the samples show no transition (start and end values are the same); check --field or --window", rc.EXIT_FAIL)
    a, b = win
    span = max(b - a, dt)
    ts0 = np.linspace(a - 1.0 * span - dt, a + 0.5 * dt, 28)
    d0 = np.linspace(max(dt / 2, 0.25 * span), 3.0 * span + 2 * dt, 36)
    s1, d1 = ts0[1] - ts0[0], d0[1] - d0[0]
    tol = {"start_s": dt / 400, "duration_s": dt / 400, "tau_s": dt / 400, "omega": 1e-4, "zeta": 1e-4}
    fits = []
    for style, direction in curve_names():
        f = fit_ease(t, y, style, direction, ts0, d0)
        f = pattern_search(lambda g, st=style, di=direction: fit_ease(t, y, st, di, g["start_s"], g["duration_s"]),
                           f, {"start_s": s1 / 2, "duration_s": d1 / 2}, tol, {"duration_s": (dt / 4, 1e9)})
        name = "Linear" if style == "Linear" else f"{style} {direction}"
        f.update({"name": name, "family": "easing", "style": style, "direction": direction, "params": 4})
        fits.append(f)
    w0 = np.geomspace(1.0, 400.0, 48)
    z0 = np.round(np.arange(0.05, 1.0001, 0.05), 4)
    ts_s = np.linspace(a - 0.5 * span - dt, a + 0.5 * dt, 20)
    sp = fit_spring(t, y, ts_s, w0, z0)
    sp = pattern_search(lambda g: fit_spring(t, y, g["start_s"], g["omega"], g["zeta"]), sp,
                        {"start_s": (ts_s[1] - ts_s[0]) / 2, "omega": 0.07 * sp["omega"], "zeta": 0.025}, tol,
                        {"omega": (0.05, 1e4), "zeta": (0.01, 1.0)})
    sp.update({"name": "Spring", "family": "spring", "params": 5})
    sp["critically_damped"] = sp["zeta"] >= 0.995
    fits.append(sp)
    ex = fit_exp(t, y, ts_s, np.geomspace(dt / 4, 3 * span + dt, 48))
    ex = pattern_search(lambda g: fit_exp(t, y, g["start_s"], g["tau_s"]), ex,
                        {"start_s": (ts_s[1] - ts_s[0]) / 2, "tau_s": 0.1 * ex["tau_s"]}, tol, {"tau_s": (dt / 20, 1e9)})
    ex.update({"name": "ExpApproach", "family": "exponential", "params": 4})
    fits.append(ex)
    fits.sort(key=lambda f: f["rms"])
    return fits, win


def refit(fit, t, y, dt):
    """Refit one candidate on new data near its current parameters (for the bootstrap)."""
    np = rc.require_numpy()
    s = max(dt, 0.05 * fit.get("duration_s", fit.get("tau_s", 0.1)))
    ts = np.linspace(fit["start_s"] - 2 * s, fit["start_s"] + 2 * s, 17)
    if fit["family"] == "easing":
        d = fit["duration_s"]
        return fit_ease(t, y, fit["style"], fit["direction"], ts, np.linspace(max(dt / 4, d - 3 * s), d + 3 * s, 25))
    if fit["family"] == "exponential":
        return fit_exp(t, y, ts, np.geomspace(fit["tau_s"] / 1.3, fit["tau_s"] * 1.3, 25))
    return fit_spring(t, y, ts, np.geomspace(fit["omega"] / 1.2, fit["omega"] * 1.2, 15),
                      np.clip(np.linspace(fit["zeta"] - 0.1, fit["zeta"] + 0.1, 9), 0.01, 1.0))


def bootstrap(fit, t, y, dt, draws=40):
    np = rc.require_numpy()
    rng = np.random.default_rng(0)
    model = model_values(fit, t)
    res = y - model
    keys = [k for k in ("start_s", "duration_s", "tau_s", "omega", "zeta") if k in fit]
    vals = {k: [] for k in keys}
    for _ in range(draws):
        yb = model + rng.choice(res, size=len(res), replace=True)
        f = refit(fit, t, yb, dt)
        for k in keys:
            vals[k].append(f[k])
    return {k: float(np.std(v)) for k, v in vals.items()}


# ----------------------------------------------------------------- input

def load_samples(args):
    np = rc.require_numpy()
    if sum(bool(x) for x in (args.track, args.csv, args.points)) != 1:
        rc.fail("give exactly one of --track, --csv or --points")
    source = ""
    if args.track:
        data = rc.read_json(args.track)
        samples = data.get("samples") if isinstance(data, dict) else None
        if samples is None and isinstance(data, dict) and isinstance(data.get("track"), dict):
            samples = data["track"].get("samples")
        if not samples:
            rc.fail(f"{args.track} has no samples")
        if not args.field:
            rc.fail("--track needs --field (for example u, v, x_px, y_px, scale)")
        try:
            pts = [(float(s["t"]), float(s[args.field])) for s in samples if s.get(args.field) is not None]
        except (KeyError, TypeError, ValueError):
            rc.fail(f"{args.track}: samples need numeric 't' and '{args.field}'")
        source = f"{Path(args.track).name} field {args.field}"
    elif args.csv:
        cols = [c.strip() for c in (args.columns or "t,y").split(",")]
        if len(cols) != 2:
            rc.fail("--columns is TIME,VALUE")
        try:
            with open(args.csv, newline="", encoding="utf-8") as fh:
                pts = [(float(r[cols[0]]), float(r[cols[1]])) for r in csv.DictReader(fh) if r.get(cols[1]) not in (None, "")]
        except FileNotFoundError:
            rc.fail(f"file not found: {args.csv}")
        except (KeyError, ValueError):
            rc.fail(f"{args.csv}: needs numeric columns {cols[0]} and {cols[1]}")
        source = f"{Path(args.csv).name} columns {cols[0]},{cols[1]}"
    else:
        pts = [tuple(p) for p in (rc.parse_float_list(c, "--points") for c in args.points.split(";") if c.strip())]
        if any(len(p) != 2 for p in pts):
            rc.fail("--points entries are t,value")
        source = "inline points"
    pts.sort()
    if args.window:
        lo, hi = rc.parse_float_list(args.window, "--window")[:2]
        pts = [p for p in pts if lo <= p[0] <= hi]
    if len(pts) < 6:
        rc.fail(f"need at least 6 samples to fit a curve (got {len(pts)})")
    t = np.array([p[0] for p in pts])
    if np.any(np.diff(t) <= 0):
        rc.fail("sample times must be distinct")
    return t, np.array([p[1] for p in pts]), source


# ----------------------------------------------------------------- report

def compare_top(fits, t, sigma, dt):
    """Fits whose residual sum of squares is within 9 noise variances of the best (a 3-sigma likelihood
    ratio). For each, the lowest frame rate (2x to 16x the footage's) at which the rival curve,
    refitted to noise-free samples of the best fit, would be 9 variances worse: None if not even 16x."""
    np = rc.require_numpy()
    best = fits[0]
    n = len(t)
    rss1 = best["rms"] ** 2 * n
    ties = []
    for f in fits[1:]:
        delta = (f["rms"] ** 2 * n - rss1) / (sigma * sigma)
        if delta > 9:
            continue
        need = None
        for mult in (2, 4, 8, 16):
            fps = mult / dt
            tt = np.arange(t[0], t[-1] + 1e-9, 1.0 / fps)
            g = refit(f, tt, model_values(best, tt), 1.0 / fps)
            if g["rms"] ** 2 * len(tt) / (sigma * sigma) > 9:
                need = fps
                break
        ties.append({"name": f["name"], "delta_chi2": round(float(delta), 3),
                     "fps_to_separate": round(need, 1) if need else None, "higher_fps_would_separate": need is not None})
    return ties


def describe(f: dict) -> str:
    if f["family"] == "spring":
        return f"omega {f['omega']:.3f} rad/s, zeta {f['zeta']:.3f}, released at {f['start_s']:.4f} s"
    if f["family"] == "exponential":
        return f"tau {f['tau_s']:.4f} s, from {f['start_s']:.4f} s"
    return f"duration {f['duration_s']:.4f} s, from {f['start_s']:.4f} s"


def luau(best: dict, unc: dict) -> list[str]:
    if best["family"] == "easing":
        style = best["style"]
        direction = best["direction"] if style != "Linear" else "In"
        return [f"-- fit_curve: {best['name']}, {describe(best)} (± {unc.get('duration_s', 0):.4f} s); "
                "the template's Easing formulas; confirm against TweenService:GetValue in Studio",
                f"local tweenInfo = TweenInfo.new({best['duration_s']:.4f}, Enum.EasingStyle.{style}, Enum.EasingDirection.{direction})",
                f'local curve = Easing.get("{style}", "{direction}")']
    if best["family"] == "spring":
        return [f"-- fit_curve: spring, {describe(best)}",
                f"local spring = Spring.new(initial, {best['omega']:.4f}, {best['zeta']:.4f}) -- angularFrequency, dampingRatio",
                f"FollowFrequency = {best['omega']:.4f}, -- Config.Camera (rad/s)",
                f"FollowDamping = {best['zeta']:.4f},"]
    return [f"-- fit_curve: exponential approach, tau {best['tau_s']:.4f} s (frame-rate independent smoothing)",
            f"local alpha = 1 - math.exp(-dt / {best['tau_s']:.4f})",
            "value += (target - value) * alpha"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--track", type=Path, help="tool output with per-sample t and --field")
    ap.add_argument("--field", help="sample field to fit (u, v, x_px, y_px, scale, a joint name, ...)")
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--columns", help="TIME,VALUE column names in --csv (default t,y)")
    ap.add_argument("--points", help="inline t,value;t,value samples")
    ap.add_argument("--window", help="a,b: only fit samples in this time range (s)")
    ap.add_argument("--fps", type=float, help="footage frame rate (default: from the sample spacing)")
    ap.add_argument("--noise", type=float, default=0.0, help="measurement noise in the value's unit (default: the best fit's rms)")
    ap.add_argument("--top", type=int, default=8, help="rows to print (default 8)")
    ap.add_argument("--unit", default="", help="unit of the fitted value, for the report")
    ap.add_argument("--plot", type=Path, help="PNG of the samples and the top three fits")
    ap.add_argument("--luau", action="store_true", help="print Luau for the best fit")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    np = rc.require_numpy()
    t, y, source = load_samples(args)
    dt = 1.0 / args.fps if args.fps else float(np.median(np.diff(t)))
    fits, win = fit_all(t, y, dt)
    best = fits[0]
    # Residual rms underestimates the noise when few samples carry many parameters: correct for the
    # degrees of freedom (n / (n - k)).
    dof = max(1, len(t) - best["params"])
    sigma = max(best["rms"] * math.sqrt(len(t) / dof), args.noise, 1e-9 * max(1.0, float(np.abs(y).max())))
    ties = compare_top(fits, t, sigma, dt)
    boot = bootstrap(best, t, y, dt)
    # Never claim more than the frame period (times) or the final grid step (spring) can resolve.
    floors = {"start_s": dt / 2, "duration_s": dt / 2, "tau_s": dt / 2, "omega": 0.004 * best.get("omega", 0.0), "zeta": 0.002}
    unc = {k: max(2 * v, floors[k]) for k, v in boot.items()}
    inside = int(((t >= best["start_s"]) & (t <= best["start_s"] + best.get("duration_s", 3 * best.get("tau_s", 0) or 0.0))).sum())
    if best["family"] == "spring":
        inside = int(((t >= best["start_s"]) & (t <= best["start_s"] + 4.0 / (best["zeta"] * best["omega"]))).sum())
    warnings = []
    if ties:
        names = ", ".join(x["name"] for x in ties[:5]) + (" ..." if len(ties) > 5 else "")
        sep = [x["name"] for x in ties if x["higher_fps_would_separate"]]
        fps_need = [x["fps_to_separate"] for x in ties if x["higher_fps_would_separate"]]
        warnings.append(f"NOT DISTINGUISHABLE at {1 / dt:.1f} fps: {best['name']} and {names} fit equally well given the noise "
                        f"({sigma:.4g}{' ' + args.unit if args.unit else ''}). "
                        + (f"Footage at about {max(fps_need):.0f} fps (or less noise) would separate them."
                           if sep and len(sep) == len(ties) else
                           f"Footage at about {max(fps_need):.0f} fps would separate {', '.join(sep[:3])}; the others stay within "
                           "the noise even at 16x the frame rate, so pick by intent and record the alternatives." if sep else
                           "They stay within the noise even at 16x the frame rate, so more frames will not help; reduce the noise "
                           "(a larger, sharper feature) or pick by intent and record the alternatives."))
    if inside < 6:
        warnings.append(f"only {inside} samples fall inside the fitted transition; the curve shape is weakly constrained")
    if best["rms"] > 0.05 * abs(best["to"] - best["from"]):
        warnings.append(f"the best fit leaves {100 * best['rms'] / abs(best['to'] - best['from']):.1f}% rms residual: "
                        "the motion may be a sequence of tweens, keyframed, or physics-driven; fit a narrower --window")
    tie_note = f"; equally good: {', '.join(x['name'] for x in ties)}" if ties else ""
    method = (f"fit_curve {source}: grid-search fit of {len(fits)} candidates (template Easing curves, Spring, exponential "
              f"approach), {len(t)} samples at {1 / dt:.2f} fps; best {best['name']} rms {best['rms']:.4g}{tie_note}; "
              "uncertainty = 2x bootstrap std (40 residual draws), at least half a frame")
    ms = []
    label = best["name"] + (" or " + ties[0]["name"] if ties else "")
    if best["family"] == "easing":
        ms.append({"metric": "curve_duration", "what": f"tween duration ({label})", "value": round(best["duration_s"], 4),
                   "uncertainty": round(unc["duration_s"], 4), "unit": "s", "method": method})
    elif best["family"] == "spring":
        ms.append({"metric": "curve_spring_omega", "what": f"spring angular frequency ({label})", "value": round(best["omega"], 4),
                   "uncertainty": round(unc["omega"], 4), "unit": "rad/s", "method": method})
        ms.append({"metric": "curve_spring_zeta", "what": f"spring damping ratio ({label})", "value": round(best["zeta"], 4),
                   "uncertainty": round(unc["zeta"], 4), "unit": "ratio", "method": method})
    else:
        ms.append({"metric": "curve_tau", "what": f"exponential approach time constant ({label})", "value": round(best["tau_s"], 4),
                   "uncertainty": round(unc["tau_s"], 4), "unit": "s", "method": method})

    def clean(f):
        out = {k: (round(v, 5) if isinstance(v, float) else v) for k, v in f.items()}
        return out

    report = {"tool": TOOL, "schema": SCHEMA, "source": source, "samples": len(t), "fps": round(1 / dt, 3),
              "transition_estimate_s": [round(win[0], 4), round(win[1], 4)], "noise": round(sigma, 6),
              "best": clean(best), "uncertainty": {k: round(v, 5) for k, v in unc.items()},
              "indistinguishable_from_best": ties, "fits": [clean(f) for f in fits], "measurements": ms,
              "warnings": warnings, "method": method}
    if args.plot:
        dense = np.linspace(t[0], t[-1], 400)
        series = [{"label": "samples", "x": t.tolist(), "y": y.tolist(), "dots": True, "color": (0, 0, 0)}]
        series += [{"label": f["name"], "x": dense.tolist(), "y": model_values(f, dense).tolist()} for f in fits[:3]]
        rc.line_plot(args.plot, [{"title": f"fit_curve: {source}", "xlabel": "time (s)", "ylabel": args.unit, "series": series}],
                     title=f"best {best['name']} ({describe(best)}), rms {best['rms']:.4g}")
        report["plot"] = str(args.plot)
    if args.out:
        rc.write_json(args.out, report)
    if args.json:
        print(rc.dump_json(report))
        return 0
    print(f"{len(t)} samples from {source} at {1 / dt:.2f} fps; noise {sigma:.4g}")
    print(f"{'rank':<5}{'fit':<18}{'rms':>11}  parameters")
    for i, f in enumerate(fits[:args.top], 1):
        print(f"{i:<5}{f['name']:<18}{f['rms']:>11.5g}  {describe(f)}; {f['from']:.4g} -> {f['to']:.4g}")
    u = ", ".join(f"{k} ± {v:.4g}" for k, v in unc.items())
    print(f"best: {best['name']} ({describe(best)}); {u}")
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if args.luau:
        print("\n-- Luau")
        print("\n".join(luau(best, unc)))
    for p in (args.out, args.plot):
        if p:
            print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    rc.run_main(main)
