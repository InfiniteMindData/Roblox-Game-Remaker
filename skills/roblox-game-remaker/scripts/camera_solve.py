#!/usr/bin/env python3
"""Estimate camera field of view, pitch and height from marked footage, and convert ground-plane
pixels to world units.

Pinhole model with square pixels and the principal point at the image center (override with
--principal). Pixel coordinates are in the full source frame: x right, y down. Pitch is the
camera's look elevation (negative = looking down, as in Config.Camera.StartPitchDeg). Roblox
Camera.FieldOfView is vertical, so every mode reports vfov_deg first.

Subcommands:
  vanishing  two or three sets of world-parallel lines (two orthogonal ground directions, and
             optionally vertical edges) -> focal length, vertical and horizontal FOV, pitch,
             roll; plus camera height with --known-height (a vertical object of known height
             standing on the ground) or --known-ground (two ground points a known distance apart)
  size       an object of known size at a known depth spanning a marked pixel segment -> FOV
  ground     four marked corners of a known ground rectangle -> image-to-ground homography;
             converts --points or a motion_track --track (feet on the ground) to world units,
             optionally re-running the standing-start speed fit in world units

Line syntax: "x1,y1,x2,y2;x1,y1,x2,y2" (at least two lines per set). Corner syntax:
"x,y;x,y;x,y;x,y" in order around the rectangle: the world origin, then along the --rect width
axis, then the far corner, then along the depth axis.

Uncertainty: every marked coordinate is moved by -1 and +1 px in turn and the result recomputed;
the reported uncertainty combines those sensitivities in quadrature, and worst_case adds them.
When a 1 px move makes the solution impossible, the value is reported as unstable.

Examples:
  python camera_solve.py vanishing --image 1920x1080 --lines-x "100,900,800,700;120,1000,900,760" \\
      --lines-z "1500,950,1200,640;1800,900,1400,620" --known-height 960,880,960,620,5 --unit studs
  python camera_solve.py size --image 1920x1080 --span 960,400,960,700 --size 5 --distance 20
  python camera_solve.py ground --image 1280x720 --corners "300,600;980,600;820,380;460,380" --rect 20x10 \\
      --track remake/tracks/run3d.json --contact bottom --analyze speed --out remake/tracks/run3d-ground.json
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "camera_solve"
SCHEMA = 1


class Unsolvable(Exception):
    """The marked geometry admits no camera (raised inside solvers; turned into messages)."""


# ----------------------------------------------------------------- parsing

def parse_image(text: str) -> tuple[int, int]:
    for sep in ("x", "X", ",", ":"):
        if sep in text:
            try:
                w, h = (int(v) for v in text.split(sep))
            except ValueError:
                break
            if w > 0 and h > 0:
                return w, h
            break
    rc.fail(f"--image must look like 1920x1080 (got {text!r})")


def parse_points(text: str, name: str, per: int) -> list[list[float]]:
    out = []
    for chunk in [c for c in text.replace(" ", "").split(";") if c]:
        vals = rc.parse_float_list(chunk, name)
        if len(vals) != per:
            rc.fail(f"{name}: each entry needs {per} numbers separated by commas (got {chunk!r})")
        out.append(vals)
    if not out:
        rc.fail(f"{name} is empty")
    return out


# ----------------------------------------------------------------- geometry

def vanishing_point(lines):
    """Least-squares intersection of image lines, as a homogeneous 3-vector (scaled image px)."""
    np = rc.require_numpy()
    rows = []
    for x1, y1, x2, y2 in lines:
        if math.hypot(x2 - x1, y2 - y1) < 2:
            raise Unsolvable("a marked line is shorter than 2 px")
        l = np.cross([x1, y1, 1.0], [x2, y2, 1.0])
        rows.append(l / math.hypot(l[0], l[1]))
    _, _, vt = np.linalg.svd(np.array(rows))
    v = vt[-1]
    return v / np.linalg.norm(v)


def camera_dir(v, f, c):
    """Unit camera-space direction (x right, y down, z forward) of a homogeneous vanishing point."""
    np = rc.require_numpy()
    d = np.array([(v[0] - c[0] * v[2]) / f, (v[1] - c[1] * v[2]) / f, v[2]])
    return d / np.linalg.norm(d)


def focal_from_pair(v1, v2, c) -> float:
    w = v1[2] * v2[2]
    if abs(w) < 1e-12:
        raise Unsolvable("one vanishing point is at infinity (its lines are parallel in the image); "
                         "focal length needs both directions to converge")
    num = (v1[0] - c[0] * v1[2]) * (v2[0] - c[0] * v2[2]) + (v1[1] - c[1] * v1[2]) * (v2[1] - c[1] * v2[2])
    f2 = -num / w
    if f2 <= 0:
        raise Unsolvable("the two line sets do not look perpendicular in the world from this camera "
                         "(f^2 <= 0); check that each set is parallel and the sets are at right angles")
    return math.sqrt(f2)


def up_vector(dx, dz, dy):
    np = rc.require_numpy()
    if dy is not None:
        u = dy
    else:
        u = np.cross(dx, dz)
        n = np.linalg.norm(u)
        if n < 1e-9:
            raise Unsolvable("the two ground directions are parallel")
        u = u / n
    return -u if u[1] > 0 else u  # world up points toward the top of the image (negative y)


def ray(p, f, c):
    np = rc.require_numpy()
    return np.array([(p[0] - c[0]) / f, (p[1] - c[1]) / f, 1.0])


def ground_point(p, f, c, u, h=1.0):
    r = ray(p, f, c)
    du = float(r @ u)
    if du >= -1e-9:
        raise Unsolvable(f"point {p[0]:.0f},{p[1]:.0f} is on or above the horizon, so it is not on the ground")
    return r * (-h / du)


def height_from_vertical(base, top, f, c, u, size):
    np = rc.require_numpy()
    g = ground_point(base, f, c, u)
    rt = ray(top, f, c)
    a = np.stack([u, -rt], axis=1)
    (s, _), *_ = np.linalg.lstsq(a, -g, rcond=None)
    if s <= 1e-9:
        raise Unsolvable("the marked top is not above the marked base")
    h = size / s
    return h, float(np.linalg.norm(g) * h)


def height_from_ground(p1, p2, f, c, u, dist):
    np = rc.require_numpy()
    g1, g2 = ground_point(p1, f, c, u), ground_point(p2, f, c, u)
    d1 = float(np.linalg.norm(g1 - g2))
    if d1 < 1e-9:
        raise Unsolvable("the two ground points coincide")
    h = dist / d1
    return h, float(np.linalg.norm(g1) * h)


def fov_pair(f, w, h):
    return math.degrees(2 * math.atan(h / 2 / f)), math.degrees(2 * math.atan(w / 2 / f))


# ----------------------------------------------------------------- sensitivity

def sensitivity(solve, coords: list[float], keys: list[str]) -> tuple[dict, dict, list[str]]:
    """Move each coordinate by -1 and +1 px; return (rss, worst_case, unstable keys)."""
    base = solve(coords)
    acc = {k: 0.0 for k in keys}
    worst = {k: 0.0 for k in keys}
    unstable: set[str] = set()
    for i in range(len(coords)):
        res = []
        for d in (-1.0, 1.0):
            moved = list(coords)
            moved[i] += d
            try:
                res.append(solve(moved))
            except (Unsolvable, rc.ToolError, ValueError, ZeroDivisionError):
                res.append(None)
        for k in keys:
            vals = [r[k] for r in res if r is not None and r.get(k) is not None]
            if len(vals) < 2:
                unstable.add(k)
                continue
            half = (vals[1] - vals[0]) / 2
            dev = max(abs(v - base[k]) for v in vals)
            acc[k] += half * half
            worst[k] += dev
    return {k: math.sqrt(v) for k, v in acc.items()}, worst, sorted(unstable)


def measurement(metric, what, value, unc, unit, method):
    return {"metric": metric, "what": what, "value": round(value, 4),
            "uncertainty": None if unc is None else round(unc, 4), "unit": unit, "method": method}


# ----------------------------------------------------------------- vanishing mode

def cmd_vanishing(args) -> dict:
    w, h = parse_image(args.image)
    c = rc.parse_float_list(args.principal, "--principal") if args.principal else [w / 2, h / 2]
    if len(c) != 2:
        rc.fail("--principal must be cx,cy")
    sets = {"x": args.lines_x, "z": args.lines_z, "y": args.lines_y}
    given = {k: parse_points(v, f"--lines-{k}", 4) for k, v in sets.items() if v}
    for k, lines in given.items():
        if len(lines) < 2:
            rc.fail(f"--lines-{k} needs at least two lines")
    if len(given) < 2:
        rc.fail("give at least two line sets (--lines-x and --lines-z for two ground directions, or one of them with --lines-y)")
    if args.known_height and args.known_ground:
        rc.fail("use --known-height or --known-ground, not both")
    known = None
    if args.known_height:
        kv = rc.parse_float_list(args.known_height, "--known-height")
        if len(kv) != 5 or kv[4] <= 0:
            rc.fail("--known-height is base_x,base_y,top_x,top_y,height")
        known = ("height", kv[:4], kv[4])
    elif args.known_ground:
        kv = rc.parse_float_list(args.known_ground, "--known-ground")
        if len(kv) != 5 or kv[4] <= 0:
            rc.fail("--known-ground is x1,y1,x2,y2,distance")
        known = ("ground", kv[:4], kv[4])

    order = [k for k in ("x", "z", "y") if k in given]
    sizes = [len(given[k]) * 4 for k in order]
    flat = [v for k in order for line in given[k] for v in line] + (known[1] if known else [])

    def solve(coords):
        pos, vps = 0, {}
        for k, n in zip(order, sizes):
            chunk = coords[pos:pos + n]
            pos += n
            vps[k] = vanishing_point([chunk[i:i + 4] for i in range(0, n, 4)])
        pairs = [(a, b) for a, b in (("x", "z"), ("x", "y"), ("z", "y")) if a in vps and b in vps]
        focals = [focal_from_pair(vps[a], vps[b], c) for a, b in pairs]
        f = sum(focals) / len(focals)
        dirs = {k: camera_dir(v, f, c) for k, v in vps.items()}
        if "y" in dirs:
            u = up_vector(None, None, dirs["y"])
        else:
            u = up_vector(dirs["x"], dirs["z"], None)
        vf, hf = fov_pair(f, w, h)
        out = {"focal_px": f, "vfov_deg": vf, "hfov_deg": hf,
               "pitch_deg": math.degrees(math.asin(max(-1.0, min(1.0, float(u[2]))))),
               "roll_deg": math.degrees(math.atan2(float(u[0]), float(-u[1]))),
               "focal_spread_px": (max(focals) - min(focals)) if len(focals) > 1 else 0.0}
        if known:
            k = coords[pos:pos + 4]
            if known[0] == "height":
                out["height"], out["distance_to_base"] = height_from_vertical(k[0:2], k[2:4], f, c, u, known[2])
            else:
                out["height"], out["distance_to_base"] = height_from_ground(k[0:2], k[2:4], f, c, u, known[2])
        out["_vps"] = vps
        return out

    try:
        base = solve(flat)
    except Unsolvable as exc:
        rc.fail(f"cannot solve the camera: {exc}", rc.EXIT_FAIL)
    keys = ["focal_px", "vfov_deg", "hfov_deg", "pitch_deg", "roll_deg"] + (["height", "distance_to_base"] if known else [])
    unc, worst, unstable = sensitivity(solve, flat, keys)
    vps = base.pop("_vps")
    method = (f"camera_solve vanishing: line sets {', '.join(order)} ({', '.join(str(len(given[k])) for k in order)} lines), "
              f"principal point {c[0]:g},{c[1]:g}, image {w}x{h}; uncertainty = +/-1 px per marked coordinate in quadrature")
    warnings = []
    if base["focal_spread_px"] > 0.05 * base["focal_px"]:
        warnings.append(f"the three line sets disagree on focal length by {base['focal_spread_px']:.0f} px "
                        f"({100 * base['focal_spread_px'] / base['focal_px']:.0f}%): a set is not parallel, or the principal point is off-center")
    for k in unstable:
        warnings.append(f"{k} is unstable: a 1 px change in a marked point makes the camera unsolvable; mark longer, more spread-out lines")
    for k in ("vfov_deg", "pitch_deg"):
        if k not in unstable and unc[k] > 3.0:
            warnings.append(f"{k} is poorly constrained (+/-{unc[k]:.1f} deg for 1 px); mark longer lines that converge more strongly")
    res = {k: round(v, 4) for k, v in base.items()}
    res["uncertainty"] = {k: (None if k in unstable else round(unc[k], 4)) for k in keys}
    res["worst_case"] = {k: (None if k in unstable else round(worst[k], 4)) for k in keys}
    res["vanishing_points"] = {k: ([round(float(v[0] / v[2]), 2), round(float(v[1] / v[2]), 2)] if abs(v[2]) > 1e-12 else "infinity")
                               for k, v in vps.items()}
    unit = args.unit
    ms = [measurement("camera_vfov", "camera vertical FOV", base["vfov_deg"], res["uncertainty"]["vfov_deg"], "deg", method),
          measurement("camera_pitch", "camera pitch (negative = looking down)", base["pitch_deg"], res["uncertainty"]["pitch_deg"], "deg", method),
          measurement("camera_roll", "camera roll", base["roll_deg"], res["uncertainty"]["roll_deg"], "deg", method)]
    if known:
        how = "vertical object" if known[0] == "height" else "ground distance"
        ms.append(measurement("camera_height", f"camera height above the ground (from a known {how} of {known[2]:g} {unit})",
                              base["height"], res["uncertainty"]["height"], unit, method))
    return {"mode": "vanishing", "image": [w, h], "principal_point": c, "unit": unit, "result": res,
            "measurements": ms, "warnings": warnings}


# ----------------------------------------------------------------- size mode

def cmd_size(args) -> dict:
    w, h = parse_image(args.image)
    span = rc.parse_float_list(args.span, "--span")
    if len(span) != 4:
        rc.fail("--span is x1,y1,x2,y2 (the two ends of the object in the frame)")
    if args.size <= 0 or args.distance <= 0:
        rc.fail("--size and --distance must be positive")

    def solve(coords):
        p = math.hypot(coords[2] - coords[0], coords[3] - coords[1])
        if p < 1:
            raise Unsolvable("the marked span is shorter than 1 px")
        f = p * args.distance / args.size
        vf, hf = fov_pair(f, w, h)
        return {"span_px": p, "focal_px": f, "vfov_deg": vf, "hfov_deg": hf}

    try:
        base = solve(span)
    except Unsolvable as exc:
        rc.fail(str(exc), rc.EXIT_FAIL)
    keys = ["focal_px", "vfov_deg", "hfov_deg"]
    unc, worst, unstable = sensitivity(solve, span, keys)
    # Relative errors in size and distance scale the focal length directly.
    rel = math.hypot((args.size_uncertainty or 0) / args.size, (args.distance_uncertainty or 0) / args.distance)
    f = base["focal_px"]
    for k in keys:
        if k == "focal_px":
            extra = f * rel
        else:
            dim = h if k == "vfov_deg" else w
            dfov_df = -math.degrees(2 * (dim / 2) / (f * f + (dim / 2) ** 2))
            extra = abs(dfov_df) * f * rel
        unc[k] = math.hypot(unc[k], extra)
    res = {k: round(v, 4) for k, v in base.items()}
    res["uncertainty"] = {k: (None if k in unstable else round(unc[k], 4)) for k in keys}
    res["worst_case"] = {k: (None if k in unstable else round(worst[k], 4)) for k in keys}
    method = (f"camera_solve size: {args.size:g} {args.unit} object at depth {args.distance:g} {args.unit} spans {base['span_px']:.1f} px "
              f"in a {w}x{h} frame; uncertainty = +/-1 px per end point"
              + (f" plus size/distance uncertainty ({100 * rel:.1f}%)" if rel else ""))
    warnings = []
    if base["span_px"] < 40:
        warnings.append(f"the object spans only {base['span_px']:.0f} px: 1 px is {100 / base['span_px']:.1f}% of the focal length; use a larger or closer object")
    ms = [measurement("camera_vfov", "camera vertical FOV", base["vfov_deg"], res["uncertainty"]["vfov_deg"], "deg", method)]
    return {"mode": "size", "image": [w, h], "unit": args.unit, "result": res, "measurements": ms, "warnings": warnings}


# ----------------------------------------------------------------- ground mode

def homography(src, dst):
    """3x3 H with dst ~ H @ src (normalized DLT, exact for four points)."""
    np = rc.require_numpy()
    src, dst = np.asarray(src, float), np.asarray(dst, float)

    def norm(p):
        m = p.mean(axis=0)
        s = math.sqrt(2) / max(1e-12, float(np.sqrt(((p - m) ** 2).sum(axis=1)).mean()))
        return np.array([[s, 0, -s * m[0]], [0, s, -s * m[1]], [0, 0, 1]])

    ts, td = norm(src), norm(dst)
    ps = (ts @ np.c_[src, np.ones(len(src))].T).T
    pd = (td @ np.c_[dst, np.ones(len(dst))].T).T
    rows = []
    for (x, y, _), (u, v, _) in zip(ps, pd):
        rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, s, vt = np.linalg.svd(np.array(rows))
    if s[-2] < 1e-9:
        raise Unsolvable("the four corners are degenerate (three are collinear)")
    hm = np.linalg.inv(td) @ vt[-1].reshape(3, 3) @ ts
    hm = hm / np.linalg.norm(hm)
    # Points on the visible side of the plane's horizon map with the same sign of w as the
    # corners; make that sign positive so apply_h can reject points beyond the horizon.
    w = np.c_[src, np.ones(len(src))] @ hm[2]
    if np.all(w < 0):
        hm = -hm
    elif not np.all(w > 0):
        raise Unsolvable("the corners straddle the horizon")
    return hm


def apply_h(hm, pts):
    np = rc.require_numpy()
    p = np.c_[np.asarray(pts, float), np.ones(len(pts))] @ hm.T
    if np.any(p[:, 2] <= 1e-12):
        raise Unsolvable("a point lies on or beyond the ground plane's horizon")
    return p[:, :2] / p[:, 2:3]


def convex_ccw(quad) -> bool:
    signs = []
    for i in range(4):
        (x1, y1), (x2, y2), (x3, y3) = quad[i], quad[(i + 1) % 4], quad[(i + 2) % 4]
        signs.append((x2 - x1) * (y3 - y2) - (y2 - y1) * (x3 - x2))
    return all(s > 0 for s in signs) or all(s < 0 for s in signs)


def local_scale(hm, p):
    """World units per pixel at image point p: (largest, smallest) singular value of the Jacobian."""
    np = rc.require_numpy()
    e = 0.5
    a = apply_h(hm, [p, [p[0] + e, p[1]], [p[0], p[1] + e]])
    j = np.stack([(a[1] - a[0]) / e, (a[2] - a[0]) / e], axis=1)
    s = np.linalg.svd(j, compute_uv=False)
    return float(s[0]), float(s[1])


def camera_from_rect(corners, w, h, c, width):
    """Cross-check: camera from the rectangle's edge vanishing points (needs both to converge)."""
    p = corners
    vx = vanishing_point([p[0] + p[1], p[3] + p[2]])
    vz = vanishing_point([p[0] + p[3], p[1] + p[2]])
    f = focal_from_pair(vx, vz, c)
    u = up_vector(camera_dir(vx, f, c), camera_dir(vz, f, c), None)
    height, dist = height_from_ground(p[0], p[1], f, c, u, width)
    vf, hf = fov_pair(f, w, h)
    return {"focal_px": f, "vfov_deg": vf, "hfov_deg": hf, "pitch_deg": math.degrees(math.asin(float(u[2]))),
            "roll_deg": math.degrees(math.atan2(float(u[0]), float(-u[1]))), "height": height}


def cmd_ground(args) -> dict:
    np = rc.require_numpy()
    w, h = parse_image(args.image)
    corners = parse_points(args.corners, "--corners", 2)
    if len(corners) != 4:
        rc.fail("--corners needs exactly four x,y points")
    try:
        rw, rl = (float(v) for v in args.rect.lower().split("x"))
    except ValueError:
        rc.fail(f"--rect must look like 20x10 (width x depth, in --unit) (got {args.rect!r})")
    if rw <= 0 or rl <= 0:
        rc.fail("--rect sizes must be positive")
    if not convex_ccw(corners):
        rc.fail("the four corners do not form a convex quadrilateral in the order given "
                "(origin, along width, far corner, along depth)")
    world = [[0, 0], [rw, 0], [rw, rl], [0, rl]]
    flat = [v for p in corners for v in p]

    def build(coords):
        return homography([coords[i:i + 2] for i in range(0, 8, 2)], world)

    try:
        hm = build(flat)
    except Unsolvable as exc:
        rc.fail(str(exc), rc.EXIT_FAIL)
    perturbed = []
    for i in range(8):
        pair = []
        for d in (-1.0, 1.0):
            moved = list(flat)
            moved[i] += d
            try:
                pair.append(build(moved))
            except Unsolvable:
                pair.append(None)
        perturbed.append(pair)

    def convert(points):
        base = apply_h(hm, points)
        acc = np.zeros(len(points))
        worst = np.zeros(len(points))
        for pair in perturbed:
            if any(x is None for x in pair):
                return base, None, None
            a, b = apply_h(pair[0], points), apply_h(pair[1], points)
            half = np.linalg.norm(b - a, axis=1) / 2
            acc += half ** 2
            worst += np.maximum(np.linalg.norm(a - base, axis=1), np.linalg.norm(b - base, axis=1))
        return base, np.sqrt(acc), worst

    unit = args.unit
    out = {"mode": "ground", "image": [w, h], "unit": unit, "rect": [rw, rl], "corners": corners,
           "homography_img_to_ground": [[round(float(v), 10) for v in row] for row in hm], "warnings": [], "measurements": []}
    c = rc.parse_float_list(args.principal, "--principal") if args.principal else [w / 2, h / 2]
    try:
        out["camera_from_rect"] = {k: round(v, 4) for k, v in camera_from_rect(corners, w, h, c, rw).items()}
    except Unsolvable as exc:
        out["camera_from_rect"] = None
        out["warnings"].append(f"camera not solvable from the rectangle alone ({exc}); the homography is still valid")

    method = (f"camera_solve ground: homography from a {rw:g}x{rl:g} {unit} ground rectangle with corners {args.corners} "
              f"in a {w}x{h} frame; uncertainty = +/-1 px per corner coordinate in quadrature")
    if args.points:
        pts = parse_points(args.points, "--points", 2)
        try:
            g, unc, worst = convert(pts)
        except Unsolvable as exc:
            rc.fail(str(exc), rc.EXIT_FAIL)
        out["points"] = [{"px": p, "ground": [round(float(a), 4), round(float(b), 4)],
                          "uncertainty": None if unc is None else round(float(unc[i]), 4),
                          "units_per_px": [round(v, 5) for v in local_scale(hm, p)]}
                         for i, (p, (a, b)) in enumerate(zip(pts, g))]
    if args.track:
        out.update(convert_track(args, hm, convert, perturbed, method, unit))
        out["measurements"] = out["track"].pop("measurements", [])
        out["warnings"] += out["track"].pop("warnings_track", [])
    elif args.analyze != "none":
        rc.fail("--analyze needs --track")
    out["method"] = method
    return out


def convert_track(args, hm, convert, perturbed, method, unit) -> dict:
    np = rc.require_numpy()
    import motion_track

    track = rc.read_json(args.track)
    if track.get("tool") != "motion_track" or not track.get("samples"):
        rc.fail(f"{args.track} is not motion_track output")
    if track.get("anchor_bbox") and not args.assume_static:
        rc.fail("the track cancelled camera motion with --anchor-bbox, but a ground homography from fixed corners only holds "
                "for a static camera; re-mark the corners per shot, or pass --assume-static if the anchor only removed shake")
    samples = track["samples"]
    bh = float(track.get("bbox", [0, 0, 0, 0])[3])
    # The bottom of the box moves with the tracked scale when motion_track ran with --scale-search.
    offs = [(bh / 2) * float(s.get("scale", 1.0)) if args.contact == "bottom" else 0.0 for s in samples]
    pts = [[s["x_px"], s["y_px"] + dy] for s, dy in zip(samples, offs)]
    try:
        g, unc, worst = convert(pts)
    except Unsolvable as exc:
        rc.fail(f"track conversion failed: {exc}", rc.EXIT_FAIL)
    scales = [local_scale(hm, p) for p in pts]
    x0, z0 = float(g[0, 0]), float(g[0, 1])
    rows = []
    for i, s in enumerate(samples):
        rows.append({"sample": s.get("sample", i), "index": s.get("index"), "t": s["t"],
                     "x_px": s["x_px"], "y_px": round(pts[i][1], 3), "score": s.get("score"),
                     "X": round(float(g[i, 0]), 5), "Z": round(float(g[i, 1]), 5),
                     "u": round(float(g[i, 0]) - x0, 5), "v": round(float(g[i, 1]) - z0, 5),
                     "uncertainty": None if unc is None else round(float(unc[i]), 5)})
    upx = sorted(sc[0] for sc in scales)
    res = {"tool": TOOL, "schema": SCHEMA, "source_track": str(args.track), "contact": args.contact,
           "unit": unit, "samples": rows,
           "units_per_px": {"median": round(upx[len(upx) // 2], 5), "min": round(upx[0], 5), "max": round(upx[-1], 5)},
           "low_score_samples": track.get("low_score_samples", 0)}
    warn = []
    has_scale = any("scale" in s for s in samples)
    if upx[-1] > 1.3 * upx[0] and not has_scale:
        warn.append(f"one pixel covers {upx[-1] / upx[0]:.1f}x more ground at one end of the path than the other (perspective): "
                    "a fixed-size template drifts as the subject shrinks; re-run motion_track with --scale-search")
    low = int(track.get("low_score_samples") or 0)
    if low:
        warn.append(f"the source track has {low} low-score samples (the tracker lost or partly lost the subject); "
                    "measurements are withheld from the ledger until the track is fixed")
    if args.contact == "center":
        warn.append("contact = center: correct only when the tracked feature lies on the ground (a shadow or a decal); "
                    "for a standing character use --contact bottom with a box around the whole body")
    if args.analyze == "speed":
        t = np.array([r["t"] for r in rows])
        xy = g - g[0]
        d = xy[-1] / max(1e-12, float(np.linalg.norm(xy[-1])))
        s_along = xy @ d
        fps = track.get("fps_from_samples") or 60.0
        speed = motion_track.analyze_speed(t, s_along, unit, upx[len(upx) // 2], fps)
        vs = []
        for pair in perturbed:
            if any(x is None for x in pair):
                vs = None
                break
            vv = []
            for hp in pair:
                gp = apply_h(hp, pts)
                xp = gp - gp[0]
                vv.append(motion_track.analyze_speed(t, xp @ d, unit, upx[len(upx) // 2], fps)["steady_speed"])
            vs.append((vv[1] - vv[0]) / 2)
        geo = math.sqrt(sum(v * v for v in vs)) if vs is not None else None
        speed["steady_speed_geometry_unc"] = None if geo is None else round(geo, 4)
        speed["direction_ground"] = [round(float(d[0]), 4), round(float(d[1]), 4)]
        res["speed"] = speed
        if geo is None:
            warn.append("steady speed is unstable under a 1 px corner change; mark a larger rectangle")
        tot = None if geo is None else math.hypot(geo, 2 * speed.get("steady_speed_std", 0.0))
        m2 = (f"{method}; track {Path(args.track).name} ({args.contact} of bbox) converted to the ground plane; "
              f"standing-start fit (preferred model {speed['preferred_model']})")
        if not low and geo is not None:
            res["measurements"] = [
                measurement("ground_speed", "steady ground speed (ground-plane track)", speed["steady_speed"], tot, f"{unit}/s", m2),
                measurement("accel_t90", "time to 90% speed (ground-plane track)", speed["t90_s"], speed["time_precision_s"], "s", m2),
            ]
    res["warnings_track"] = warn
    return {"track": res}


# ----------------------------------------------------------------- output

def print_result(out: dict) -> None:
    if out["mode"] in ("vanishing", "size"):
        r = out["result"]
        u = r["uncertainty"]

        def pm(k):
            return f"{r[k]:.3f} ± {u[k]:.3f}" if u.get(k) is not None else f"{r[k]:.3f} (unstable)"

        print(f"focal length: {pm('focal_px')} px")
        print(f"vertical FOV: {pm('vfov_deg')} deg   (Roblox Camera.FieldOfView)")
        print(f"horizontal FOV: {pm('hfov_deg')} deg at {out['image'][0]}x{out['image'][1]}")
        if out["mode"] == "vanishing":
            print(f"pitch: {pm('pitch_deg')} deg   roll: {pm('roll_deg')} deg")
            if "height" in r:
                print(f"camera height: {pm('height')} {out['unit']}   distance to marked base: {pm('distance_to_base')} {out['unit']}")
            print(f"vanishing points: {r['vanishing_points']}")
    else:
        cam = out.get("camera_from_rect")
        if cam:
            print(f"camera from rectangle: vFOV {cam['vfov_deg']:.2f} deg, pitch {cam['pitch_deg']:.2f} deg, "
                  f"height {cam['height']:.3f} {out['unit']} (principal point assumed centered)")
        for p in out.get("points", []):
            unc = f" ± {p['uncertainty']}" if p["uncertainty"] is not None else " (unstable)"
            print(f"px {p['px'][0]:g},{p['px'][1]:g} -> ground {p['ground'][0]}, {p['ground'][1]}{unc} {out['unit']}")
        tr = out.get("track")
        if tr:
            print(f"converted {len(tr['samples'])} track samples; {tr['units_per_px']['median']} {out['unit']}/px at the subject (median)")
            sp = tr.get("speed")
            if sp:
                tot = out["measurements"][0]["uncertainty"] if out["measurements"] else "withheld"
                print(f"  steady_speed: {sp['steady_speed']} {out['unit']}/s ± {tot} "
                      f"(fit std {sp['steady_speed_std']}, geometry {sp['steady_speed_geometry_unc']})")
                print(f"  t90_s: {sp['t90_s']}  preferred_model: {sp['preferred_model']}")
    for wmsg in out.get("warnings", []):
        print(f"WARNING: {wmsg}", file=sys.stderr)


def luau_lines(out: dict) -> list[str]:
    r = out.get("result") or out.get("camera_from_rect")
    if not r:
        return []
    u = (out.get("result") or {}).get("uncertainty", {})
    lines = [f"FieldOfView = {r['vfov_deg']:.2f}, -- camera_solve {out['mode']}: vertical FOV ± {u.get('vfov_deg', '?')} deg"]
    if "pitch_deg" in r:
        lines.append(f"StartPitchDeg = {r['pitch_deg']:.2f}, -- camera_solve {out['mode']}: pitch ± {u.get('pitch_deg', '?')} deg")
    return lines


COORD_OPTIONS = {"--lines-x", "--lines-z", "--lines-y", "--known-height", "--known-ground", "--span", "--corners",
                 "--points", "--principal"}


def join_negative_values(argv: list[str]) -> list[str]:
    """Let coordinate lists start with a negative number (argparse would read "-12,..." as an option)."""
    out, i = [], 0
    while i < len(argv):
        a = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else ""
        if a in COORD_OPTIONS and len(nxt) > 1 and nxt[0] == "-" and (nxt[1].isdigit() or nxt[1] == "."):
            out.append(f"{a}={nxt}")
            i += 2
            continue
        out.append(a)
        i += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--image", required=True, help="source frame size, WxH (for example 1920x1080)")
        p.add_argument("--principal", help="principal point cx,cy in px (default: image center)")
        p.add_argument("--unit", default="studs", help="world unit of known sizes (default studs)")
        p.add_argument("--out", type=Path, help="write JSON results here")
        p.add_argument("--json", action="store_true")
        p.add_argument("--luau", action="store_true", help="print Config.Camera lines")

    p = sub.add_parser("vanishing", help="FOV, pitch, roll (and height) from parallel line sets")
    common(p)
    p.add_argument("--lines-x", help="lines along one ground direction: x1,y1,x2,y2;...")
    p.add_argument("--lines-z", help="lines along the perpendicular ground direction")
    p.add_argument("--lines-y", help="vertical world edges (optional third set)")
    p.add_argument("--known-height", help="base_x,base_y,top_x,top_y,H: a vertical object of height H standing on the ground")
    p.add_argument("--known-ground", help="x1,y1,x2,y2,D: two ground points D apart")
    p = sub.add_parser("size", help="FOV from an object of known size at a known depth")
    common(p)
    p.add_argument("--span", required=True, help="x1,y1,x2,y2: the object's two ends in the frame")
    p.add_argument("--size", type=float, required=True, help="the object's real size along the marked span")
    p.add_argument("--distance", type=float, required=True, help="the object's depth from the camera along the view axis")
    p.add_argument("--size-uncertainty", type=float, default=0.0)
    p.add_argument("--distance-uncertainty", type=float, default=0.0)
    p = sub.add_parser("ground", help="image-to-ground homography from a known rectangle; convert points or a track")
    common(p)
    p.add_argument("--corners", required=True, help="x,y;x,y;x,y;x,y: origin, along width, far corner, along depth")
    p.add_argument("--rect", required=True, help="WIDTHxDEPTH of the rectangle in --unit (for example 20x10)")
    p.add_argument("--points", help="x,y;x,y image points on the ground to convert")
    p.add_argument("--track", type=Path, help="motion_track output whose tracked feature touches the ground")
    p.add_argument("--contact", choices=["bottom", "center"], default="bottom",
                   help="which point of the tracked bbox touches the ground (default bottom)")
    p.add_argument("--analyze", choices=["speed", "none"], default="none", help="re-run the standing-start speed fit in world units")
    p.add_argument("--assume-static", action="store_true", help="accept a track that used --anchor-bbox (shake only)")
    args = ap.parse_args(join_negative_values(sys.argv[1:]))

    out = {"cmd_vanishing": cmd_vanishing, "cmd_size": cmd_size, "cmd_ground": cmd_ground}[f"cmd_{args.cmd}"](args)
    out = {"tool": TOOL, "schema": SCHEMA, **out}
    if args.out:
        rc.write_json(args.out, out)
    if args.json:
        print(rc.dump_json(out))
    else:
        print_result(out)
        if args.luau:
            print("\n-- Luau (Config.Camera; keep the evidence IDs)")
            print("\n".join(luau_lines(out)))
        if args.out:
            print(f"wrote {args.out}")
    return rc.EXIT_OK


if __name__ == "__main__":
    rc.run_main(main)
