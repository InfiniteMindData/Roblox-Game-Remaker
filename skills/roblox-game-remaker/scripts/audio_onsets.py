#!/usr/bin/env python3
"""Detect sound onsets in a reference clip and map them to video frames.

Decodes the audio with ffmpeg to mono 16-bit PCM, computes a log-energy onset envelope, and
picks peaks above an adaptive threshold. Use it to align footstep sounds with animation contact
frames, hit sounds with active frames, and UI sounds with tweens.

Onsets are found per hop (default 5.8 ms at 22050 Hz), then refined to the sample where the
amplitude envelope starts rising, typically within about 1 ms for clean transients. Overlapping
music masks quieter effects: prefer clips with music turned down.

Times are on the video's presentation timeline, the same as extract_frames manifests (pts_time):
an audio stream that starts later than the video (start_time 2.0 s) is shifted by its start, also
with --start. Frames come from the video's real per-frame timestamps (the nearest frame), so a
variable-frame-rate clip maps correctly; --fps overrides that, with a warning on a VFR clip.

Examples:
  python audio_onsets.py clip.mp4
  python audio_onsets.py clip.mp4 --start 10 --end 14 --sensitivity 2.5 --out onsets.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "audio_onsets"


def audio_start_offset(path: Path, start: float | None) -> tuple[float, list[str]]:
    """Presentation time of the first decoded sample, on the timeline extract_frames uses.

    ffmpeg decodes an audio stream from its first sample whatever its start_time, and -ss seeks
    relative to the container start, so the first sample sits at
    container_start + max(--start, audio_start - container_start)."""
    warnings = []
    try:
        info = rc.ffprobe_json(path)
    except rc.ToolError:
        return (start or 0.0), ["could not probe the stream start times; onset times assume the audio starts at 0"]
    fmt_start = _num((info.get("format") or {}).get("start_time")) or 0.0
    aud = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    a0 = _num((aud or {}).get("start_time"))
    if a0 is None:
        a0 = fmt_start
    if a0 < fmt_start:  # cannot happen per the container rule; trust the stream
        fmt_start = a0
    rel = a0 - fmt_start
    if abs(rel) > 1e-3 and start is None:
        warnings.append(f"the audio stream starts {rel:.3f} s after the video: onset times include that offset")
    return fmt_start + max(start or 0.0, rel), warnings


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def nearest_frame(ts: list[float], t: float) -> int:
    import bisect

    i = bisect.bisect_left(ts, t)
    if i <= 0:
        return 0
    if i >= len(ts):
        return len(ts) - 1
    return i if ts[i] - t < t - ts[i - 1] else i - 1


def decode(path: Path, rate: int, start: float | None, end: float | None):
    np = rc.require_numpy()
    rc.need_tool("ffmpeg")
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(path)]
    if end is not None:
        cmd += ["-t", str(end - (start or 0.0))]
    cmd += ["-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"]
    proc = rc.run(cmd)
    samples = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size == 0:
        rc.fail("no audio decoded (does the file have an audio stream?)", rc.EXIT_FAIL)
    return samples


def check_params(rate: int, hop: int, win: int) -> None:
    if rate < 1000:
        rc.fail("--rate must be at least 1000 Hz")
    if hop < 1:
        rc.fail("--hop must be at least 1 sample")
    if win < 16:
        rc.fail("--window must be at least 16 samples")
    if hop > win:
        rc.fail("--hop must not be larger than --window (samples between windows would be skipped)")


def onsets(samples, rate: int, hop: int, win: int, sensitivity: float, min_gap: float):
    np = rc.require_numpy()
    check_params(rate, hop, win)
    n = 1 + max(0, (len(samples) - win) // hop)
    if n < 3:
        rc.fail("audio is too short to analyze")
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    frames = samples[idx] * np.hanning(win)[None, :]
    energy = (frames ** 2).mean(axis=1)
    loud = 10 * np.log10(energy + 1e-10)
    flux = np.maximum(np.diff(loud, prepend=loud[0]), 0.0)
    med = float(np.median(flux))
    mad = float(np.median(np.abs(flux - med))) * 1.4826 + 1e-6
    thr = med + sensitivity * max(mad, 0.5)
    gap = max(1, int(round(min_gap * rate / hop)))
    picks, last = [], -gap
    for i in range(1, n - 1):
        if flux[i] >= thr and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1] and i - last >= gap:
            # The flux peaks on the first hop that touches the sound, when the window still holds
            # mostly silence; judge loudness a couple of hops later so such onsets are not dropped.
            if float(loud[i:i + 3].max()) > -60:
                picks.append(i)
                last = i
    out = []
    smooth = max(1, int(rate * 0.001))
    kernel = np.ones(smooth) / smooth
    for i in picks:
        # Refine to the sample where the amplitude envelope first rises a quarter of the way
        # from the local floor to the local peak.
        a = max(0, i * hop - win)
        b = min(len(samples), i * hop + 2 * win)
        env = np.convolve(np.abs(samples[a:b]), kernel, mode="same")
        quarter = max(1, len(env) // 4)
        floor, peak = float(np.median(env[:quarter])), float(env.max())
        above = np.nonzero(env >= floor + 0.25 * (peak - floor))[0]
        t = (a + int(above[0])) / rate if len(above) else (i * hop + win / 2) / rate
        out.append((t, float(flux[i]), float(loud[min(i + 2, n - 1)])))
    return out, thr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media", type=Path, help="video or audio file")
    ap.add_argument("--fps", type=float, help="video frame rate for frame mapping (default: probed)")
    ap.add_argument("--start", type=float, help="analyze from this time (s)")
    ap.add_argument("--end", type=float, help="analyze until this time (s)")
    ap.add_argument("--rate", type=int, default=22050)
    ap.add_argument("--hop", type=int, default=128)
    ap.add_argument("--window", type=int, default=512)
    ap.add_argument("--sensitivity", type=float, default=3.0, help="threshold in robust deviations (lower = more onsets)")
    ap.add_argument("--min-gap", type=float, default=0.05, help="minimum seconds between onsets")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if not args.media.is_file():
        rc.fail(f"file not found: {args.media}")
    if args.start is not None and args.end is not None and args.end <= args.start:
        rc.fail("--end must be after --start")
    check_params(args.rate, args.hop, args.window)
    warnings: list[str] = []
    fps = args.fps
    vs = None
    try:
        info = rc.ffprobe_json(args.media)
        vs = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    except rc.ToolError:
        info = None
    avg = rc.parse_rate(vs.get("avg_frame_rate")) if vs else None
    ts = None
    if vs is not None:
        try:
            ts = rc.frame_timestamps(args.media)
        except rc.ToolError:
            ts = None
    vfr = False
    if ts and len(ts) > 2:
        import statistics

        d = [b - a for a, b in zip(ts, ts[1:])]
        med = statistics.median(d)
        vfr = med > 0 and (max(d) > 1.5 * med or min(d) < 0.5 * med)
    if fps is not None:
        mapping = "fps"
        if vfr:
            warnings.append(f"the video has a variable frame rate but --fps {fps:g} maps onsets with one frame period: "
                            "frame numbers drift; leave out --fps to use the per-frame timestamps")
    elif ts:
        mapping = "timestamps"
        fps = avg
    else:
        mapping = "fps" if avg else None
        fps = avg
        if vs is not None:
            warnings.append("could not read per-frame timestamps; frames use the average frame rate and are wrong if the "
                            "frame rate varies (check with probe_video)")
    samples = decode(args.media, args.rate, args.start, args.end)
    found, thr = onsets(samples, args.rate, args.hop, args.window, args.sensitivity, args.min_gap)
    offset, w2 = audio_start_offset(args.media, args.start)
    warnings += w2
    rows = []
    for t, strength, level in found:
        tt = t + offset
        row = {"t": round(tt, 4), "strength_db": round(strength, 2), "level_db": round(level, 1)}
        if mapping == "timestamps":
            row["frame"] = nearest_frame(ts, tt)
        elif mapping == "fps" and fps:
            row["frame"] = int(round(tt * fps))
        rows.append(row)
    result = {"tool": TOOL, "media": str(args.media), "fps": fps, "frame_mapping": mapping, "vfr": vfr,
              "audio_start_s": round(offset, 6), "hop_s": round(args.hop / args.rate, 5),
              "threshold_db": round(thr, 3), "onsets": rows, "warnings": warnings}
    if args.out:
        rc.write_json(args.out, result)
    if args.json:
        print(rc.dump_json(result))
    else:
        for r in rows:
            frame = f"  frame {r['frame']}" if "frame" in r else ""
            print(f"{r['t']:9.4f} s{frame}  +{r['strength_db']:.1f} dB  (level {r['level_db']} dB)")
        print(f"{len(rows)} onsets (hop {result['hop_s'] * 1000:.1f} ms)" + (f"; wrote {args.out}" if args.out else ""))
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    rc.run_main(main)
