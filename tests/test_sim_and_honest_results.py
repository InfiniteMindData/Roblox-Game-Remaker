"""Simulation-driven games (SimRecorder logs), honest "unchecked" results, and tool launching on Windows."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "roblox-game-remaker" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import doctor  # noqa: E402
import remake_common as rc  # noqa: E402

HZ = 60


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=600)


def line(obj: dict) -> str:
    return f"12:00:00.000  REMAKE_MEASURE {json.dumps(obj)}  -  Server"


def fight_log(path: Path, startup: int = 7) -> Path:
    """Two fighters as SimRecorder writes them. p1 walks forward at 3 units/s for 1 s, then attacks:
    attack at tick 80, active at 80 + startup, back to idle 12 ticks later. p2 stands still."""
    out = [line({"k": "sim", "id": sid, "hz": HZ, "grounded": ["idle", "walkF", "walkB"]}) for sid in ("p1", "p2")]
    out.append(line({"k": "e", "id": "p1", "t": 10 / HZ, "n": "move_start"}))
    rows, x = [], 0.0
    for tick in range(10, 70):
        x += 3 / HZ
        rows.append([round(tick / HZ, 5), round(x, 4), 0, 0, 3, 0, 0, "walkF", 1])
    out.append(line({"k": "b", "id": "p1", "s": rows}))
    out.append(line({"k": "e", "id": "p1", "t": 70 / HZ, "n": "move_stop"}))
    out.append(line({"k": "b", "id": "p1", "s": [[round(t / HZ, 5), round(x, 4), 0, 0, 0, 0, 0, "idle", 0] for t in range(70, 80)]}))
    for t, n in ((80, "attack"), (80 + startup, "active"), (92 + startup, "idle")):
        out.append(line({"k": "e", "id": "p1", "t": round(t / HZ, 5), "n": n}))
    out.append(line({"k": "b", "id": "p2", "s": [[round(t / HZ, 5), 5, 0, 0, 0, 0, 0, "idle", 0] for t in range(0, 100)]}))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


class SimLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def targets(self, metrics: dict) -> Path:
        p = self.dir / "t.json"
        p.write_text(json.dumps({"metrics": metrics}), encoding="utf-8")
        return p

    def test_several_subjects_need_a_choice(self):
        proc = run("measure_compare.py", fight_log(self.dir / "f.log"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("p1, p2", proc.stderr)
        self.assertEqual(run("measure_compare.py", self.dir / "f.log", "--subject", "p9").returncode, 2)

    def test_frame_data_interval_judged_in_frames(self):
        log = fight_log(self.dir / "f.log", startup=7)
        t = self.targets({"startup": {"target": 7, "tolerance": 0, "unit": "frames"},
                          "ground_speed": {"target": 3, "tolerance": 0.05}})
        proc = run("measure_compare.py", log, "--subject", "p1", "--interval", "startup=attack..active",
                   "--interval", "recovery=active..idle", "--targets", t, "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        rep = json.loads(proc.stdout)
        self.assertEqual(rep["hz"], HZ)
        self.assertEqual(rep["status"], "pass")
        self.assertEqual(rep["metrics"]["startup"]["unit"], "frames")
        self.assertAlmostEqual(rep["metrics"]["startup"]["mean"], 7, places=2)
        self.assertAlmostEqual(rep["metrics"]["recovery"]["mean_frames"], 12, places=2)
        self.assertAlmostEqual(rep["metrics"]["ground_speed"]["mean"], 3, places=3)  # walkF counts as grounded

        slow = fight_log(self.dir / "slow.log", startup=9)
        proc = run("measure_compare.py", slow, "--subject", "p1", "--interval", "startup=attack..active", "--targets", t)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("FAIL  startup", proc.stdout)

    def test_clip_compare_reads_one_subject(self):
        log = fight_log(self.dir / "f.log")
        proc = run("clip_compare.py", log, log, "--subject", "p1", "--json")
        self.assertIn(proc.returncode, (0, 1), proc.stderr)
        self.assertNotIn("several subjects", proc.stderr)

    def test_log_without_motion_fails(self):
        log = self.dir / "empty.log"
        log.write_text(line({"k": "e", "t": 0, "n": "session"}) + "\n", encoding="utf-8")
        proc = run("measure_compare.py", log)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("SimRecorder", proc.stderr)

    def test_interval_ends_before_the_next_start(self):
        """Two whiffed jabs and one that connects: attack..hit must pair only the third."""
        out = [line({"k": "sim", "id": "p1", "hz": HZ, "grounded": ["idle"]})]
        for a in (100, 130, 160):
            out.append(line({"k": "e", "id": "p1", "t": a / HZ, "n": "attack"}))
            out.append(line({"k": "e", "id": "p1", "t": (a + 20) / HZ, "n": "neutral"}))
        out.append(line({"k": "e", "id": "p1", "t": 167 / HZ, "n": "hit"}))
        out.append(line({"k": "b", "id": "p1", "s": [[round(t / HZ, 5), 0, 0, 0, 0, 0, 0, "idle", 0] for t in range(95, 190)]}))
        log = self.dir / "jabs.log"
        log.write_text("\n".join(out) + "\n", encoding="utf-8")
        proc = run("measure_compare.py", log, "--interval", "contact=attack..hit", "--interval", "total=attack..neutral", "--json")
        rep = json.loads(proc.stdout)
        self.assertEqual(rep["metrics"]["contact"]["n"], 1)
        self.assertAlmostEqual(rep["metrics"]["contact"]["mean_frames"], 7, places=2)
        self.assertEqual(rep["unpaired_intervals"], {"contact": 2})
        self.assertEqual(rep["metrics"]["total"]["n"], 3)

    def test_speeds_per_state_and_per_window_acceleration(self):
        """Back-walk at 7 then forward-walk at 9: separate speeds, and no acceleration artefact."""
        out = [line({"k": "sim", "id": "p1", "hz": HZ, "grounded": ["idle", "walkF", "walkB"]})]
        rows, x, tick = [], 0.0, 0
        for state, speed, ticks in (("idle", 0, 10), ("walkB", 7, 72), ("idle", 0, 20), ("walkF", 9, 84), ("idle", 0, 20)):
            if state != "idle":
                out.append(line({"k": "e", "id": "p1", "t": round(tick / HZ, 5), "n": "move_start"}))
            for _ in range(ticks):
                x += (speed if state == "walkF" else -speed) / HZ
                rows.append([round(tick / HZ, 5), round(x, 4), 0, 0, speed if state == "walkF" else -speed, 0, 0, state,
                             0 if state == "idle" else 1])
                tick += 1
            if state != "idle":
                out.append(line({"k": "b", "id": "p1", "s": rows}))
                rows = []
                out.append(line({"k": "e", "id": "p1", "t": round(tick / HZ, 5), "n": "move_stop"}))
        out.append(line({"k": "b", "id": "p1", "s": rows}))
        log = self.dir / "walks.log"
        log.write_text("\n".join(out) + "\n", encoding="utf-8")
        rep = json.loads(run("measure_compare.py", log, "--json").stdout)
        self.assertAlmostEqual(rep["metrics"]["ground_speed[walkB]"]["mean"], 7, places=3)
        self.assertAlmostEqual(rep["metrics"]["ground_speed[walkF]"]["mean"], 9, places=3)
        self.assertEqual(rep["metrics"]["accel_t90"]["max"], 0)  # used to be ~2.3 s: back-walk never reached 90% of 9

    def test_no_targets_is_unchecked_not_pass(self):
        proc = run("measure_compare.py", fight_log(self.dir / "f.log"), "--subject", "p1")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("result: unchecked", proc.stdout)


class VisualCompareHonestyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        rng = np.random.default_rng(3)
        base = (rng.random((90, 160, 3)) * 255).astype(np.uint8)
        Image.fromarray(base).save(self.dir / "ref.png")
        Image.fromarray(base).resize((240, 90)).save(self.dir / "wide.png")  # 2.67:1 instead of 16:9

    def tearDown(self):
        self.tmp.cleanup()

    def test_aspect_mismatch_fails_unless_allowed(self):
        proc = run("visual_compare.py", "pair", self.dir / "ref.png", self.dir / "wide.png", "--out", self.dir / "a")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("aspect mismatch", proc.stdout)
        ok = run("visual_compare.py", "pair", self.dir / "ref.png", self.dir / "wide.png", "--out", self.dir / "b",
                 "--allow-aspect-mismatch")
        self.assertEqual(ok.returncode, 0, ok.stdout)

    def test_no_thresholds_is_unchecked(self):
        proc = run("visual_compare.py", "pair", self.dir / "ref.png", self.dir / "ref.png", "--out", self.dir / "c", "--json")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["status"], "unchecked")
        shots = {"shots": [{"id": "S", "reference": "ref.png", "recreation": "wide.png", "thresholds": {"ssim": 0.5}}]}
        (self.dir / "shots.json").write_text(json.dumps(shots), encoding="utf-8")
        proc = run("visual_compare.py", "batch", self.dir / "shots.json", "--out", self.dir / "d", "--root", self.dir)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        summary = json.loads((self.dir / "d" / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["shots"][0]["status"], "fail")
        self.assertTrue(summary["shots"][0]["aspect_mismatch"])


class LauncherTests(unittest.TestCase):
    """Windows starts only .exe files by bare name; tools installed as .cmd launchers must still run."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        if os.name == "nt":
            (self.dir / "remakefaketool.cmd").write_text("@echo off\r\necho faketool 1.2.3\r\n", encoding="utf-8")
        else:
            script = self.dir / "remakefaketool"
            script.write_text("#!/bin/sh\necho faketool 1.2.3\n", encoding="utf-8")
            script.chmod(0o755)
        self.path = os.environ["PATH"]
        os.environ["PATH"] = str(self.dir) + os.pathsep + self.path

    def tearDown(self):
        os.environ["PATH"] = self.path
        self.tmp.cleanup()

    def test_doctor_runs_launcher_scripts(self):
        info = doctor.probe(["remakefaketool", "--version"])
        self.assertTrue(info["runs"], info)
        self.assertEqual(info["version"], "faketool 1.2.3")

    def test_missing_tool_is_not_usable(self):
        info = doctor.probe(["remake-no-such-tool-xyz", "--version"])
        self.assertEqual(info, {"path": None, "version": None, "runs": False})

    def test_shared_runner_resolves_launchers(self):
        proc = rc.run(["remakefaketool"])
        self.assertIn(b"faketool 1.2.3", proc.stdout)


if __name__ == "__main__":
    unittest.main()
