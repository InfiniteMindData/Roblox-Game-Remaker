#!/usr/bin/env python3
"""Describe a sound in a clip segment, and score a replacement sound against the reference.

Features (numpy FFT; audio decoded to mono by ffmpeg, through audio_onsets.decode):
  duration        active length: from the onset (refined to the sample) until a 2 ms running
                  RMS stays below max(peak - 40 dB, noise floor + 10 dB)
  envelope        RMS loudness in dBFS per hop (default 5.8 ms at 22050 Hz)
  level           RMS level over the active part, and the peak, in dBFS
  dominant        strongest frequency per frame (parabolic peak interpolation), its median over
                  the active part, and its spread in cents
  centroid        power-weighted spectral centroid per frame (bins within 60 dB of the frame's
                  peak) and its energy-weighted mean over the loud part (brightness)

Subcommands:
  analyze MEDIA [--start s --end s]             one segment: features, plus ledger measurements
  compare REF REPLACEMENT [--ref-start ...]      align both on their onsets and report:
      level_db      replacement minus reference RMS level
      duration      replacement / reference active length
      envelope_db   RMS difference of the level-matched envelopes, each stretched to the same
                    length (attack and decay shape; length is judged by duration)
      pitch_cents   median dominant-frequency difference
      centroid      replacement / reference brightness
    with a pass/fail per feature against tolerances, and hints in Roblox terms. Exit 1 when a
    tolerance is exceeded.

The replacement must be an original or licensed sound (references/rights-and-policy.md): this
tool tunes it to match timing, loudness and pitch; it never copies the reference.

Examples:
  python audio_compare.py analyze clip.mp4 --start 12.40 --end 12.90 --out remake/audio/jump-ref.json
  python audio_compare.py compare clip.mp4 remake/audio/jump-new.wav --ref-start 12.40 --ref-end 12.90 --plot remake/audio/jump.png
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402
from audio_onsets import decode  # noqa: E402

TOOL = "audio_compare"
SCHEMA = 1
DEFAULT_TOL = {"level_db": 1.5, "duration_pct": 10.0, "envelope_db": 3.0, "pitch_cents": 50.0, "centroid_pct": 15.0}


def features(x, rate: int, win: int, hop: int) -> dict:
    np = rc.require_numpy()
    ewin = min(win, 4 * hop)  # short window for the loudness envelope; long window for frequencies
    if len(x) < win + hop:
        rc.fail("the segment is too short to analyze; widen --start/--end", rc.EXIT_FAIL)
    n = 1 + (len(x) - ewin) // hop
    centers = np.arange(n) * hop + ewin // 2
    idx = np.arange(ewin)[None, :] + hop * np.arange(n)[:, None]
    rms = np.sqrt((x[idx] ** 2).mean(axis=1))
    env = 20 * np.log10(np.maximum(rms, 1e-10))
    peak_db = float(env.max())
    floor_db = float(np.percentile(env, 10))
    thr = max(peak_db - 40.0, floor_db + 10.0)
    active = np.nonzero(env > thr)[0]
    if len(active) == 0 or peak_db - floor_db < 10:
        rc.fail("no sound stands out from the background in this segment (less than 10 dB above the floor)", rc.EXIT_FAIL)
    a0, a1 = int(active[0]), int(active[-1])
    # Onset to the sample, as audio_onsets does: the first rise a quarter of the way from floor to peak.
    smooth = max(1, int(rate * 0.001))
    s0, s1 = max(0, a0 * hop - win), min(len(x), a0 * hop + 2 * win)
    amp = np.convolve(np.abs(x[s0:s1]), np.ones(smooth) / smooth, mode="same")
    q = max(1, len(amp) // 4)
    fl, pk = float(np.median(amp[:q])), float(amp.max())
    rise = np.nonzero(amp >= fl + 0.25 * (pk - fl))[0]
    onset = (s0 + int(rise[0])) / rate if len(rise) else centers[a0] / rate
    # End to the sample: the last point where a 2 ms running RMS is above the threshold.
    k2 = max(1, int(rate * 0.002))
    e0, e1 = max(0, int(centers[a1]) - ewin), min(len(x), int(centers[a1]) + ewin)
    run_rms = np.sqrt(np.convolve(x[e0:e1] ** 2, np.ones(k2) / k2, mode="same"))
    above = np.nonzero(20 * np.log10(np.maximum(run_rms, 1e-10)) > thr)[0]
    end = (e0 + int(above[-1])) / rate if len(above) else (centers[a1] + ewin / 2) / rate
    # Spectra on the long window, centred on the same instants as the envelope frames.
    pad = np.pad(x, (win // 2, win // 2))
    sel = np.arange(a0, a1 + 1)
    sidx = np.arange(win)[None, :] + centers[sel][:, None]
    window = np.hanning(win)
    spec = np.abs(np.fft.rfft(pad[sidx] * window[None, :], axis=1))
    freqs = np.fft.rfftfreq(win, 1 / rate)
    spec[:, freqs < 20] = 0
    mag = spec + 1e-12
    k = np.clip(np.argmax(mag, axis=1), 1, mag.shape[1] - 2)
    rows = np.arange(len(k))
    la, lb, lc = np.log(mag[rows, k - 1]), np.log(mag[rows, k]), np.log(mag[rows, k + 1])
    den = la - 2 * lb + lc
    off = np.where(np.abs(den) > 1e-12, 0.5 * (la - lc) / den, 0.0)
    dom = (k + np.clip(off, -0.5, 0.5)) * rate / win
    # Brightness: power-weighted centroid of the bins within 60 dB of each frame's peak, so the
    # broadband noise floor does not pull it up.
    power = spec ** 2
    power[power < power.max(axis=1, keepdims=True) * 1e-6] = 0
    cent = (power * freqs[None, :]).sum(axis=1) / np.maximum(power.sum(axis=1), 1e-30)
    energy = rms[a0:a1 + 1] ** 2
    seg = x[int(onset * rate):max(int(onset * rate) + 1, int(end * rate))]
    level = 10 * math.log10(max(float((seg ** 2).mean()), 1e-20))  # RMS over exactly the active samples
    voiced = env[a0:a1 + 1] > peak_db - 20  # pitch and brightness from the loud part
    dom = np.where(voiced, dom, np.nan)
    dom_v = dom[voiced] if voiced.any() else np.nan_to_num(dom)
    med = float(np.median(dom_v))
    spread = float(np.median(np.abs(1200 * np.log2(np.maximum(dom_v, 1e-6) / med)))) if med > 0 else 0.0
    w_e = energy * voiced
    return {
        "rate": rate, "hop_s": hop / rate, "window_s": win / rate, "envelope_window_s": ewin / rate,
        "onset_s": onset, "end_s": end, "duration_s": end - onset,
        "peak_dbfs": peak_db, "level_dbfs": level, "floor_dbfs": floor_db, "threshold_dbfs": thr,
        "dominant_hz_median": med, "dominant_spread_cents": spread,
        "centroid_hz": float((cent * w_e).sum() / max(float(w_e.sum()), 1e-30)),
        "_env": env, "_t": centers / rate, "_active": (a0, a1), "_dom": dom, "_cent": cent,
    }


def public(f: dict, offset: float) -> dict:
    out = {k: (round(v + offset, 5) if k in ("onset_s", "end_s") else round(v, 5) if isinstance(v, float) else v)
           for k, v in f.items() if not k.startswith("_")}
    a0, a1 = f["_active"]
    out["envelope_dbfs"] = [round(float(v), 2) for v in f["_env"][a0:a1 + 1]]
    out["dominant_hz"] = [None if v != v else round(float(v), 2) for v in f["_dom"]]
    out["track_t_s"] = [round(float(v) + offset, 5) for v in f["_t"][a0:a1 + 1]]
    out["centroid_track_hz"] = [round(float(v), 1) for v in f["_cent"]]
    return out


def load(path: Path, start, end, rate, win, hop):
    if not path.is_file():
        rc.fail(f"file not found: {path}")
    if start is not None and end is not None and end <= start:
        rc.fail("--end must be after --start")
    return features(decode(path, rate, start, end), rate, win, hop)


def cmd_analyze(args) -> dict:
    f = load(args.media, args.start, args.end, args.rate, args.window, args.hop)
    off = args.start or 0.0
    hop = f["hop_s"]
    method = (f"audio_compare analyze {args.media.name} [{off:.3f}s..{args.end if args.end is not None else 'end'}]: mono {args.rate} Hz, "
              f"{args.window}-sample Hann window, hop {hop * 1000:.1f} ms; active = above max(peak - 40 dB, floor + 10 dB)")
    ms = [
        {"metric": "audio_duration", "what": f"sound duration ({args.media.name} at {f['onset_s'] + off:.3f} s)",
         "value": round(f["duration_s"], 4), "uncertainty": round(hop, 4), "unit": "s", "method": method},
        {"metric": "audio_dominant_hz", "what": "dominant frequency (median over the loud part)", "value": round(f["dominant_hz_median"], 2),
         "uncertainty": round(max(f["dominant_hz_median"] * (2 ** (f["dominant_spread_cents"] / 1200) - 1), args.rate / args.window / 10), 2),
         "unit": "Hz", "method": method},
        {"metric": "audio_level_dbfs", "what": "RMS level over the active part (relative to this recording's mix)",
         "value": round(f["level_dbfs"], 2), "uncertainty": 0.5, "unit": "dBFS", "method": method},
    ]
    return {"mode": "analyze", "media": str(args.media), "segment": [args.start, args.end], "features": public(f, off),
            "measurements": ms, "_f": [f]}


def cmd_compare(args) -> dict:
    np = rc.require_numpy()
    ref = load(args.reference, args.ref_start, args.ref_end, args.rate, args.window, args.hop)
    rep = load(args.replacement, args.rep_start, args.rep_end, args.rate, args.window, args.hop)
    tol = dict(DEFAULT_TOL)
    for k in tol:
        v = getattr(args, f"tol_{k}")
        if v is not None:
            tol[k] = v
    level = rep["level_dbfs"] - ref["level_dbfs"]
    ratio = rep["duration_s"] / ref["duration_s"]
    cents = 1200 * math.log2(rep["dominant_hz_median"] / ref["dominant_hz_median"]) if ref["dominant_hz_median"] > 0 and rep["dominant_hz_median"] > 0 else 0.0
    cratio = rep["centroid_hz"] / ref["centroid_hz"] if ref["centroid_hz"] > 0 else 1.0
    # Envelope shape: each active span stretched to the same length (duration is judged separately),
    # levels matched, then the rms dB difference.
    u = np.linspace(0, 1, 101)
    e_ref = np.interp(ref["onset_s"] + u * ref["duration_s"], ref["_t"], ref["_env"])
    e_rep = np.interp(rep["onset_s"] + u * rep["duration_s"], rep["_t"], rep["_env"]) - level
    floor = max(ref["peak_dbfs"] - 60, ref["floor_dbfs"])
    shape = float(np.sqrt(((np.maximum(e_rep, floor) - np.maximum(e_ref, floor)) ** 2).mean()))
    hop = ref["hop_s"]
    span = max(ref["duration_s"], rep["duration_s"])
    grid = np.arange(-0.05, span + 0.05, hop)
    p_ref = np.interp(grid + ref["onset_s"], ref["_t"], ref["_env"])
    p_rep = np.interp(grid + rep["onset_s"], rep["_t"], rep["_env"])
    checks = {
        "level_db": (round(level, 3), abs(level) <= tol["level_db"]),
        "duration_ratio": (round(ratio, 4), abs(ratio - 1) * 100 <= tol["duration_pct"]),
        "envelope_db": (round(shape, 3), shape <= tol["envelope_db"]),
        "pitch_cents": (round(cents, 2), abs(cents) <= tol["pitch_cents"]),
        "centroid_ratio": (round(cratio, 4), abs(cratio - 1) * 100 <= tol["centroid_pct"]),
    }
    failures = [k for k, (_, ok) in checks.items() if not ok]
    hints = []
    speed = 2 ** (-cents / 1200)
    if "pitch_cents" in failures or "duration_ratio" in failures:
        # Played s times faster, a sound is s times higher and 1/s as long: the correcting speed
        # factor 2^(-cents/1200) then equals the duration ratio.
        if abs(math.log(ratio) - math.log(speed)) < 0.05 and abs(cents) > tol["pitch_cents"] / 2:
            hints.append(f"pitch and length are off together (as a speed change would be): PlaybackSpeed x{speed:.3f} fixes both")
        else:
            if "pitch_cents" in failures:
                hints.append(f"pitch is {cents:+.0f} cents off: AudioPitchShifter.Pitch x{speed:.3f} (0.5 to 2) shifts pitch without "
                             f"changing length; PlaybackSpeed x{speed:.3f} would also change the length")
            if "duration_ratio" in failures:
                hints.append(f"the replacement lasts {ratio:.2f}x as long: trim or re-edit it (PlaybackRegion can cut the tail); "
                             "speeding it up would also raise the pitch")
    if "level_db" in failures:
        hints.append(f"the replacement is {level:+.1f} dB: AudioPlayer.Volume x{10 ** (-level / 20):.3f} (a multiplier on the stream); "
                     "for Sound.Volume, change it and re-measure")
    if "envelope_db" in failures:
        hints.append(f"the loudness shape differs by {shape:.1f} dB rms after level matching: edit the attack and decay of the "
                     "replacement (look at the plot), not the volume")
    if "centroid_ratio" in failures:
        hints.append(f"the replacement is {'brighter' if cratio > 1 else 'duller'} (centroid x{cratio:.2f}): an AudioEqualizer "
                     f"{'cut' if cratio > 1 else 'boost'} in the high band moves it toward the reference")
    score = 100 * math.exp(-sum((abs(v) / t) ** 2 for v, t in (
        (level, tol["level_db"]), ((ratio - 1) * 100, tol["duration_pct"]), (shape, tol["envelope_db"]),
        (cents, tol["pitch_cents"]), ((cratio - 1) * 100, tol["centroid_pct"]))) / 5)
    return {"mode": "compare", "reference": str(args.reference), "replacement": str(args.replacement),
            "segments": {"reference": [args.ref_start, args.ref_end], "replacement": [args.rep_start, args.rep_end]},
            "reference_features": public(ref, args.ref_start or 0.0), "replacement_features": public(rep, args.rep_start or 0.0),
            "comparison": {k: v for k, (v, _) in checks.items()}, "pass": {k: ok for k, (_, ok) in checks.items()},
            "tolerances": tol, "failures": failures, "score": round(score, 1), "hints": hints,
            "method": (f"audio_compare: onsets aligned (refined to the sample); levels as RMS over the active parts; envelope shape "
                       f"as rms dB difference after level matching (floor peak - 60 dB); pitch from median dominant frequency; "
                       f"score = 100 exp(-mean squared tolerance ratio)"),
            "_f": [ref, rep], "_grid": (grid, p_ref, p_rep)}


def plot(rep: dict, path: Path) -> None:
    np = rc.require_numpy()
    if rep["mode"] == "compare":
        grid, a, b = rep["_grid"]
        r, p = rep["_f"]
        panels = [{"title": "loudness since onset (dBFS)", "xlabel": "s since onset", "ylabel": "dBFS",
                   "series": [{"label": "reference", "x": grid.tolist(), "y": a.tolist()},
                              {"label": "replacement", "x": grid.tolist(), "y": b.tolist()}]},
                  {"title": "dominant frequency (Hz)", "xlabel": "s since onset", "ylabel": "Hz",
                   "series": [{"label": "reference", "x": (r["_t"][r["_active"][0]:r["_active"][1] + 1] - r["onset_s"]).tolist(),
                               "y": r["_dom"].tolist(), "dots": True},
                              {"label": "replacement", "x": (p["_t"][p["_active"][0]:p["_active"][1] + 1] - p["onset_s"]).tolist(),
                               "y": p["_dom"].tolist(), "dots": True}]}]
        title = f"audio_compare: score {rep['score']}; " + (", ".join(rep["failures"]) or "all within tolerance")
    else:
        f = rep["_f"][0]
        a0, a1 = f["_active"]
        t = f["_t"] - f["onset_s"]
        panels = [{"title": "loudness (dBFS)", "xlabel": "s since onset", "ylabel": "dBFS", "series": [{"label": "envelope", "x": t.tolist(), "y": f["_env"].tolist()}]},
                  {"title": "dominant frequency and centroid (Hz)", "xlabel": "s since onset", "ylabel": "Hz",
                   "series": [{"label": "dominant", "x": t[a0:a1 + 1].tolist(), "y": f["_dom"].tolist(), "dots": True},
                              {"label": "centroid", "x": t[a0:a1 + 1].tolist(), "y": np.asarray(f["_cent"]).tolist()}]}]
        title = f"audio_compare analyze: {Path(rep['media']).name}"
    rc.line_plot(path, panels, title=title)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--rate", type=int, default=22050, help="analysis sample rate (default 22050)")
        p.add_argument("--window", type=int, default=2048, help="FFT window in samples (default 2048)")
        p.add_argument("--hop", type=int, default=128, help="hop in samples (default 128)")
        p.add_argument("--plot", type=Path, help="write a PNG of the envelope and frequencies")
        p.add_argument("--out", type=Path)
        p.add_argument("--json", action="store_true")

    a = sub.add_parser("analyze", help="features of one segment")
    a.add_argument("media", type=Path)
    a.add_argument("--start", type=float)
    a.add_argument("--end", type=float)
    common(a)
    c = sub.add_parser("compare", help="score a replacement against the reference segment")
    c.add_argument("reference", type=Path)
    c.add_argument("replacement", type=Path)
    for side in ("ref", "rep"):
        c.add_argument(f"--{side}-start", type=float)
        c.add_argument(f"--{side}-end", type=float)
    c.add_argument("--tol-level-db", type=float, help=f"default {DEFAULT_TOL['level_db']}")
    c.add_argument("--tol-duration-pct", type=float, help=f"default {DEFAULT_TOL['duration_pct']}")
    c.add_argument("--tol-envelope-db", type=float, help=f"default {DEFAULT_TOL['envelope_db']}")
    c.add_argument("--tol-pitch-cents", type=float, help=f"default {DEFAULT_TOL['pitch_cents']}")
    c.add_argument("--tol-centroid-pct", type=float, help=f"default {DEFAULT_TOL['centroid_pct']}")
    common(c)
    args = ap.parse_args()
    if args.hop < 1 or args.window < 64 or args.rate < 4000:
        rc.fail("--hop must be >= 1, --window >= 64 and --rate >= 4000")

    rep = cmd_analyze(args) if args.cmd == "analyze" else cmd_compare(args)
    rep = {"tool": TOOL, "schema": SCHEMA, **rep}
    if args.plot:
        plot(rep, args.plot)
        rep["plot"] = str(args.plot)
    for k in ("_f", "_grid"):
        rep.pop(k, None)
    if args.out:
        rc.write_json(args.out, rep)
    if args.json:
        print(rc.dump_json(rep))
    elif rep["mode"] == "analyze":
        f = rep["features"]
        print(f"onset {f['onset_s']} s, duration {f['duration_s']} s (± {f['hop_s']:.4f})")
        print(f"level {f['level_dbfs']} dBFS rms, peak {f['peak_dbfs']} dBFS, floor {f['floor_dbfs']} dBFS")
        print(f"dominant {f['dominant_hz_median']} Hz (spread {f['dominant_spread_cents']} cents), centroid {f['centroid_hz']} Hz")
    else:
        for k, v in rep["comparison"].items():
            print(f"{'PASS' if rep['pass'][k] else 'FAIL'}  {k:<15} {v}")
        print(f"score {rep['score']} / 100")
        for h in rep["hints"]:
            print(f"hint: {h}")
        print("result: " + ("FAIL - " + ", ".join(rep["failures"]) if rep["failures"] else "pass"))
    if not args.json:
        for p in (args.out, getattr(args, "plot", None)):
            if p:
                print(f"wrote {p}")
    return rc.EXIT_FAIL if rep.get("failures") else rc.EXIT_OK


if __name__ == "__main__":
    rc.run_main(main)
