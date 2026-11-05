#!/usr/bin/env python3
"""Track several body points and turn them into 2D joint angles, cycle timing and keyposes.

Each --point is tracked with the same template matcher as motion_track.py (a square patch
centered on the point). Angles are measured in the image plane:
  --joint knee=hip,knee,foot   interior angle at the middle point (180 = straight)
  --segment thigh=hip,knee     segment direction from straight down; positive toward screen right
--cycle foot.y finds the cycle period of a signal (point.x or point.y, image pixels) by
autocorrelation, and keyposes are the extremes of that signal (contact, passing, apex...).

The output is a first draft of the keypose table in animation-analysis.md. Angles from 2D
footage are projections: treat them as ±10° unless the limb moves parallel to the image plane.

Examples:
  python pose_track.py frames/run/manifest.json --point hip=412,300 --point knee=420,350 --point foot=414,398 \
    --joint knee=hip,knee,foot --segment thigh=hip,knee --cycle foot.y --table remake/anim/run-keys.md --out remake/tracks/run-pose.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402
from motion_track import track  # noqa: E402

TOOL = "pose_track"


def parse_named(text: str, n: int, what: str) -> tuple[str, list[str]]:
    if "=" not in text:
        rc.fail(f"{what} must look like name=a,b{',c' if n == 3 else ''} (got {text!r})")
    name, rest = text.split("=", 1)
    parts = [p.strip() for p in rest.split(",")]
    if len(parts) != n or not name.strip():
        rc.fail(f"{what} {text!r} needs {n} comma-separated values")
    return name.strip(), parts


def segment_angle(a, b) -> float:
    """Direction of a->b in degrees from straight down (image y down); positive toward +x."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    return math.degrees(math.atan2(dx, dy))


def joint_angle(a, b, c) -> float:
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return float("nan")
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos))


def period_frames(sig) -> tuple[float | None, float]:
    np = rc.require_numpy()
    x = np.asarray(sig, float)
    x = x - np.polyval(np.polyfit(np.arange(len(x)), x, 1), np.arange(len(x)))
    if np.allclose(x, 0):
        return None, 0.0
    ac = np.correlate(x, x, mode="full")[len(x) - 1:]
    ac /= ac[0]
    for lag in range(3, len(ac) - 1):
        if ac[lag] > ac[lag - 1] and ac[lag] >= ac[lag + 1] and ac[lag] > 0.3:
            a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
            denom = a - 2 * b + c
            off = 0.5 * (a - c) / denom if abs(denom) > 1e-12 else 0.0
            return lag + off, float(b)
    return None, 0.0


def extremes(sig, min_gap: int):
    np = rc.require_numpy()
    x = np.convolve(np.asarray(sig, float), np.ones(3) / 3, mode="same")
    keys = []
    for i in range(1, len(x) - 1):
        kind = "max" if x[i] >= x[i - 1] and x[i] > x[i + 1] else ("min" if x[i] <= x[i - 1] and x[i] < x[i + 1] else None)
        if kind and (not keys or i - keys[-1][0] >= min_gap):
            keys.append((i, kind))
    return keys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--point", action="append", required=True, help="name=x,y on the first frame (repeatable)")
    ap.add_argument("--joint", action="append", default=[], help="name=a,b,c interior angle at b")
    ap.add_argument("--segment", action="append", default=[], help="name=a,b direction from straight down")
    ap.add_argument("--patch", type=int, default=16, help="template size in pixels (default 16)")
    ap.add_argument("--search", type=int, default=48)
    ap.add_argument("--anchor-bbox", help="static patch to cancel camera motion")
    ap.add_argument("--cycle", help="signal for the cycle period, point.x or point.y")
    ap.add_argument("--min-score", type=float, default=0.6)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--table", type=Path, help="write a Markdown keypose table draft")
    args = ap.parse_args()

    point_names = [parse_named(p, 2, "--point")[0] for p in args.point]
    joints = [parse_named(j, 3, "--joint") for j in args.joint]
    segments = [parse_named(s, 2, "--segment") for s in args.segment]
    for name, refs in joints + segments:
        for r in refs:
            if r not in point_names:
                rc.fail(f"{name}: unknown point {r!r} (defined: {', '.join(point_names)})")
    _, frames, base = rc.load_manifest(args.manifest)
    images = [rc.load_gray(base / f["file"]) for f in frames]
    times = [float(f.get("pts_time", i / 60)) for i, f in enumerate(frames)]
    fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 60.0
    half = args.patch // 2
    anchor = track(images, rc.parse_bbox(args.anchor_bbox, "--anchor-bbox"), args.search, 1) if args.anchor_bbox else None
    points: dict[str, list] = {}
    low: dict[str, int] = {}
    for spec in args.point:
        name, xy = parse_named(spec, 2, "--point")
        x, y = (int(round(float(v))) for v in xy)
        if x - half < 0 or y - half < 0:
            rc.fail(f"point {name} is too close to the frame edge for a {args.patch}px patch")
        tr = track(images, (x - half, y - half, args.patch, args.patch), args.search, 1)
        if anchor:
            tr = [(px - (anchor[i][0] - anchor[0][0]), py - (anchor[i][1] - anchor[0][1]), s) for i, (px, py, s) in enumerate(tr)]
        points[name] = tr
        low[name] = sum(1 for _, _, s in tr if s < args.min_score)

    rows = []
    for i, f in enumerate(frames):
        row = {"sample": i, "index": f.get("index"), "t": round(times[i], 5)}
        for name, tr in points.items():
            row[f"{name}.x"], row[f"{name}.y"] = round(tr[i][0], 2), round(tr[i][1], 2)
        for name, (a, b, c) in joints:
            row[name] = round(joint_angle(points[a][i], points[b][i], points[c][i]), 2)
        for name, (a, b) in segments:
            row[name] = round(segment_angle(points[a][i], points[b][i]), 2)
        rows.append(row)

    result = {"tool": TOOL, "manifest": str(args.manifest), "fps_from_samples": round(fps, 4),
              "points": {k: [round(v[0][0], 1), round(v[0][1], 1)] for k, v in points.items()},
              "low_score_samples": low, "angles": [n for n, _ in joints] + [n for n, _ in segments], "samples": rows}
    angle_names = result["angles"]
    if args.cycle:
        if args.cycle not in rows[0]:
            rc.fail(f"--cycle {args.cycle!r} is not a tracked signal (use point.x or point.y)")
        sig = [r[args.cycle] for r in rows]
        per, strength = period_frames(sig)
        cyc = {"signal": args.cycle, "period_frames": round(per, 3) if per else None,
               "period_s": round(per / fps, 5) if per else None, "strength": round(strength, 3),
               "cycles_observed": round(len(sig) / per, 2) if per else 0}
        keys = extremes(sig, max(2, int((per or 8) / 4)))
        cyc["keyposes"] = [{"sample": k, "index": rows[k]["index"], "t": rows[k]["t"],
                            "kind": f"{args.cycle} {kind}" + ((" (lowest on screen)" if kind == "max" else " (highest on screen)")
                                                               if args.cycle.endswith(".y") else ""),
                            **{n: rows[k][n] for n in angle_names}} for k, kind in keys]
        result["cycle"] = cyc
    if args.out:
        rc.write_json(args.out, result)
    if args.table:
        lines = [f"<!-- pose_track.py draft from {args.manifest}; 2D projected angles, verify against frames -->", ""]
        if result.get("cycle", {}).get("period_frames"):
            c = result["cycle"]
            lines.append(f"Cycle: {c['period_frames']} frames ({c['period_s']} s) at {fps:.2f} fps from {c['signal']}, "
                         f"{c['cycles_observed']} cycles observed (strength {c['strength']}).")
            lines.append("")
        keyrows = result.get("cycle", {}).get("keyposes") or [{"index": r["index"], "t": r["t"], "kind": "", **{n: r[n] for n in angle_names}} for r in rows[:: max(1, len(rows) // 8)]]
        lines.append("| frame | t (s) | key | " + " | ".join(angle_names) + " |")
        lines.append("|---|---|---|" + "---|" * len(angle_names))
        for k in keyrows:
            lines.append(f"| {k['index']} | {k['t']} | {k['kind']} | " + " | ".join(f"{k[n]:.1f}°" for n in angle_names) + " |")
        rc.ensure_parent(args.table)
        args.table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"tracked {len(points)} points over {len(rows)} frames; low-score samples {low}")
    if "cycle" in result:
        c = result["cycle"]
        if c["period_frames"]:
            print(f"cycle: {c['period_frames']} frames = {c['period_s']} s ({c['cycles_observed']} cycles, strength {c['strength']})")
        else:
            print("cycle: no clear period; track a longer clip or another signal")
        for k in c["keyposes"][:8]:
            print(f"  key frame {k['index']} t={k['t']} {k['kind']}: " + ", ".join(f"{n} {k[n]:.1f}" for n in angle_names))
    if any(low.values()):
        print("WARNING: low match scores; patches may have slipped (occlusion, rotation). Check with frame_zoom.py --point.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    rc.run_main(main)
