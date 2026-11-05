"""Tests for the workflow tools: ledger, config_check, remake_status, frame_zoom, find_mover."""

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
SAMPLE = SKILL / "examples" / "04-sample-workspace"
TEMPLATE_CONFIG = SKILL / "assets" / "rojo-template" / "src" / "shared" / "Remake" / "Config.luau"
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=600)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self.tmp.name)
        self.assertEqual(run("breakdown_init.py", self.proj, "--game", "T").returncode, 0)
        self.remake = self.proj / "remake"

    def tearDown(self):
        self.tmp.cleanup()

    def test_ids_and_validation(self):
        a = run("ledger.py", "add-evidence", self.remake, "--type", "video", "--title", "jump", "--source", "j.mp4", "--analysis", "x")
        b = run("ledger.py", "add-evidence", self.remake, "--type", "video", "--title", "dead", "--source", "https://x", "--inaccessible")
        self.assertEqual((a.stdout.strip(), b.stdout.strip()), ("EV-002", "EV-003"))
        self.assertEqual(run("ledger.py", "add-evidence", self.remake, "--type", "bogus", "--title", "t", "--source", "s").returncode, 2)
        ok = run("ledger.py", "add-measurement", self.remake, "--what", "apex", "--evidence", "EV-002", "--method", "m",
                 "--value", "8", "--uncertainty", "0.1", "--unit", "studs", "--metric", "jump_apex")
        self.assertEqual(ok.stdout.strip(), "MS-001")
        bad = run("ledger.py", "add-measurement", self.remake, "--what", "apex", "--evidence", "EV-003", "--method", "m",
                  "--value", "8", "--uncertainty", "0.1", "--unit", "studs")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("inaccessible", bad.stderr)
        self.assertEqual(run("ledger.py", "targets", self.remake, "--tier", "S").returncode, 0)
        t = json.loads((self.remake / "targets.json").read_text())["metrics"]["jump_apex"]
        self.assertEqual(t["target"], 8.0)
        self.assertAlmostEqual(t["tolerance"], 0.24, places=6)  # 3% beats the 0.1 uncertainty
        self.assertEqual(run("breakdown_check.py", self.remake).returncode, 0)

    def test_import_track(self):
        track = {"tool": "motion_track", "unit": "studs", "px_per_unit": 20, "bbox": [1, 2, 3, 4], "anchor_bbox": None,
                 "samples": [{"index": 10}, {"index": 11}, {"index": 50}],
                 "jump": {"segment_samples": [0, 2], "apex_height": 8.0, "rise_time_s": 0.4, "fall_time_s": 0.28,
                          "airtime_s": 0.68, "g_rise": 100, "g_rise_std": 0.5, "g_fall": 200, "g_fall_std": 1.0,
                          "fit_rms": 0.01, "time_precision_s": 1 / 60, "method": "piecewise"}}
        (self.proj / "t.json").write_text(json.dumps(track))
        ev = run("ledger.py", "add-evidence", self.remake, "--type", "video", "--title", "j", "--source", "j", "--analysis", "a").stdout.strip()
        proc = run("ledger.py", "import-track", self.remake, self.proj / "t.json", "--evidence", ev)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ms = json.loads((self.remake / "measurements.json").read_text())["measurements"]
        self.assertEqual([m["metric"] for m in ms], ["jump_apex", "jump_rise_time", "jump_fall_time", "jump_airtime", "g_rise", "g_fall"])
        self.assertEqual(ms[0]["frames"], [10, 50])
        run("ledger.py", "targets", self.remake)
        metrics = json.loads((self.remake / "targets.json").read_text())["metrics"]
        self.assertNotIn("g_rise", metrics)
        self.assertAlmostEqual(metrics["jump_rise_time"]["tolerance"], 2 / 60, places=4)


class ConfigCheckTests(unittest.TestCase):
    def test_sample_passes_strict(self):
        proc = run("config_check.py", SAMPLE / "remake", "--strict", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(json.loads(proc.stdout)["summary"]["direct_matches"], 3)

    def test_detects_drift_and_bad_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "Config.luau"
            text = (SAMPLE / "src" / "shared" / "Remake" / "Config.luau").read_text()
            text = text.replace("WalkSpeed = 20, -- MS-004", "WalkSpeed = 24, -- MS-004")
            text = text.replace('["Movement.JumpApex"] = "MS-001",', '["Movement.JumpApex"] = "MS-001",\n\t["Movement.AirJumps"] = "MS-777",\n\t["Movement.JumpBuffer2"] = "ASSUMED: guess",')
            cfg.write_text(text)
            proc = run("config_check.py", SAMPLE / "remake", "--config", cfg, "--json")
            self.assertEqual(proc.returncode, 1)
            data = json.loads(proc.stdout)
            errs = "\n".join(e["message"] for e in data["errors"])
            warns = "\n".join(w["message"] for w in data["warnings"])
            self.assertIn("Movement.WalkSpeed = 24 but MS-004 measured 19.996", errs)
            self.assertIn("MS-777, which is not in the ledgers", errs)
            self.assertIn("JumpBuffer2, which Config does not define", warns)
            self.assertIn("ASSUMED", warns)

    def test_template_config_parses(self):
        proc = run("config_check.py", SAMPLE / "remake", "--config", TEMPLATE_CONFIG, "--json")
        data = json.loads(proc.stdout)
        self.assertGreater(data["summary"]["values"], 50)
        self.assertEqual(data["error_count"], 0)


class StatusTests(unittest.TestCase):
    def test_sample_reaches_verify_phase(self):
        proc = run("remake_status.py", SAMPLE / "remake", "--json")
        st = json.loads(proc.stdout)
        self.assertEqual(st["current_phase"], 6)
        self.assertTrue(all(g["ok"] for g in st["gates"][:6]))
        self.assertTrue(any("EV-006" in s for s in st["inaccessible_sources"]))
        self.assertEqual(run("remake_status.py", SAMPLE / "remake", "--require-phase", "6").returncode, 0)
        self.assertEqual(run("remake_status.py", SAMPLE / "remake", "--require-phase", "7").returncode, 1)

    def test_fresh_workspace_starts_at_intake_and_writes_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            run("breakdown_init.py", tmp, "--game", "T")
            proc = run("remake_status.py", Path(tmp) / "remake", "--write")
            self.assertEqual(proc.returncode, 0)
            self.assertIn("**Current phase:** 0 Intake and rights", proc.stdout)
            self.assertTrue((Path(tmp) / "remake" / "STATUS.md").is_file())
        self.assertEqual(run("remake_status.py", "/nonexistent").returncode, 2)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not installed")
class FrameToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        subprocess.run([sys.executable, str(SKILL / "examples" / "demo" / "make_demo_footage.py"), "--out", str(cls.dir)], check=True, capture_output=True)
        for clip in ("jump", "run"):
            run("extract_frames.py", cls.dir / f"demo_{clip}.mkv", "--out", cls.dir / clip, "--mode", "all")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def iou(a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
        iy = max(0, min(ay + ah, by + bh) - max(ay, by))
        inter = ix * iy
        return inter / (aw * ah + bw * bh - inter)

    def test_find_mover_static_camera(self):
        data = json.loads(run("find_mover.py", self.dir / "jump" / "manifest.json", "--json").stdout)
        self.assertFalse(data["camera_moves"])
        self.assertGreater(self.iou(data["candidates"][0]["bbox"], [288, 288, 24, 24]), 0.7)

    def test_find_mover_panning_camera_and_anchor(self):
        data = json.loads(run("find_mover.py", self.dir / "run" / "manifest.json", "--json", "--preview", self.dir / "p.png").stdout)
        self.assertTrue(data["camera_moves"])
        self.assertGreater(self.iou(data["candidates"][0]["bbox"], [90, 200, 20, 20]), 0.7)
        self.assertIsNotNone(data["anchor_bbox"])
        self.assertTrue((self.dir / "p.png").is_file())
        # The suggestion must actually work end to end.
        bbox = ",".join(map(str, data["candidates"][0]["bbox"]))
        anchor = ",".join(map(str, data["anchor_bbox"]))
        run("motion_track.py", self.dir / "run" / "manifest.json", "--bbox", bbox, "--anchor-bbox", anchor, "--search", "40",
            "--px-per-unit", "20", "--analyze", "speed", "--out", self.dir / "s.json")
        s = json.loads((self.dir / "s.json").read_text())["speed"]
        self.assertAlmostEqual(s["steady_speed"], 20, delta=0.3)

    def test_frame_zoom(self):
        frame = sorted((self.dir / "jump").glob("f000000_*.png"))[0]
        proc = run("frame_zoom.py", frame, "--region", "270,270,60,60", "--scale", "8", "--mark", "288,288,24,24",
                   "--point", "300,300", "--out", self.dir / "z.png")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        from PIL import Image
        with Image.open(self.dir / "z.png") as im:
            self.assertEqual(im.size, (60 * 8 + 44, 60 * 8 + 18))
        self.assertEqual(run("frame_zoom.py", frame, "--region", "600,380,100,100", "--out", self.dir / "bad.png").returncode, 2)


if __name__ == "__main__":
    unittest.main()
