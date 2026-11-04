#!/usr/bin/env python3
"""Probe a reference video before any frame-by-frame measurement.

Reports nominal frame rate, variable-frame-rate (VFR) behavior, resolution and aspect, and
(with --dupes) near-duplicate consecutive frames, which reveal the effective update rate of the
content. A 60 fps file with ~50% duplicates is 30 fps content: timing precision is then one
33.3 ms frame, not 16.7 ms.

Examples:
  python probe_video.py clip.mp4
  python probe_video.py clip.mp4 --dupes --json
  python probe_video.py clip.mp4 --dupes --dupes-region 0,0,640,360 --max-frames 1200
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "probe_video"


def analyze_timestamps(ts: list[float]) -> dict:
    if len(ts) < 2:
        return {"frames_counted": len(ts), "vfr": False}
    deltas = [b - a for a, b in zip(ts, ts[1:]) if b - a > 0]
    if not deltas:
        return {"frames_counted": len(ts), "vfr": False}
    med = statistics.median(deltas)
    long_gaps = sum(1 for d in deltas if d > 1.5 * med)
    spread = (max(deltas) - min(deltas)) / med if med > 0 else 0.0
    # Container rounding produces tiny jitter; treat >5% spread with gaps or >25% spread as VFR.
    vfr = spread > 0.25 or (spread > 0.05 and long_gaps > 0)
    return {
        "frames_counted": len(ts),
        "first_pts": round(ts[0], 6),
        "last_pts": round(ts[-1], 6),
        "delta_median_ms": round(med * 1000, 4),
        "delta_min_ms": round(min(deltas) * 1000, 4),
        "delta_max_ms": round(max(deltas) * 1000, 4),
        "delta_std_ms": round(statistics.pstdev(deltas) * 1000, 4),
        # Mean rate over the clip is robust to millisecond-rounded container timestamps.
        "fps_from_timestamps": round((len(ts) - 1) / (ts[-1] - ts[0]), 4) if ts[-1] > ts[0] else None,
        "long_gaps": long_gaps,
        "vfr": vfr,
    }


def duplicate_analysis(video: Path, width: int, height: int, region, threshold: float, max_frames: int | None) -> dict:
    np = rc.require_numpy()
    rc.need_tool("ffmpeg")
    filters = []
    if region:
        x, y, w, h = region
        if x + w > width or y + h > height:
            rc.fail(f"--dupes-region {region} lies outside the {width}x{height} frame")
        filters.append(f"crop={w}:{h}:{x}:{y}")
        width, height = w, h
    sw = min(160, width)
    sh = max(2, int(round(sw * height / width / 2.0)) * 2)
    filters.append(f"scale={sw}:{sh}:flags=area")
    filters.append("format=gray")
    cmd = ["ffmpeg", "-v", "error", "-i", str(video), "-map", "0:v:0", "-vf", ",".join(filters)]
    cmd += ["-fps_mode", "passthrough"]
    if max_frames:
        cmd += ["-frames:v", str(int(max_frames))]
    cmd += ["-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = rc.run(cmd, check=False)
    if proc.returncode != 0:
        # ffmpeg older than 5.1 has no -fps_mode
        cmd = [c for c in cmd if c not in ("-fps_mode", "passthrough")]
        cmd[cmd.index("-f"):cmd.index("-f")] = ["-vsync", "0"]
        proc = rc.run(cmd)
    frame_size = sw * sh
    raw = proc.stdout
    count = len(raw) // frame_size
    if count < 2:
        rc.fail("not enough decoded frames for duplicate analysis")
    frames = np.frombuffer(raw[: count * frame_size], dtype=np.uint8).reshape(count, sh, sw).astype(np.float32)
    mad = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    p75 = float(np.percentile(mad, 75))
    auto = threshold is None
    if auto:
        # Duplicates sit near zero relative to typical inter-frame change; lossy encodes add a
        # little noise, so scale the cut-off with the 75th percentile of all differences.
        threshold = max(0.02, 0.2 * p75)
    dup = mad < threshold
    runs: dict[int, int] = {}
    run_len = 0
    for is_dup in dup:
        if is_dup:
            run_len += 1
        else:
            if run_len:
                runs[run_len] = runs.get(run_len, 0) + 1
            run_len = 0
    if run_len:
        runs[run_len] = runs.get(run_len, 0) + 1
    pct = np.percentile(mad, [5, 25, 50, 75, 95]).tolist()
    return {
        "frames_analyzed": int(count),
        "threshold": round(float(threshold), 4),
        "threshold_mode": "auto" if auto else "fixed",
        "low_motion": bool(np.percentile(mad, 95) < 0.5),
        "duplicate_pairs": int(dup.sum()),
        "duplicate_ratio": round(float(dup.mean()), 4),
        "duplicate_run_histogram": {str(k): v for k, v in sorted(runs.items())},
        "mad_percentiles": {k: round(v, 4) for k, v in zip(("p5", "p25", "p50", "p75", "p95"), pct)},
        "region": list(region) if region else None,
    }


def build_report(video: Path, args) -> dict:
    info = rc.ffprobe_json(video)
    vs = rc.video_stream(info)
    fmt = info.get("format", {})
    width, height = int(vs.get("width") or 0), int(vs.get("height") or 0)
    r_rate = rc.parse_rate(vs.get("r_frame_rate"))
    avg_rate = rc.parse_rate(vs.get("avg_frame_rate"))
    sar = vs.get("sample_aspect_ratio") or "1:1"
    dar = vs.get("display_aspect_ratio")
    try:
        sar_value = rc.parse_aspect(sar) if sar not in ("0:1", "N/A") else 1.0
    except rc.ToolError:
        sar_value = 1.0
    display_aspect = (width * sar_value / height) if height else None
    report = {
        "tool": TOOL,
        "video": str(video),
        "codec": vs.get("codec_name"),
        "pix_fmt": vs.get("pix_fmt"),
        "width": width,
        "height": height,
        "sample_aspect_ratio": sar,
        "display_aspect_ratio": dar,
        "display_aspect": round(display_aspect, 6) if display_aspect else None,
        "fps_r_frame_rate": round(r_rate, 6) if r_rate else None,
        "fps_avg_frame_rate": round(avg_rate, 6) if avg_rate else None,
        "duration_s": float(fmt.get("duration") or vs.get("duration") or 0) or None,
        "nb_frames_header": int(vs["nb_frames"]) if str(vs.get("nb_frames", "")).isdigit() else None,
    }
    ts = rc.frame_timestamps(video, args.max_frames)
    report["timestamps"] = analyze_timestamps(ts)
    nominal = report["timestamps"].get("fps_from_timestamps") or avg_rate or r_rate
    if nominal and r_rate and abs(nominal - r_rate) / r_rate < 0.005 and not report["timestamps"].get("vfr"):
        nominal = r_rate  # snap to the declared constant rate when they agree within 0.5%
    report["fps_nominal"] = round(nominal, 4) if nominal else None
    report["vfr"] = bool(report["timestamps"].get("vfr"))
    if args.dupes:
        region = rc.parse_bbox(args.dupes_region, "--dupes-region") if args.dupes_region else None
        d = duplicate_analysis(video, width, height, region, args.dupes_threshold, args.max_frames)
        report["dupes"] = d
        if nominal:
            unique = d["frames_analyzed"] - d["duplicate_pairs"]
            report["effective_fps"] = round(nominal * unique / d["frames_analyzed"], 3)
            report["timing_precision_ms"] = round(1000.0 / max(report["effective_fps"], 1e-6), 3)
    else:
        report["effective_fps"] = report["fps_nominal"]
        report["timing_precision_ms"] = round(1000.0 / nominal, 3) if nominal else None
    report["warnings"] = warnings_for(report)
    return report


def warnings_for(r: dict) -> list[str]:
    out = []
    if r.get("vfr"):
        out.append("Variable frame rate: use per-frame pts_time from extract_frames manifests, not index/fps.")
    d = r.get("dupes")
    if d and d["duplicate_ratio"] > 0.1:
        out.append(
            f"{d['duplicate_ratio']:.0%} near-duplicate frames: content updates at about "
            f"{r.get('effective_fps')} fps; count timings at that rate."
        )
    if d and d.get("low_motion"):
        out.append("Very little motion in the analyzed area: duplicate detection is unreliable; "
                   "use --dupes-region on a moving element such as the character.")
    if r.get("fps_nominal") and r["fps_nominal"] < 50:
        out.append("Below 50 fps: fast events (attack frames, hit-stop) may fall between frames.")
    if r.get("sample_aspect_ratio") not in (None, "1:1", "0:1", "N/A"):
        out.append("Non-square pixels: convert to the display aspect before measuring UI or FOV.")
    return out


def print_text(r: dict) -> None:
    print(f"video:            {r['video']}")
    print(f"codec:            {r['codec']} {r['pix_fmt']}  {r['width']}x{r['height']}  DAR {r['display_aspect_ratio']}")
    print(f"fps nominal:      {r['fps_nominal']}  (r_frame_rate {r['fps_r_frame_rate']}, avg {r['fps_avg_frame_rate']})")
    t = r["timestamps"]
    print(f"frames counted:   {t.get('frames_counted')}  duration {r.get('duration_s')} s")
    print(f"frame delta ms:   median {t.get('delta_median_ms')}  min {t.get('delta_min_ms')}  max {t.get('delta_max_ms')}  gaps {t.get('long_gaps')}")
    print(f"variable rate:    {'YES' if r['vfr'] else 'no'}")
    if "dupes" in r:
        d = r["dupes"]
        print(f"duplicates:       {d['duplicate_pairs']}/{d['frames_analyzed'] - 1} pairs ({d['duplicate_ratio']:.1%}), runs {d['duplicate_run_histogram']}")
        print(f"MAD percentiles:  {d['mad_percentiles']}")
    print(f"effective fps:    {r.get('effective_fps')}  (timing precision ±{r.get('timing_precision_ms')} ms)")
    for w in r["warnings"]:
        print(f"WARNING: {w}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--dupes", action="store_true", help="analyze near-duplicate consecutive frames")
    ap.add_argument("--dupes-threshold", type=float, default=None,
                    help="mean absolute difference (0-255, on a 160px-wide grayscale proxy) below which consecutive "
                         "frames count as duplicates (default: auto = max(0.02, 0.2 x 75th percentile))")
    ap.add_argument("--dupes-region", help="x,y,w,h region to analyze (for example a character or HUD element)")
    ap.add_argument("--max-frames", type=int, help="only analyze the first N frames")
    ap.add_argument("--json", action="store_true", help="print JSON")
    args = ap.parse_args()
    if not args.video.is_file():
        rc.fail(f"video not found: {args.video}")
    report = build_report(args.video, args)
    if args.json:
        print(rc.dump_json(report))
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    rc.run_main(main)
