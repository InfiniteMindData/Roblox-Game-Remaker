"""Tests for fit_curve.py: identifying easing curves, springs and exponential approaches."""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "roblox-game-remaker"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fit_curve  # noqa: E402


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=600)


class CurveFormulaTests(unittest.TestCase):
    def test_every_template_curve_is_fitted(self):
        luau = (SKILL / "assets" / "rojo-template" / "src" / "shared" / "Remake" / "Easing.luau").read_text(encoding="utf-8")
        block = luau[luau.index("local IN"):luau.index("function Easing.get")]
        names = set(re.findall(r"^\t([A-Z][A-Za-z]+) = function", block, re.M))
        self.assertEqual(names, {"Linear", *fit_curve.STYLES})

    def test_values_match_the_template_formulas(self):
        c1 = 1.70158
        cases = {("Quad", "Out", 0.5): 0.75, ("Cubic", "In", 0.5): 0.125, ("Sine", "InOut", 0.25): (1 - math.cos(math.pi / 4)) / 2,
                 ("Back", "Out", 0.5): 1 - ((c1 + 1) * 0.125 - c1 * 0.25), ("Bounce", "Out", 0.5): 7.5625 * (0.5 - 1.5 / 2.75) ** 2 + 0.75,
                 ("Exponential", "In", 0.0): 0.0, ("Exponential", "In", 0.5): 2 ** -5, ("Circular", "Out", 0.6): math.sqrt(1 - 0.16),
                 ("Elastic", "Out", 1.0): 1.0, ("Quint", "InOut", 0.75): 1 - (0.5 ** 5) / 2}
        for (style, direction, x), want in cases.items():
            self.assertAlmostEqual(float(fit_curve.ease(style, direction, np.array([x]))[0]), want, places=9, msg=f"{style} {direction}")
        c2 = c1 * 1.525
        self.assertAlmostEqual(float(fit_curve.ease("Back", "InOut", np.array([0.25]))[0]), (0.5 ** 2 * ((c2 + 1) * 0.5 - c2)) / 2, places=9)
        # Spring.luau's closed form, released from rest: critically damped and underdamped.
        self.assertAlmostEqual(float(fit_curve.spring_progress(np.array([0.1]), 20.0, 1.0)[0]), 1 - math.exp(-2) * 3, places=9)
        wd = 10 * math.sqrt(1 - 0.25)
        want = 1 - math.exp(-5 * 0.2) * (math.cos(wd * 0.2) + 5 / wd * math.sin(wd * 0.2))
        self.assertAlmostEqual(float(fit_curve.spring_progress(np.array([0.2]), 10.0, 0.5)[0]), want, places=9)


class FitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.rng = np.random.default_rng(7)

    def tearDown(self):
        self.tmp.cleanup()

    def fit(self, t, y, *extra, code=0):
        path = self.dir / "track.json"
        path.write_text(json.dumps({"tool": "motion_track", "samples": [{"t": float(a), "x_px": float(b)} for a, b in zip(t, y)]}), encoding="utf-8")
        proc = run("fit_curve.py", "--track", path, "--field", "x_px", "--json", *extra)
        self.assertEqual(proc.returncode, code, proc.stderr)
        return json.loads(proc.stdout) if code == 0 else proc

    def test_easing_curves_are_identified_with_their_duration(self):
        t = np.arange(0, 1.0, 1 / 60)
        for style, direction in (("Quad", "Out"), ("Back", "Out"), ("Sine", "InOut"), ("Bounce", "Out"), ("Cubic", "In"), ("Linear", "In")):
            y = 100 + 300 * fit_curve.ease(style, direction, (t - 0.25) / 0.4) + self.rng.normal(0, 0.15, len(t))
            rep = self.fit(t, y)
            name = "Linear" if style == "Linear" else f"{style} {direction}"
            self.assertEqual(rep["best"]["name"], name)
            self.assertAlmostEqual(rep["best"]["duration_s"], 0.4, delta=0.01, msg=name)
            self.assertAlmostEqual(rep["best"]["start_s"], 0.25, delta=0.01, msg=name)
            self.assertLessEqual(abs(rep["best"]["duration_s"] - 0.4), rep["uncertainty"]["duration_s"], name)
            self.assertEqual(rep["measurements"][0]["metric"], "curve_duration")

    def test_spring_parameters(self):
        t = np.arange(0, 1.2, 1 / 60)
        y = 50 + 120 * fit_curve.spring_progress(t - 0.2, 12.0, 0.6) + self.rng.normal(0, 0.15, len(t))
        rep = self.fit(t, y, "--luau")
        best = rep["best"]
        self.assertEqual(best["name"], "Spring")
        self.assertAlmostEqual(best["omega"], 12.0, delta=0.12)
        self.assertAlmostEqual(best["zeta"], 0.6, delta=0.02)
        self.assertEqual({m["metric"] for m in rep["measurements"]}, {"curve_spring_omega", "curve_spring_zeta"})

    def test_exponential_approach_and_a_true_tie(self):
        t = np.arange(0, 1.2, 1 / 60)
        y = 50 + 120 * (1 - np.exp(-np.clip(t - 0.2, 0, None) / 0.15)) + self.rng.normal(0, 0.15, len(t))
        rep = self.fit(t, y)
        names = {rep["best"]["name"]} | {x["name"] for x in rep["indistinguishable_from_best"]}
        # Easing.luau's Exponential Out is 1 - 2^(-10x): an exponential approach with tau = duration / (10 ln 2).
        self.assertTrue({"ExpApproach", "Exponential Out"} <= names, names)
        tau = rep["best"]["tau_s"] if rep["best"]["name"] == "ExpApproach" else rep["best"]["duration_s"] / (10 * math.log(2))
        self.assertAlmostEqual(tau, 0.15, delta=0.005)
        self.assertTrue(any("NOT DISTINGUISHABLE" in w for w in rep["warnings"]))

    def test_low_frame_rate_says_the_top_fits_cannot_be_told_apart(self):
        t = np.arange(0, 1.0, 1 / 10)
        y = 100 + 300 * fit_curve.ease("Sine", "Out", (t - 0.25) / 0.4) + self.rng.normal(0, 2.0, len(t))
        rep = self.fit(t, y, "--plot", self.dir / "fit.png", "--noise", "2")
        self.assertTrue(rep["indistinguishable_from_best"])
        self.assertTrue(any("NOT DISTINGUISHABLE at 10.0 fps" in w for w in rep["warnings"]))
        self.assertTrue(any(x["higher_fps_would_separate"] for x in rep["indistinguishable_from_best"]))
        self.assertGreaterEqual(rep["uncertainty"]["duration_s"], 0.05)  # never finer than half a frame
        self.assertTrue((self.dir / "fit.png").is_file())

    def test_luau_output_and_ledger_import(self):
        t = np.arange(0, 1.0, 1 / 60)
        y = 10 + 200 * fit_curve.ease("Quad", "Out", (t - 0.1) / 0.3)
        (self.dir / "s.csv").write_text("time,x\n" + "".join(f"{a},{b}\n" for a, b in zip(t, y)), encoding="utf-8")
        proc = run("fit_curve.py", "--csv", self.dir / "s.csv", "--columns", "time,x", "--luau", "--out", self.dir / "fit.json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("TweenInfo.new(0.3", proc.stdout)
        self.assertIn("Enum.EasingStyle.Quad, Enum.EasingDirection.Out)", proc.stdout)
        run("breakdown_init.py", self.dir, "--game", "T")
        ev = run("ledger.py", "add-evidence", self.dir / "remake", "--type", "video", "--title", "menu", "--source", "m.mp4",
                 "--analysis", "fit_curve").stdout.strip()
        self.assertEqual(run("ledger.py", "import", self.dir / "remake", self.dir / "fit.json", "--evidence", ev).returncode, 0)
        ms = json.loads((self.dir / "remake" / "measurements.json").read_text(encoding="utf-8"))["measurements"]
        self.assertEqual(ms[0]["metric"], "curve_duration")
        self.assertIn("Quad Out", ms[0]["what"])

    def test_bad_input(self):
        self.assertEqual(run("fit_curve.py", "--points", "0,0;0.1,1;0.2,2").returncode, 2)
        flat = ";".join(f"{i / 60},5" for i in range(30))
        self.assertEqual(run("fit_curve.py", "--points", flat).returncode, 1)
        self.assertEqual(run("fit_curve.py", "--points", flat, "--csv", "x.csv").returncode, 2)
        (self.dir / "t.json").write_text(json.dumps({"samples": [{"t": i / 60, "u": i} for i in range(30)]}), encoding="utf-8")
        self.assertEqual(run("fit_curve.py", "--track", self.dir / "t.json", "--field", "nope").returncode, 2)
        self.assertEqual(run("fit_curve.py", "--track", self.dir / "t.json").returncode, 2)


if __name__ == "__main__":
    unittest.main()
