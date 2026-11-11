"""Tests for fidelity_report.py: scorecard, history and regression detection across iterations."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "roblox-game-remaker"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_clip_compare import ramp, write_log, write_track  # noqa: E402
from test_skill import MeasureCompareTests  # noqa: E402


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=600)


class FidelityReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self.tmp.name)
        run("breakdown_init.py", self.proj, "--game", "T")
        self.remake = r = self.proj / "remake"
        rng = np.random.default_rng(0)
        img = (rng.random((120, 160, 3)) * 200 + 20).astype(np.uint8)
        (r / "media").mkdir(exist_ok=True)
        (r / "captures").mkdir(exist_ok=True)
        Image.fromarray(img).save(r / "media" / "ref.png")
        Image.fromarray(img).save(r / "captures" / "rec.png")
        shots = {"shots": [{"id": "SHOT-01", "reference": "remake/media/ref.png", "recreation": "remake/captures/rec.png",
                            "thresholds": {"ssim": 0.8, "delta_e_mean": 6.0}}]}
        (r / "shots.json").write_text(json.dumps(shots))
        targets = {"metrics": {"jump_apex": {"target": 7.4, "tolerance": 0.3}, "ground_speed": {"target": 20, "tolerance_pct": 3}},
                   "clips": {"default": {"position_rms": 0.5}}}
        (r / "targets.json").write_text(json.dumps(targets))
        (r / "logs").mkdir(exist_ok=True)
        MeasureCompareTests.make_log(None, r / "logs" / "run-01.log")
        write_track(self.proj / "ref.json", 60, 90, along=lambda t: ramp(t, 20, 0.25, 0.2))

    def tearDown(self):
        self.tmp.cleanup()

    def iteration(self, n: int, rec_speed: float, *extra, code=0):
        r = self.remake
        self.assertIn(run("visual_compare.py", "batch", r / "shots.json", "--out", r / "diff" / f"it{n}", "--root", self.proj).returncode, (0, 1))
        write_log(self.proj / f"rec{n}.log", 60, 90, lambda t: ramp(t, rec_speed, 0.25, 0.3), lambda t: 0.0)
        run("clip_compare.py", self.proj / "ref.json", self.proj / f"rec{n}.log", "--targets", r / "targets.json", "--clip", "run01",
            "--out", r / "diff" / f"it{n}" / "clip-run01.json")
        proc = run("fidelity_report.py", r, "--diff-log", "--label", f"iteration {n}", *extra)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return proc

    def test_scorecard_history_and_regression(self):
        self.iteration(1, 20.0)
        r = self.remake
        history = [json.loads(ln) for ln in (r / "history.jsonl").read_text().splitlines()]
        self.assertEqual(len(history), 1)
        sysm = history[0]["systems"]
        self.assertEqual(sysm["shot:SHOT-01"]["status"], "pass")
        self.assertAlmostEqual(sysm["shot:SHOT-01"]["r"], 0.0, places=3)  # identical images: perfect ssim and delta E
        self.assertEqual(sysm["metric:jump_apex"]["status"], "pass")
        self.assertAlmostEqual(sysm["metric:jump_apex"]["r"], abs(sysm["metric:jump_apex"]["error"]) / 0.3, places=3)
        self.assertEqual(sysm["clip:run01"]["status"], "pass")
        card = (r / "scorecard.md").read_text()
        self.assertIn("| metric:jump_apex | pass |", card)
        self.assertIn("## Iteration 1", (r / "diff-log.md").read_text())

        # Iteration 2: a darker capture and a slower recreation. The shot and the clip regress.
        ImageEnhance.Brightness(Image.open(r / "captures" / "rec.png")).enhance(0.6).save(r / "captures" / "rec.png")
        proc = self.iteration(2, 17.0, code=1)
        self.assertIn("REGRESSION", proc.stderr)
        latest = json.loads((r / "history.jsonl").read_text().splitlines()[-1])
        self.assertEqual(latest["iteration"], 2)
        self.assertTrue(any(x.startswith("shot:SHOT-01") for x in latest["regressions"]))
        self.assertTrue(any(x.startswith("clip:run01") for x in latest["regressions"]))
        self.assertGreater(latest["systems"]["clip:run01"]["change"], 1.0)
        self.assertIn("REGRESSIONS", (r / "diff-log.md").read_text())

        # remake_status reports the scorecard and holds the verify gate on the regression.
        st = json.loads(run("remake_status.py", r, "--json").stdout)
        self.assertEqual(st["scorecard"]["iteration"], 2)
        self.assertTrue(st["scorecard"]["regressions"])
        verify = st["gates"][6]
        self.assertFalse(verify["ok"])
        self.assertIn("regressions", verify["action"])
        text = run("remake_status.py", r, "--write").stdout
        self.assertIn("REGRESSION:", text)

        # A dry run writes nothing.
        before = (r / "history.jsonl").read_text()
        run("fidelity_report.py", r, "--dry-run")
        self.assertEqual((r / "history.jsonl").read_text(), before)

    def test_bad_input(self):
        self.assertEqual(run("fidelity_report.py", self.proj / "nope").returncode, 2)
        with tempfile.TemporaryDirectory() as tmp:
            run("breakdown_init.py", tmp, "--game", "T")
            proc = run("fidelity_report.py", Path(tmp) / "remake")
            self.assertEqual(proc.returncode, 1)
            self.assertIn("nothing to score", proc.stderr)
        self.assertEqual(run("fidelity_report.py", self.remake, "--log", self.proj / "missing.log").returncode, 2)


if __name__ == "__main__":
    unittest.main()
