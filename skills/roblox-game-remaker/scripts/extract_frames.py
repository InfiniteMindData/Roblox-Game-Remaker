#!/usr/bin/env python3
"""Extract exact video frames with a traceable manifest.

Every output file is named f<index>_t<pts>.png, where <index> is the 0-based source frame
index in presentation order and <pts> its presentation timestamp in seconds. manifest.json lists
all extracted frames, so later measurements can cite exact frames.

Modes:
  all     every frame
  every   every Nth frame (--step)
  range   frames --start..--end inclusive (source indexes)
  times   the frame nearest each timestamp in --times (seconds)
  scene   frames where the scene changes by more than --threshold (0-1), plus frame 0

Examples:
  python extract_frames.py clip.mp4 --out frames/jump --mode range --start 240 --end 300
  python extract_frames.py clip.mp4 --out frames/overview --mode every --step 15
  python extract_frames.py clip.mp4 --out frames/cuts --mode scene --threshold 0.3
  python extract_frames.py clip.mp4 --out frames/hud --mode times --times 12.5,40 --crop 0,900,600,180
"""

from __future__ import annotations

import argparse
import bisect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "extract_frames"


def contiguous_runs(indices: list[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for i in indices:
        if runs and i == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((i, i))
    return runs


def select_expression(indices: list[int], mode: str, step: int | None) -> str:
    if mode == "all":
        return ""
    if mode == "every":
        return f"not(mod(n\\,{step}))"
    parts = []
    for a, b in contiguous_runs(indices):
        parts.append(f"eq(n\\,{a})" if a == b else f"between(n\\,{a}\\,{b})")
    return "+".join(parts)


def nearest_index(ts: list[float], t: float) -> int:
    pos = bisect.bisect_left(ts, t)
    if pos <= 0:
        return 0
    if pos >= len(ts):
        return len(ts) - 1
    return pos if abs(ts[pos] - t) < abs(ts[pos - 1] - t) else pos - 1


def scene_indices(video: Path, threshold: float, ts: list[float]) -> list[int]:
    rc.need_tool("ffmpeg")
    proc = rc.run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-map", "0:v:0",
        "-vf", f"select='gt(scene\\,{threshold})',showinfo", "-f", "null", "-",
    ])
    found = {0}
    for m in re.finditer(r"pts_time:\s*([0-9.]+)", proc.stderr.decode("utf-8", "replace")):
        found.add(nearest_index(ts, float(m.group(1))))
    return sorted(found)


def run_ffmpeg(video: Path, out_dir: Path, select: str, crop, scale: int | None, fmt: str, expected: int) -> list[Path]:
    rc.need_tool("ffmpeg")
    filters = []
    if select:
        filters.append(f"select='{select}'")
    if crop:
        x, y, w, h = crop
        filters.append(f"crop={w}:{h}:{x}:{y}")
    if scale:
        filters.append(f"scale={scale}:-2:flags=lanczos")
    tmp_pattern = str(out_dir / f"__tmp_%07d.{fmt}")
    base = ["ffmpeg", "-hide_banner", "-v", "error", "-i", str(video), "-map", "0:v:0"]
    if filters:
        base += ["-vf", ",".join(filters)]
    quality = ["-q:v", "2"] if fmt == "jpg" else []
    attempt = base + ["-fps_mode", "passthrough"] + quality + [tmp_pattern]
    proc = rc.run(attempt, check=False)
    if proc.returncode != 0:
        for leftover in out_dir.glob("__tmp_*"):
            leftover.unlink()
        rc.run(base + ["-vsync", "0"] + quality + [tmp_pattern])
    produced = sorted(out_dir.glob(f"__tmp_*.{fmt}"))
    if len(produced) != expected:
        for p in produced:
            p.unlink()
        rc.fail(
            f"ffmpeg produced {len(produced)} frames but {expected} were selected. The decoder's frame "
            "numbering differs from the container timestamps (edit lists or a damaged stream). "
            "Remux the clip first: ffmpeg -i in.mp4 -c copy -map 0:v:0 fixed.mkv",
            rc.EXIT_FAIL,
        )
    return produced


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--out", type=Path, required=True, help="output directory (created; must be empty unless --overwrite)")
    ap.add_argument("--mode", choices=["all", "every", "range", "times", "scene"], default="range")
    ap.add_argument("--start", type=int, help="first source frame index (range mode)")
    ap.add_argument("--end", type=int, help="last source frame index, inclusive (range mode)")
    ap.add_argument("--step", type=int, help="keep every Nth frame (every mode)")
    ap.add_argument("--times", help="comma-separated timestamps in seconds (times mode)")
    ap.add_argument("--threshold", type=float, default=0.3, help="scene-change threshold 0-1 (scene mode, default 0.3)")
    ap.add_argument("--crop", help="x,y,w,h crop applied to every frame (source pixels)")
    ap.add_argument("--scale", type=int, help="resize output to this width (keeps aspect)")
    ap.add_argument("--format", choices=["png", "jpg"], default="png")
    ap.add_argument("--max-frames", type=int, default=5000, help="refuse to write more frames than this (default 5000)")
    ap.add_argument("--overwrite", action="store_true", help="allow writing into a non-empty output directory")
    args = ap.parse_args()

    if not args.video.is_file():
        rc.fail(f"video not found: {args.video}")
    ts = rc.frame_timestamps(args.video)
    n = len(ts)

    if args.mode == "all":
        indices = list(range(n))
    elif args.mode == "every":
        if not args.step or args.step < 1:
            rc.fail("--mode every needs --step N (N >= 1)")
        indices = list(range(0, n, args.step))
    elif args.mode == "range":
        if args.start is None or args.end is None:
            rc.fail("--mode range needs --start and --end (source frame indexes)")
        if args.start < 0 or args.end < args.start:
            rc.fail("--start must be >= 0 and --end >= --start")
        if args.start >= n:
            rc.fail(f"--start {args.start} is past the last frame ({n - 1})")
        indices = list(range(args.start, min(args.end, n - 1) + 1))
    elif args.mode == "times":
        if not args.times:
            rc.fail("--mode times needs --times t1,t2,...")
        indices = sorted({nearest_index(ts, t) for t in rc.parse_float_list(args.times, "--times")})
    else:
        if not 0 < args.threshold < 1:
            rc.fail("--threshold must be between 0 and 1")
        indices = scene_indices(args.video, args.threshold, ts)

    if not indices:
        rc.fail("no frames selected")
    if len(indices) > args.max_frames:
        rc.fail(f"{len(indices)} frames selected, more than --max-frames {args.max_frames}; narrow the selection or raise the limit")

    crop = rc.parse_bbox(args.crop, "--crop") if args.crop else None
    out_dir = rc.ensure_out_dir(args.out, allow_nonempty=args.overwrite)
    select = select_expression(indices, args.mode, args.step)
    produced = run_ffmpeg(args.video, out_dir, select, crop, args.scale, args.format, len(indices))

    frames = []
    for idx, tmp in zip(indices, produced):
        name = f"f{idx:06d}_t{ts[idx]:.6f}.{args.format}"
        target = out_dir / name
        if target.exists():
            target.unlink()
        tmp.rename(target)
        frames.append({"index": idx, "pts_time": round(ts[idx], 6), "file": name})

    fps_guess = None
    if n > 1 and ts[-1] > ts[0]:
        fps_guess = round((n - 1) / (ts[-1] - ts[0]), 4)
    manifest = {
        "tool": TOOL,
        "video": str(args.video),
        "mode": args.mode,
        "selection": {"start": args.start, "end": args.end, "step": args.step, "times": args.times,
                      "threshold": args.threshold if args.mode == "scene" else None},
        "source_frame_count": n,
        "fps_estimate": fps_guess,
        "crop": list(crop) if crop else None,
        "scale_width": args.scale,
        "frames": frames,
    }
    rc.write_json(out_dir / "manifest.json", manifest)
    print(f"wrote {len(frames)} frames to {out_dir} (manifest.json); source has {n} frames, ~{fps_guess} fps")
    return 0


if __name__ == "__main__":
    rc.run_main(main)
