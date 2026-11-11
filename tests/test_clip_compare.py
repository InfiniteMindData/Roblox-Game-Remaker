"""Tests for clip_compare.py: aligned, resampled comparison of a recreation clip with the reference."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "roblox-game-remaker"
SCRIPTS = SKILL / "scripts"
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=600)


def ramp(t, speed, ramp_s, t0):
    tt = t - t0
    if tt <= 0:
        return 0.0
    return speed * tt * tt / (2 * ramp_s) if tt < ramp_s else speed * (tt - ramp_s / 2)


def jump(t, apex, rise, fall, t0):
    tt = t - t0
    if tt <= 0:
        return 0.0
    if tt <= rise:
        return apex - apex * ((rise - tt) / rise) ** 2
    td = tt - rise
    return max(0.0, apex - apex * (td / fall) ** 2) if td <= fall else 0.0


def write_track(path: Path, fps: float, n: int, along=lambda t: 0.0, up=lambda t: 0.0, unit="studs"):
    samples = [{"sample": i, "index": i, "t": round(i / fps, 6), "x_px": 0, "y_px": 0, "score": 1.0,
                "u": round(along(i / fps), 6), "v": round(up(i / fps), 6)} for i in range(n)]
    path.write_text(json.dumps({"tool": "motion_track", "unit": unit, "samples": samples, "low_score_samples": 0}))
    return path


def write_log(path: Path, fps: float, n: int, along, up, heading_deg=0.0):
    """A MeasurementHarness log: the character runs along a heading in the X-Z plane."""
    hx, hz = math.cos(math.radians(heading_deg)), math.sin(math.radians(heading_deg))
    rows = [[round(i / fps, 4), round(5 + hx * along(i / fps), 4), round(3 + up(i / fps), 4), round(-2 + hz * along(i / fps), 4),
             0, 0, 0, 1, 1.0] for i in range(n)]
    lines = ["REMAKE_MEASURE " + json.dumps({"k": "b", "s": rows[i:i + 30]}) for i in range(0, n, 30)]
    path.write_text("\n".join(f"12:00:00.000  {ln}  -  Client" for ln in lines) + "\n")
    return path


class ClipCompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def compare(self, *args, code=0):
        proc = run("clip_compare.py", *args, "--json")
        self.assertEqual(proc.returncode, code, proc.stderr)
        return json.loads(proc.stdout)

    def test_alignment_errors_and_events_against_analytic_truth(self):
        ref = write_track(self.dir / "ref.json", 60, 90, along=lambda t: ramp(t, 20, 0.25, 0.2))
        rec = write_track(self.dir / "rec.json", 30, 60, along=lambda t: ramp(t, 19, 0.30, 0.7))
        rep = self.compare(ref, rec, "--plot", self.dir / "plot.png")
        self.assertAlmostEqual(rep["reference"]["align_time_s"], 0.2, delta=0.002)
        self.assertAlmostEqual(rep["recreation"]["align_time_s"], 0.7, delta=0.002)
        self.assertEqual(rep["axes"], ["along"])  # neither clip moves vertically
        grid = np.arange(rep["window_s"][0], rep["window_s"][1] + 1e-9, rep["resample_step_s"])
        err = np.array([ramp(t + 0.7, 19, 0.3, 0.7) - ramp(t + 0.2, 20, 0.25, 0.2) for t in grid])
        self.assertLess(abs(rep["position_rms"] - float(np.sqrt((err ** 2).mean()))), rep["floor"])
        self.assertLess(abs(rep["position_max"] - float(np.abs(err).max())), rep["floor"])
        s90 = rep["events"]["speed_90"]
        self.assertAlmostEqual(s90["reference_s"], 0.225, delta=1 / 60)
        self.assertAlmostEqual(s90["offset_s"], 0.27 - 0.225, delta=s90["precision_s"])
        self.assertEqual(rep["status"], "no-tolerance")
        with Image.open(self.dir / "plot.png") as im:
            self.assertEqual(im.width, 960)

    def test_identical_motion_at_different_rates_is_below_the_floor(self):
        ref = write_track(self.dir / "ref.json", 60, 120, along=lambda t: ramp(t, 16, 0.2, 0.3))
        rec = write_log(self.dir / "rec.log", 60, 150, lambda t: ramp(t, 16, 0.2, 0.8), lambda t: 0.0, heading_deg=37)
        rep = self.compare(ref, rec, "--tol-rms", "0.05", "--tol-event", "0.034")
        self.assertLess(rep["position_rms"], rep["floor"] / 4)
        self.assertEqual(rep["status"], "pass")

    def test_jump_events_and_tolerance_exit_codes(self):
        ref = write_track(self.dir / "ref.json", 60, 80, up=lambda t: jump(t, 8, 0.4, 0.283, 0.2))
        rec = write_log(self.dir / "rec.log", 60, 80, lambda t: 0.0, lambda t: jump(t, 7.5, 0.38, 0.3, 0.3))
        rep = self.compare(ref, rec)
        self.assertEqual(rep["axes"], ["up"])
        ev = rep["events"]
        self.assertAlmostEqual(ev["apex"]["reference_s"], 0.4, delta=1 / 60)
        self.assertAlmostEqual(ev["apex"]["offset_s"], -0.02, delta=ev["apex"]["precision_s"])
        self.assertAlmostEqual(ev["landing"]["offset_s"], (0.38 + 0.3) - (0.4 + 0.283), delta=0.03)
        targets = {"clips": {"default": {"position_rms_pct": 1, "event_offset_frames": 2}, "loose": {"position_rms_pct": 20}}}
        (self.dir / "targets.json").write_text(json.dumps(targets))
        failed = self.compare(ref, rec, "--targets", self.dir / "targets.json", code=1)
        self.assertTrue(any("position rms" in f for f in failed["failures"]))
        self.assertAlmostEqual(failed["tolerances"]["position_rms"], 0.08, delta=0.001)  # 1% of 8 studs of travel
        loose = self.compare(ref, rec, "--targets", self.dir / "targets.json", "--clip", "loose")
        self.assertEqual(loose["status"], "pass")
        self.assertEqual(run("clip_compare.py", ref, rec, "--targets", self.dir / "targets.json", "--clip", "nope").returncode, 2)

    def test_frame_alignment_and_ground_track(self):
        ref = write_track(self.dir / "ref.json", 60, 90, along=lambda t: ramp(t, 12, 0.3, 0.25))
        rec = write_track(self.dir / "rec.json", 60, 90, along=lambda t: ramp(t, 12, 0.3, 0.25 + 10 / 60))
        rep = self.compare(ref, rec, "--align", "frames", "--ref-frame", "5", "--rec-frame", "15")
        self.assertLess(rep["position_rms"], 1e-4)
        samples = [{"t": round(i / 60, 6), "index": i, "X": 3 + 0.6 * ramp(i / 60, 12, 0.3, 0.25), "Z": 7 + 0.8 * ramp(i / 60, 12, 0.3, 0.25)}
                   for i in range(90)]
        (self.dir / "ground.json").write_text(json.dumps({"tool": "camera_solve", "unit": "studs", "track": {"samples": samples}}))
        rep2 = self.compare(self.dir / "ground.json", ref)
        # Orientation-independent "along"; a start from rest pins the onset to a fraction of a millisecond.
        self.assertLess(rep2["position_rms"], rep2["floor"] / 20)

    def test_bad_input(self):
        ref = write_track(self.dir / "ref.json", 60, 90, along=lambda t: ramp(t, 20, 0.25, 0.2))
        px = write_track(self.dir / "px.json", 60, 90, along=lambda t: ramp(t, 20, 0.25, 0.2), unit="px")
        proc = run("clip_compare.py", ref, px)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("units differ", proc.stderr)
        self.assertEqual(run("clip_compare.py", ref, self.dir / "missing.json").returncode, 2)
        short = write_track(self.dir / "short.json", 60, 3, along=lambda t: t)
        self.assertEqual(run("clip_compare.py", ref, short).returncode, 2)
        (self.dir / "manifest.json").write_text(json.dumps({"frames": [{"index": i, "pts_time": i / 60, "file": "a.png"} for i in range(6)]}))
        proc = run("clip_compare.py", self.dir / "manifest.json", ref)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--ref-bbox", proc.stderr)
        self.assertEqual(run("clip_compare.py", ref, ref, "--align", "frames").returncode, 2)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not installed")
class ClipCompareFootageTests(unittest.TestCase):
    def test_demo_clip_against_itself_through_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            subprocess.run([sys.executable, str(SKILL / "examples" / "demo" / "make_demo_footage.py"), "--out", str(d), "--only", "jump"],
                           check=True, capture_output=True)
            run("extract_frames.py", d / "demo_jump.mkv", "--out", d / "ref", "--mode", "all")
            run("extract_frames.py", d / "demo_jump.mkv", "--out", d / "rec", "--mode", "range", "--start", "5", "--end", "79")
            proc = run("clip_compare.py", d / "ref" / "manifest.json", d / "rec" / "manifest.json", "--ref-bbox", "288,288,24,24",
                       "--rec-bbox", "288,288,24,24", "--ref-px-per-unit", "20", "--rec-px-per-unit", "20", "--json",
                       "--plot", d / "p.png")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            rep = json.loads(proc.stdout)
            self.assertLess(rep["position_rms"], 0.05)
            self.assertAlmostEqual(rep["events"]["apex"]["offset_s"], 0.0, delta=0.005)


if __name__ == "__main__":
    unittest.main()
