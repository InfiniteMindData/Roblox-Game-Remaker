"""Camera motion and tracking robustness: the cases real gameplay footage has.

Each clip comes from make_demo_footage.py --only camera with exact ground truth. Before the camera model these went
wrong silently: a sprint FOV kick read 12% fast with a fake 0.5 s ramp and "reliable" (17.9 studs/s
for a true 16), a follow camera gave "no motion detected", a flat pillar scored 7.8 on a 0-1 scale and
the track stuck to it, a look-alike crossing flipped the track, find_mover called the followed player
HUD. The rule for every case: the result is right within its stated uncertainty, or it is marked
unreliable with the sample where it went wrong. A confident number that misses the truth fails.
"""

from __future__ import annotations

import json
import math
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

sys.path.insert(0, str(SCRIPTS))
import motion_track as mt  # noqa: E402


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=600)


def iou(a, b) -> float:
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = max(0, min(ax1, bx1) - max(a[0], b[0])), max(0, min(ay1, by1) - max(a[1], b[1]))
    inter = iw * ih
    return inter / float(a[2] * a[3] + b[2] * b[3] - inter)


class MatchScoreTests(unittest.TestCase):
    def test_flat_window_scores_zero_and_scores_stay_in_range(self):
        """Before the fix the variance floor of 1e-9 scored a flat wall 21.4 here (7.83 on the audit's frames)."""
        import numpy as np

        rng = np.random.default_rng(0)
        tmpl = (rng.random((80, 40)) * 120 + 60).astype(np.float32)
        search = np.full((200, 200), 90.0, np.float32)
        search[:, :60] = rng.random((200, 60)) * 120 + 60
        m = mt.ncc_map(search, tmpl)
        self.assertLessEqual(float(m.max()), 1.0)
        self.assertGreaterEqual(float(m.min()), -1.0)
        self.assertEqual(float(np.abs(m[:, 70:]).max()), 0.0)  # windows entirely on the flat area
        exact = search[10:90, 0:40]
        self.assertAlmostEqual(float(mt.ncc_map(exact, exact)[0, 0]), 1.0, places=6)


class CameraModelTests(unittest.TestCase):
    """The whole-frame model on frames warped by a known similarity, with a mover and a HUD in view."""

    def test_recovers_shift_zoom_and_roll_with_a_mover_and_hud(self):
        import numpy as np
        from PIL import Image

        rng = np.random.default_rng(3)
        world = Image.fromarray(rng.integers(0, 255, (120, 200)).astype(np.uint8)).resize((1600, 960), Image.BICUBIC)
        W, H = 480, 270

        def truth(i):  # first frame -> frame i: zoom 1 -> 1.15, roll 0 -> 2.5 deg, pan
            z, r = 1 + 0.15 * i / 30, math.radians(2.5 * i / 30)
            return (z * math.cos(r), z * math.sin(r), -4.0 * i, 1.5 * i)

        def frame(i):
            S = mt.sim_inverse(truth(i))  # screen of frame i -> screen of frame 0
            base = (560.0, 340.0)  # where the first frame's screen sits in the world
            a, b, tx, ty = S
            img = world.transform((W, H), Image.AFFINE, (a, -b, tx + base[0], b, a, ty + base[1]), resample=Image.BILINEAR)
            arr = np.asarray(img, dtype=np.float32).copy()
            arr[110:150, 200 + 3 * i:220 + 3 * i] = 240.0 * ((np.arange(20) // 4) % 2)  # a striped mover
            arr[5:45, 5:125] = (rng.random((40, 120)) * 200).astype(np.float32) if i == 0 else hud  # static HUD
            return arr

        f0 = frame(0)
        hud = f0[5:45, 5:125].copy()
        cam = mt.CameraMotion(f0)
        for i in range(1, 31):
            info = cam.update(frame(i), [(200 + 3 * i - 10, 100, 40, 60)])
        self.assertTrue(info["ok"] and info["chain_ok"])
        S, T = info["S"], truth(30)
        self.assertAlmostEqual(mt.sim_scale(S), mt.sim_scale(T), delta=0.003)
        self.assertAlmostEqual(mt.sim_roll_deg(S), mt.sim_roll_deg(T), delta=0.15)
        for px, py in ((W / 2, H / 2), (60, 200), (420, 60)):
            got, want = mt.sim_apply(S, px, py), mt.sim_apply(T, px, py)
            self.assertLess(math.hypot(got[0] - want[0], got[1] - want[1]), 0.6, (px, py, got, want))

    def test_robust_similarity_ignores_outliers(self):
        import numpy as np

        rng = np.random.default_rng(1)
        src = rng.random((40, 2)) * 400
        T = (1.08 * math.cos(0.03), 1.08 * math.sin(0.03), 12.0, -7.0)
        dst = np.array([mt.sim_apply(T, x, y) for x, y in src]) + rng.normal(0, 0.1, (40, 2))
        dst[:14] += rng.random((14, 2)) * 60 + 5  # 35% outliers (subject, HUD, other movers)
        S, inl, rms = mt.robust_similarity(src, dst, thr=1.0)
        self.assertEqual(int(inl[14:].sum()), 26)
        self.assertEqual(int(inl[:14].sum()), 0)
        for a, b in zip(S, T):
            self.assertAlmostEqual(a, b, delta=0.2 if abs(b) > 1 else 0.002)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not installed")
class HardFootageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        subprocess.run([sys.executable, str(SKILL / "examples" / "demo" / "make_demo_footage.py"), "--out", str(cls.dir),
                        "--only", "camera"], check=True, capture_output=True)
        cls.truth = json.loads((cls.dir / "ground_truth.json").read_text(encoding="utf-8"))["camera"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def frames(self, clip: str) -> Path:
        frames = self.dir / ("f_" + clip.split(".")[0])
        if not frames.exists():
            proc = run("extract_frames.py", self.dir / clip, "--out", frames, "--mode", "all")
            self.assertEqual(proc.returncode, 0, proc.stderr)
        return frames / "manifest.json"

    def track(self, clip: str, *args, ppu=None, code=0):
        t = self.truth["clips"][clip]
        out = self.dir / f"t_{clip}_{len(args)}.json"
        ppu = ppu or t.get("px_per_unit", self.truth["px_per_unit"])
        proc = run("motion_track.py", self.frames(clip), "--bbox", ",".join(map(str, t["bbox"])), "--px-per-unit", ppu,
                   "--analyze", "speed", *args, "--out", out)
        self.assertEqual(proc.returncode, code, proc.stderr)
        return json.loads(out.read_text(encoding="utf-8")), proc

    def assert_speed(self, res, truth, delta=0.15):
        s = res["speed"]
        self.assertTrue(res["reliable"], res["warnings"])
        self.assertAlmostEqual(s["steady_speed"], truth, delta=delta)
        self.assertLessEqual(abs(s["steady_speed"] - truth), max(delta, 3 * s["steady_speed_std"]))
        # Instant start: no ramp may be invented (the FOV kick used to fake a 0.55 s one).
        self.assertLessEqual(s["t90_s"], 3 * s["time_precision_s"], s)

    def assert_on_path(self, res, clip, tol_units):
        """Every sample the analysis used sits on the true path (u = speed x time since the start)."""
        t = self.truth["clips"][clip]
        for s in res["samples"]:
            if s.get("excluded") or s.get("repeat"):
                continue
            want = t["speed"] * max(0.0, s["t"] - t["start_s"])
            self.assertLessEqual(abs(s["u"] - want), tol_units, f"sample {s['sample']}: u {s['u']} vs truth {want}")

    def test_fov_kick_is_divided_out(self):
        """Before the camera model: 17.85 studs/s for a true 16, t90 0.47 s, reliable, no warning."""
        res, _ = self.track("cam_zoom.mp4")
        self.assert_speed(res, 16.0)
        cam = res["camera"]
        self.assertTrue(cam["applied"])
        self.assertAlmostEqual(cam["zoom_range"][1], 1.12, delta=0.01)
        self.assertTrue(any("zoomed 12%" in w for w in res["warnings"]), res["warnings"])
        res, _ = self.track("cam_zoom.mp4", "--anchor-bbox", "400,120,40,40")
        self.assert_speed(res, 16.0)
        # An anchor shift alone cannot remove a zoom: it must say so and refuse "reliable".
        res, proc = self.track("cam_zoom.mp4", "--anchor-bbox", "400,120,40,40", "--camera", "none")
        self.assertFalse(res["reliable"])
        self.assertIn("cannot remove", proc.stderr)

    def test_follow_camera_and_anchor_hand_off(self):
        """Before the camera model: "no motion detected" without an anchor; with one, the track was voided once it left."""
        t = self.truth["clips"]["cam_follow.mp4"]
        res, _ = self.track("cam_follow.mp4")
        self.assert_speed(res, 16.0, delta=0.1)
        res, proc = self.track("cam_follow.mp4", "--anchor-bbox", ",".join(map(str, t["anchor_bbox"])))
        self.assert_speed(res, 16.0, delta=0.1)
        hs = res["camera"]["anchor_handoff_sample"]
        self.assertIsNotNone(hs)
        self.assertAlmostEqual(res["samples"][hs]["t"], t["anchor_leaves_view_s"], delta=0.1)
        self.assertFalse(any(s.get("excluded") == "anchor lost" for s in res["samples"]))
        self.assertIn("whole-frame camera model carries", proc.stderr)

    def test_find_mover_reports_the_followed_player(self):
        """Before the camera model: "no moving object found" and the player listed as HUD."""
        for clip in ("cam_follow.mp4", "cam_zoom.mp4", "cam_pan_zoom.mp4"):
            fm = json.loads(run("find_mover.py", self.frames(clip), "--json").stdout)
            top = fm["candidates"][0]
            self.assertGreaterEqual(iou(top["bbox"], self.truth["clips"][clip]["bbox"]), 0.5, (clip, fm["candidates"]))
            self.assertTrue(fm["camera_moves"])
        fm = json.loads(run("find_mover.py", self.frames("cam_follow.mp4"), "--json").stdout)
        self.assertEqual(fm["candidates"][0]["kind"], "probable_player_camera_follows")
        z = json.loads(run("find_mover.py", self.frames("cam_zoom.mp4"), "--json").stdout)["camera_zoom_range"]
        self.assertAlmostEqual(z[1], 1.12, delta=0.01)

    def test_pan_zoom_and_roll(self):
        res, _ = self.track("cam_pan_zoom.mp4")
        self.assert_speed(res, 16.0)
        cam = res["camera"]
        self.assertAlmostEqual(cam["zoom_range"][1], 1.35, delta=0.01)
        self.assertAlmostEqual(cam["roll_range_deg"][1], 3.0, delta=0.3)

    def test_flat_occluder(self):
        """Before the camera model: the track jumped onto the flat pillar (score 7.8) and reported 0 studs/s, reliable."""
        res, _ = self.track("cam_occluder.mp4")
        self.assertTrue(all(-1.0 <= s["score"] <= 1.0 for s in res["samples"]))
        self.assert_on_path(res, "cam_occluder.mp4", 0.6)
        s = res["speed"]
        if res["reliable"]:
            self.assertLessEqual(abs(s["steady_speed"] - 16.0), max(0.2, 3 * s["steady_speed_std"]))
        else:
            self.assertIn("first_lost_sample", res)

    def test_lookalike_crossing(self):
        """Before the camera model: the track followed the look-alike after the crossing, with no warning."""
        t = self.truth["clips"]["cam_lookalike.mp4"]
        res, _ = self.track("cam_lookalike.mp4")
        last = res["samples"][-1]
        if res["reliable"]:
            self.assertAlmostEqual(last["x_px"], t["end_x_px"], delta=3.0)
            self.assertLessEqual(abs(res["speed"]["steady_speed"] - 10.0), max(0.3, 3 * res["speed"]["steady_speed_std"]))
            self.assert_on_path(res, "cam_lookalike.mp4", 0.5)
        else:
            self.assertIn("first_lost_sample", res)

    def test_small_subject(self):
        """Before the camera model: the track jumped onto background texture and no speed could be fitted."""
        res, _ = self.track("cam_small.mp4")
        self.assert_on_path(res, "cam_small.mp4", 2.0)
        s = res["speed"]
        if res["reliable"]:
            self.assertLessEqual(abs(s["steady_speed"] - 16.0), max(0.3, 3 * s["steady_speed_std"]))
        else:
            self.assertIn("first_lost_sample", res)
            self.assertTrue(any("first lost at sample" in w for w in res["warnings"]))

    def test_variable_frame_rate_under_a_moving_camera(self):
        probe = json.loads(run("probe_video.py", self.dir / "cam_vfr.mkv", "--json").stdout)
        self.assertTrue(probe["vfr"])
        res, _ = self.track("cam_vfr.mkv")
        self.assert_speed(res, 16.0)

    @unittest.skipIf(sys.platform == "win32", "resource module is POSIX only")
    def test_frames_are_streamed(self):
        """Peak memory must not grow with the clip (it held every frame: 4.8 GB for 10 s of 1080p60)."""
        manifest = self.frames("cam_follow.mp4")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        short = manifest.parent / "manifest_short.json"
        short.write_text(json.dumps({**data, "frames": data["frames"][:30]}), encoding="utf-8")
        probe = ("import resource, subprocess, sys; subprocess.run(sys.argv[1:], check=True, capture_output=True); "
                 "print(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)")
        peaks = []
        for m in (short, manifest):
            out = subprocess.run([sys.executable, "-c", probe, sys.executable, str(SCRIPTS / "motion_track.py"), str(m),
                                  "--bbox", "250,220,20,40", "--px-per-unit", "10", "--analyze", "speed"],
                                 capture_output=True, text=True, check=True).stdout
            peaks.append(int(out.strip().splitlines()[-1]) / 1024.0)  # MB (Linux reports KB)
        # 120 more 640x360 frames held as float32 would add about 110 MB.
        self.assertLess(peaks[1] - peaks[0], 30.0, peaks)


if __name__ == "__main__":
    unittest.main()
