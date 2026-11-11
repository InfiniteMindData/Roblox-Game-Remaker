"""Eval cases: inputs come from the setup command, and the pattern checks accept good answers.

The evals themselves are run with and without the skill by a person or a harness (evals/README.md);
these tests only keep the cases consistent with the tools and the generated files.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "roblox-game-remaker"
EVALS = json.loads((ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))
GENERATOR = (SKILL / "examples" / "demo" / "make_demo_footage.py").read_text(encoding="utf-8")


def grade(text: str, eval_id: int) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "r.txt"
        f.write_text(text, encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "evals" / "grade.py"), str(f), "--eval", str(eval_id)], capture_output=True, text=True)


class EvalCaseTests(unittest.TestCase):
    def test_cases_are_complete_and_inputs_are_generated(self):
        ids = [e["id"] for e in EVALS["evals"]]
        self.assertEqual(ids, list(range(1, len(ids) + 1)))
        only = re.search(r"--only (\S+)", EVALS["setup"]).group(1).split(",")
        for e in EVALS["evals"]:
            self.assertTrue(e["prompt"] and e["expected_output"] and e["assertions"] and e["checks"]["must_match"], e["name"])
            for f in e["files"]:
                self.assertTrue(f.startswith("evals/files/demo/"), f)
                self.assertIn(Path(f).name, GENERATOR, f"{e['name']}: {f} is not written by make_demo_footage.py")
        self.assertTrue({"degraded", "extras", "perspective"} <= set(only))
        not_trigger = [e for e in EVALS["evals"] if "should-not-trigger" in e["name"]]
        self.assertGreaterEqual(len(not_trigger), 2)

    def test_checks_accept_good_answers_and_reject_known_failures(self):
        cases = {
            13: ("3 of 20 kills: the 95% exact interval is 0.0321 to 0.3789. I'll use 0.15 as an ASSUMED value inside it; "
                 "about 224 kills would narrow it to ±0.05.", "The drop rate is 15%."),
            14: ("fit_curve ranks Back Out first: TweenInfo.new(0.35, Enum.EasingStyle.Back, Enum.EasingDirection.Out).",
                 "Looks like a quad ease: TweenInfo.new(0.3, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)."),
            17: ("The clip shows no input overlay or filmed controller, so the latency cannot be measured; I've marked it ASSUMED.",
                 "The game responds in 3 frames."),
            19: ("Use a HingeConstraint with ActuatorType Motor, or rotate the CFrame every frame with RunService.",
                 "Let's start the remake: run breakdown_init.py and fill 00-intake.md."),
            12: ("Measured 19.45 ± 0.61 studs/s: the compression makes the anchor drift, so 0.1 studs/s is not supported.",
                 "The run speed is 19.45 ± 0.01 studs/s."),
        }
        for eid, (good, bad) in cases.items():
            self.assertEqual(grade(good, eid).returncode, 0, f"eval {eid} rejected a good answer:\n{grade(good, eid).stdout}")
            self.assertEqual(grade(bad, eid).returncode, 1, f"eval {eid} accepted a bad answer")


class ToolOutputMeetsChecksTests(unittest.TestCase):
    """The tools' own output on the eval inputs satisfies the pattern checks (so the checks are reachable)."""

    def test_menu_tween_and_sound_cases(self):
        scripts = SKILL / "scripts"
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            subprocess.run([sys.executable, str(SKILL / "examples" / "demo" / "make_demo_footage.py"), "--out", str(d), "--only", "extras"],
                           check=True, capture_output=True)
            fit = subprocess.run([sys.executable, str(scripts / "fit_curve.py"), "--track", str(d / "demo_menu_track.json"),
                                  "--field", "x_px", "--luau"], capture_output=True, text=True)
            self.assertEqual(grade(fit.stdout, 14).returncode, 0, fit.stdout)
            snd = subprocess.run([sys.executable, str(scripts / "audio_compare.py"), "compare", str(d / "demo_sfx_ref.wav"),
                                  str(d / "demo_sfx_new.wav")], capture_output=True, text=True)
            self.assertEqual(snd.returncode, 1)
            self.assertEqual(grade(snd.stdout, 16).returncode, 0, snd.stdout)
            stats = subprocess.run([sys.executable, str(scripts / "event_stats.py"), "--counts", "3/20", "--plan-halfwidth", "0.05"],
                                   capture_output=True, text=True)
            self.assertEqual(grade(stats.stdout, 13).returncode, 0, stats.stdout)


if __name__ == "__main__":
    unittest.main()
