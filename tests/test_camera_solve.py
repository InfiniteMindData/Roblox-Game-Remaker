"""Tests for camera_solve.py: FOV, pitch and height from marks, and ground-plane conversion.

The synthetic camera below projects known world geometry, so every expected value is exact.
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

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "roblox-game-remaker"
SCRIPTS = SKILL / "scripts"
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=600)


def camera(vfov=70.0, pitch=-20.0, yaw=30.0, roll=0.0, height=10.0, w=1920, h=1080):
    """Return project((x, y, z)) -> [px, py] for a pinhole camera at (0, height, 0), world y up."""
    f = (h / 2) / math.tan(math.radians(vfov) / 2)
    p, y, r = (math.radians(v) for v in (pitch, yaw, roll))
    fwd = np.array([math.sin(y) * math.cos(p), math.sin(p), math.cos(y) * math.cos(p)])
    right = np.cross([0.0, 1.0, 0.0], fwd)
    right /= np.linalg.norm(right)
    down = np.cross(right, fwd)
    rr, dd = math.cos(r) * right + math.sin(r) * down, -math.sin(r) * right + math.cos(r) * down
    c = np.array([0.0, height, 0.0])

    def project(point, digits=None):
        d = np.asarray(point, float) - c
        xy = [w / 2 + f * (d @ rr) / (d @ fwd), h / 2 + f * (d @ dd) / (d @ fwd)]
        return [round(v, digits) if digits is not None else v for v in xy]

    return project


def lines(project, pairs, digits=None):
    return ";".join(",".join(f"{v:.4f}" for v in project(a, digits) + project(b, digits)) for a, b in pairs)


X_LINES = [((-10, 0, 20), (10, 0, 20)), ((-10, 0, 40), (10, 0, 40)), ((-8, 0, 30), (12, 0, 30))]
Z_LINES = [((-6, 0, 15), (-6, 0, 45)), ((6, 0, 15), (6, 0, 45))]
Y_LINES = [((-6, 0, 25), (-6, 8, 25)), ((7, 0, 35), (7, 8, 35))]


class VanishingTests(unittest.TestCase):
    def solve(self, project, digits=None, extra=()):
        base, top = project((2, 0, 25), digits), project((2, 5, 25), digits)
        proc = run("camera_solve.py", "vanishing", "--image", "1920x1080", "--lines-x=" + lines(project, X_LINES, digits),
                   "--lines-z=" + lines(project, Z_LINES, digits), "--known-height", ",".join(map(str, base + top)) + ",5",
                   "--json", *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_exact_marks_recover_the_camera(self):
        r = self.solve(camera(roll=3.0))["result"]
        self.assertAlmostEqual(r["vfov_deg"], 70.0, delta=0.01)
        self.assertAlmostEqual(r["pitch_deg"], -20.0, delta=0.01)
        self.assertAlmostEqual(r["roll_deg"], -3.0, delta=0.01)  # horizon rises to the right
        self.assertAlmostEqual(r["height"], 10.0, delta=0.005)
        for k in ("vfov_deg", "pitch_deg", "height"):
            self.assertGreater(r["uncertainty"][k], 0)

    def test_whole_pixel_marks_stay_inside_the_reported_uncertainty(self):
        for kw in ({"vfov": 70.0, "pitch": -20.0}, {"vfov": 50.0, "pitch": -35.0, "yaw": -25.0, "height": 14.0}):
            out = self.solve(camera(**kw), digits=0)
            r, u = out["result"], out["result"]["uncertainty"]
            self.assertLess(abs(r["vfov_deg"] - kw["vfov"]), max(2 * u["vfov_deg"], 0.2), out)
            self.assertLess(abs(r["pitch_deg"] - kw["pitch"]), max(2 * u["pitch_deg"], 0.2), out)
            self.assertLess(u["vfov_deg"], 3.0)

    def test_third_set_and_known_ground(self):
        project = camera(vfov=60, pitch=-30, yaw=40, height=8)
        proc = run("camera_solve.py", "vanishing", "--image", "1920x1080", "--lines-x=" + lines(project, X_LINES),
                   "--lines-z=" + lines(project, Z_LINES), "--lines-y=" + lines(project, Y_LINES),
                   "--known-ground", ",".join(map(str, project((-6, 0, 20)) + project((6, 0, 20)))) + ",12", "--json", "--luau")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        r = json.loads(proc.stdout)["result"]
        self.assertAlmostEqual(r["vfov_deg"], 60.0, delta=0.01)
        self.assertAlmostEqual(r["height"], 8.0, delta=0.005)
        self.assertLess(r["focal_spread_px"], 0.5)

    def test_bad_geometry_is_refused(self):
        par = "100,500,900,500;100,600,900,600"  # parallel in the image: vanishing point at infinity
        proc = run("camera_solve.py", "vanishing", "--image", "1920x1080", "--lines-x", par, "--lines-z", "500,900,700,300;900,900,800,300")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("infinity", proc.stderr)
        same = "100,900,800,700;120,1000,900,760"
        proc = run("camera_solve.py", "vanishing", "--image", "1920x1080", "--lines-x", same, "--lines-z", same)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("perpendicular", proc.stderr)
        self.assertEqual(run("camera_solve.py", "vanishing", "--image", "1920x1080", "--lines-x", same).returncode, 2)
        self.assertEqual(run("camera_solve.py", "vanishing", "--image", "1920x1080", "--lines-x", "1,2,3", "--lines-z", same).returncode, 2)
        self.assertEqual(run("camera_solve.py", "vanishing", "--image", "wide", "--lines-x", same, "--lines-z", same).returncode, 2)


class SizeTests(unittest.TestCase):
    def test_known_size_at_known_depth(self):
        proc = run("camera_solve.py", "size", "--image", "1920x1080", "--span", "960,390,960,690", "--size", "5", "--distance", "20", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        r = json.loads(proc.stdout)["result"]
        self.assertAlmostEqual(r["focal_px"], 1200.0, places=6)  # 300 px * 20 / 5
        self.assertAlmostEqual(r["vfov_deg"], math.degrees(2 * math.atan(540 / 1200)), places=3)
        # A 1 px move at each end changes the span by 1 px in quadrature: about 0.47% of f.
        self.assertAlmostEqual(r["uncertainty"]["focal_px"], 1200 * math.sqrt(2) / 300, delta=0.05)
        with_dist = json.loads(run("camera_solve.py", "size", "--image", "1920x1080", "--span", "960,390,960,690", "--size", "5",
                                   "--distance", "20", "--distance-uncertainty", "1", "--json").stdout)["result"]
        self.assertGreater(with_dist["uncertainty"]["vfov_deg"], r["uncertainty"]["vfov_deg"] * 5)
        self.assertEqual(run("camera_solve.py", "size", "--image", "1920x1080", "--span", "1,1,1,1", "--size", "5", "--distance", "2").returncode, 1)
        self.assertEqual(run("camera_solve.py", "size", "--image", "1920x1080", "--span", "1,1,9,9", "--size", "-5", "--distance", "2").returncode, 2)


class GroundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.project = camera(vfov=60, pitch=-25, yaw=20, height=12, w=1280, h=720)
        corners = [self.project((x, 0, z)) for x, z in ((-10, 20), (10, 20), (10, 40), (-10, 40))]
        self.corners = ";".join(f"{x:.3f},{y:.3f}" for x, y in corners)

    def tearDown(self):
        self.tmp.cleanup()

    def make_track(self, anchor=None):
        speed, ramp, t0, heading = 12.0, 0.3, 0.25, 0.5
        samples = []
        for i in range(90):
            tt = i / 60 - t0
            s = 0.0 if tt <= 0 else (speed * tt * tt / (2 * ramp) if tt < ramp else speed * (tt - ramp / 2))
            x, y = self.project((-6 + math.cos(heading) * s, 0, 24 + math.sin(heading) * s))
            samples.append({"sample": i, "index": i, "t": round(i / 60, 6), "x_px": round(x, 3), "y_px": round(y - 10, 3),
                            "score": 0.99, "u": 0.0, "v": 0.0})
        track = {"tool": "motion_track", "schema": 1, "bbox": [0, 0, 20, 20], "anchor_bbox": anchor, "samples": samples,
                 "fps_from_samples": 60.0, "low_score_samples": 0}
        path = self.dir / "track.json"
        path.write_text(json.dumps(track))
        return path

    def test_points_and_track_to_world_units(self):
        out = self.dir / "ground.json"
        mid = self.project((0, 0, 30))
        proc = run("camera_solve.py", "ground", "--image", "1280x720", "--corners", self.corners, "--rect", "20x20",
                   "--points", f"{mid[0]},{mid[1]}", "--track", self.make_track(), "--analyze", "speed", "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        g = json.loads(out.read_text())
        self.assertAlmostEqual(g["points"][0]["ground"][0], 10.0, delta=0.002)
        self.assertAlmostEqual(g["points"][0]["ground"][1], 10.0, delta=0.002)
        ms = {m["metric"]: m for m in g["measurements"]}
        self.assertAlmostEqual(ms["ground_speed"]["value"], 12.0, delta=0.02)
        self.assertLess(ms["ground_speed"]["uncertainty"], 0.3)
        self.assertAlmostEqual(ms["accel_t90"]["value"], 0.27, delta=1 / 60)
        cam = g["camera_from_rect"]
        self.assertAlmostEqual(cam["vfov_deg"], 60.0, delta=0.05)
        self.assertAlmostEqual(cam["pitch_deg"], -25.0, delta=0.05)
        self.assertAlmostEqual(cam["height"], 12.0, delta=0.02)

    def test_moving_camera_track_and_bad_corners_are_refused(self):
        proc = run("camera_solve.py", "ground", "--image", "1280x720", "--corners", self.corners, "--rect", "20x20",
                   "--track", self.make_track(anchor="1,1,10,10"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("static camera", proc.stderr)
        bowtie = "100,600;900,600;300,300;800,300"
        self.assertEqual(run("camera_solve.py", "ground", "--image", "1280x720", "--corners", bowtie, "--rect", "20x20").returncode, 2)
        self.assertEqual(run("camera_solve.py", "ground", "--image", "1280x720", "--corners", self.corners, "--rect", "20").returncode, 2)

    def test_ledger_import_and_targets_skip_camera_inputs(self):
        proj = self.dir
        self.assertEqual(run("breakdown_init.py", proj, "--game", "T").returncode, 0)
        remake = proj / "remake"
        ev = run("ledger.py", "add-evidence", remake, "--type", "video", "--title", "3rd person run", "--source", "clip.mp4",
                 "--analysis", "camera_solve").stdout.strip()
        out = self.dir / "cam.json"
        project = camera()
        base, top = project((2, 0, 25)), project((2, 5, 25))
        run("camera_solve.py", "vanishing", "--image", "1920x1080", "--lines-x=" + lines(project, X_LINES),
            "--lines-z=" + lines(project, Z_LINES), "--known-height", ",".join(map(str, base + top)) + ",5", "--out", out)
        proc = run("ledger.py", "import", remake, out, "--evidence", ev)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ms = json.loads((remake / "measurements.json").read_text())["measurements"]
        self.assertEqual([m["metric"] for m in ms], ["camera_vfov", "camera_pitch", "camera_roll", "camera_height"])
        self.assertTrue(all(m["uncertainty"] > 0 and m["method"].startswith("camera_solve") for m in ms))
        g = self.dir / "g.json"
        run("camera_solve.py", "ground", "--image", "1280x720", "--corners", self.corners, "--rect", "20x20",
            "--track", self.make_track(), "--analyze", "speed", "--out", g)
        self.assertEqual(run("ledger.py", "import", remake, g, "--evidence", ev).returncode, 0)
        run("ledger.py", "targets", remake)
        metrics = json.loads((remake / "targets.json").read_text())["metrics"]
        self.assertNotIn("camera_vfov", metrics)
        self.assertAlmostEqual(metrics["ground_speed"]["target"], 12.0, delta=0.02)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not installed")
class PerspectiveFootageTests(unittest.TestCase):
    """The rendered third-person demo clip: track, then convert with marked (whole-pixel) corners."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        subprocess.run([sys.executable, str(SKILL / "examples" / "demo" / "make_demo_footage.py"), "--out", str(cls.dir),
                        "--only", "perspective"], check=True, capture_output=True)
        cls.truth = json.loads((cls.dir / "ground_truth.json").read_text())["perspective"]
        run("extract_frames.py", cls.dir / "demo_perspective.mkv", "--out", cls.dir / "frames", "--mode", "all")
        cls.corners = ";".join(f"{round(x)},{round(y)}" for x, y in cls.truth["rect_corners_px"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def convert(self, *track_args):
        bbox = ",".join(map(str, self.truth["sprite_bbox_px"]))
        track = self.dir / f"track{len(track_args)}.json"
        run("motion_track.py", self.dir / "frames" / "manifest.json", "--bbox", bbox, *track_args, "--out", track)
        out = self.dir / f"ground{len(track_args)}.json"
        proc = run("camera_solve.py", "ground", "--image", "640x360", "--corners", self.corners, "--rect", "12x12",
                   "--track", track, "--contact", "bottom", "--analyze", "speed", "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(out.read_text())

    def test_scale_search_track_converts_to_the_true_speed(self):
        g = self.convert("--scale-search")
        ms = {m["metric"]: m for m in g["measurements"]}
        speed = ms["ground_speed"]
        self.assertLess(abs(speed["value"] - self.truth["steady_speed"]), max(2 * speed["uncertainty"], 0.1), speed)
        self.assertLess(speed["uncertainty"], 0.5)
        self.assertAlmostEqual(ms["accel_t90"]["value"], self.truth["t90_s"], delta=2 / 60)
        cam = g["camera_from_rect"]
        self.assertAlmostEqual(cam["vfov_deg"], self.truth["vfov_deg"], delta=2.0)
        self.assertAlmostEqual(cam["pitch_deg"], self.truth["pitch_deg"], delta=1.0)
        self.assertAlmostEqual(cam["height"], self.truth["height"], delta=0.4)

    def test_fixed_template_track_is_not_passed_off_as_a_measurement(self):
        g = self.convert()
        self.assertEqual(g["measurements"], [])
        self.assertTrue(any("low-score" in w for w in g["warnings"]))


if __name__ == "__main__":
    unittest.main()
