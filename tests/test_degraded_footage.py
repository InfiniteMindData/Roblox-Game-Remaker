"""Robustness: the trackers on footage that goes wrong the way real captures do.

Each degraded clip has the same ground truth as the clean demo clips. For every variant the
rule is the same: the result is inside a stated error bound, or the tool warns and its reported
uncertainty covers the truth, or it refuses. A confident number that misses the truth fails.

Bounds below are what the tools achieved when this suite was written (see docs/VERIFICATION.md).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "roblox-game-remaker"
SCRIPTS = SKILL / "scripts"
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
FRAME = 1 / 60
JUMP_ARGS = ["--bbox", "288,288,24,24", "--px-per-unit", "20", "--analyze", "jump"]
RUN_ARGS = ["--bbox", "90,200,20,20", "--anchor-bbox", "400,20,40,40", "--search", "40", "--px-per-unit", "20", "--analyze", "speed"]


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=600)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not installed")
class DegradedFootageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        subprocess.run([sys.executable, str(SKILL / "examples" / "demo" / "make_demo_footage.py"), "--out", str(cls.dir),
                        "--only", "degraded"], check=True, capture_output=True)
        truth = json.loads((cls.dir / "ground_truth.json").read_text())
        cls.jump, cls.run_truth = truth["jump"], truth["run"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def track(self, clip: str, args: list[str], code=0):
        frames = self.dir / ("f_" + clip.split(".")[0])
        if not frames.exists():
            proc = run("extract_frames.py", self.dir / clip, "--out", frames, "--mode", "all")
            self.assertEqual(proc.returncode, 0, proc.stderr)
        out = frames / "track.json"
        proc = run("motion_track.py", frames / "manifest.json", *args, "--out", out)
        self.assertEqual(proc.returncode, code, proc.stderr)
        return (json.loads(out.read_text()) if code == 0 else None), proc

    def assert_honest(self, name, value, truth, unc, k=2.0):
        """Within k reported standard uncertainties (or the stated bound) of the truth."""
        self.assertLessEqual(abs(value - truth), k * unc, f"{name}: {value} vs truth {truth} with stated uncertainty {unc}")

    def assert_jump(self, j, *, apex=0.15, frames=1.0, g_pct=5.0):
        dt = max(j["time_precision_s"], FRAME)
        self.assertAlmostEqual(j["apex_height"], self.jump["apex_height"], delta=apex)
        self.assertAlmostEqual(j["rise_time_s"], self.jump["rise_time_s"], delta=frames * dt)
        self.assertAlmostEqual(j["fall_time_s"], self.jump["fall_time_s"], delta=frames * dt)
        for g in ("g_rise", "g_fall"):
            err = abs(j[g] - self.jump[g])
            ok = err <= g_pct / 100 * self.jump[g] or err <= 2 * j[f"{g}_std"]
            self.assertTrue(ok, f"{g} {j[g]} ± {j[g + '_std']} vs truth {self.jump[g]}")

    def test_h264_heavy_compression(self):
        t, _ = self.track("demo_jump_h264.mp4", JUMP_ARGS)
        self.assert_jump(t["jump"])
        t, _ = self.track("demo_run_h264.mp4", RUN_ARGS)
        s = t["speed"]
        # The anchor drifts in the blocky background: the split-half check must widen the uncertainty.
        self.assert_honest("speed", s["steady_speed"], self.run_truth["steady_speed"], s["steady_speed_std"])
        self.assert_honest("t90", s["t90_s"], self.run_truth["t90_s"], s["t90_uncertainty_s"])
        self.assertTrue(t["reliable"])

    def test_destroyed_background_fails_or_warns(self):
        frames = self.dir / "f_demo_run_h264_crf40"
        run("extract_frames.py", self.dir / "demo_run_h264_crf40.mp4", "--out", frames, "--mode", "all")
        proc = run("motion_track.py", frames / "manifest.json", *RUN_ARGS, "--out", frames / "track.json")
        if proc.returncode == 0:
            t = json.loads((frames / "track.json").read_text())
            s = t["speed"]
            self.assertTrue(t["warnings"] or s["notes"] or t["low_score_samples"], "a result on destroyed footage must warn")
            self.assert_honest("speed", s["steady_speed"], self.run_truth["steady_speed"], s["steady_speed_std"])
        else:
            self.assertIn(proc.returncode, (1, 2))
            self.assertIn("error:", proc.stderr)

    def test_motion_blur(self):
        t, proc = self.track("demo_jump_blur.mkv", JUMP_ARGS)
        self.assertGreater(t["low_score_samples"], 0)
        self.assertIn("low match scores", proc.stderr)
        self.assert_jump(t["jump"], g_pct=8.0)
        t, _ = self.track("demo_run_blur.mkv", RUN_ARGS)
        self.assertGreater(t["low_score_samples"], 0)
        self.assertAlmostEqual(t["speed"]["steady_speed"], self.run_truth["steady_speed"], delta=0.3)
        self.assertAlmostEqual(t["speed"]["t90_s"], self.run_truth["t90_s"], delta=FRAME)

    def test_30fps_content_in_a_60fps_file(self):
        probe = json.loads(run("probe_video.py", self.dir / "demo_jump_30in60.mkv", "--dupes", "--json").stdout)
        self.assertAlmostEqual(probe["effective_fps"], 30, delta=2)
        t, proc = self.track("demo_jump_30in60.mkv", JUMP_ARGS)
        self.assertAlmostEqual(t["content_fps"], 30, delta=2.5)
        self.assertIn("repeat the previous position", proc.stderr)
        j = t["jump"]
        self.assertGreater(j["time_precision_s"], 1 / 32)  # honest: one 30 fps frame, not one 60 fps frame
        self.assert_jump(j)

    def test_variable_frame_rate(self):
        probe = json.loads(run("probe_video.py", self.dir / "demo_jump_vfr.mkv", "--json").stdout)
        self.assertTrue(probe["vfr"])
        t, _ = self.track("demo_jump_vfr.mkv", JUMP_ARGS)
        self.assert_jump(t["jump"], frames=0.6, g_pct=3.0)

    def test_hud_over_the_subject(self):
        t, proc = self.track("demo_run_hud.mkv", RUN_ARGS)
        self.assertGreater(t["excluded_samples"], 0)
        self.assertTrue(any(s.get("excluded") for s in t["samples"]))
        self.assertIn("left out of the analysis", proc.stderr)
        self.assertAlmostEqual(t["speed"]["steady_speed"], self.run_truth["steady_speed"], delta=0.3)
        self.assertAlmostEqual(t["speed"]["t90_s"], self.run_truth["t90_s"], delta=FRAME)
        # find_mover must not offer the screen-fixed HUD as the mover (camera compensation makes it look like one).
        fm = json.loads(run("find_mover.py", self.dir / "f_demo_run_hud" / "manifest.json", "--json").stdout)
        x, y, w, h = fm["candidates"][0]["bbox"]
        self.assertTrue(80 <= x <= 100 and 190 <= y <= 210, fm["candidates"][0])
        self.assertTrue(fm["screen_fixed_regions"])


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not installed")
class CleanFootageRateTests(unittest.TestCase):
    def test_still_stretches_are_not_mistaken_for_a_low_frame_rate(self):
        """Before 1.2.0 probe_video reported the clean 60 fps jump as ~31 fps content."""
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, str(SKILL / "examples" / "demo" / "make_demo_footage.py"), "--out", tmp, "--only", "jump"],
                           check=True, capture_output=True)
            probe = json.loads(run("probe_video.py", Path(tmp) / "demo_jump.mkv", "--dupes", "--json").stdout)
            self.assertGreater(probe["effective_fps"], 55)
            self.assertGreater(probe["dupes"]["static_pairs"], 20)


class LedgerReliabilityTests(unittest.TestCase):
    def test_unreliable_tracks_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            run("breakdown_init.py", d, "--game", "T")
            ev = run("ledger.py", "add-evidence", d / "remake", "--type", "video", "--title", "x", "--source", "x.mp4",
                     "--analysis", "track").stdout.strip()
            track = {"tool": "motion_track", "unit": "studs", "px_per_unit": 20, "reliable": False, "warnings": ["UNRELIABLE: 40% lost"],
                     "samples": [{"index": i} for i in range(10)],
                     "speed": {"steady_speed": 19, "steady_speed_std": 0.1, "t90_s": 0.2, "linear_ramp": {"time_to_full_s": 0.22},
                               "exponential": {"tau_s": 0.1}, "preferred_model": "linear_ramp", "time_precision_s": FRAME}}
            (d / "t.json").write_text(json.dumps(track))
            proc = run("ledger.py", "import", d / "remake", d / "t.json", "--evidence", ev)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("unreliable", proc.stderr)


if __name__ == "__main__":
    unittest.main()
