"""Tests for event_stats.py: intervals, binomial rates, state machines and progression curves."""

from __future__ import annotations

import csv
import json
import math
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

import event_stats  # noqa: E402


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=600)


class DistributionTests(unittest.TestCase):
    def test_reference_values(self):
        # binom.test(3, 20) in R: 0.03207094 0.37892683; 0 of 10: upper 0.3084971
        lo, hi = event_stats.clopper_pearson(3, 20, 0.95)
        self.assertAlmostEqual(lo, 0.03207094, places=7)
        self.assertAlmostEqual(hi, 0.37892683, places=7)
        self.assertEqual(event_stats.clopper_pearson(0, 10, 0.95)[0], 0.0)
        self.assertAlmostEqual(event_stats.clopper_pearson(0, 10, 0.95)[1], 0.3084971, places=6)
        # qt(0.975, c(2, 9, 30)) and qnorm(0.975)
        for df, want in ((2, 4.302653), (9, 2.262157), (30, 2.042272)):
            self.assertAlmostEqual(event_stats.t_ppf(0.975, df), want, places=5)
        self.assertAlmostEqual(event_stats.z_ppf(0.975), 1.959964, places=5)
        wl, wh = event_stats.wilson(3, 20, 0.95)
        self.assertAlmostEqual(wl, 0.05236875, places=6)
        self.assertAlmostEqual(wh, 0.36041886, places=6)


class EventTableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        rng = np.random.default_rng(3)
        rows = []
        # Two spawners on a fixed 2.5 s timer (150 frames at 60 fps), offset from each other.
        for ent, start in (("A", 30), ("B", 95)):
            rows += [{"frame": start + 150 * i, "event": "spawn", "entity": ent} for i in range(8)]
        # An attack on a random 1.0-2.0 s interval.
        f = 40
        for _ in range(25):
            rows.append({"frame": f, "event": "attack", "entity": "boss"})
            f += int(rng.integers(60, 121))
        # 40 kills, 6 drops; loot column on kills.
        for i in range(40):
            rows.append({"frame": 2000 + 30 * i, "event": "kill", "loot": "rare" if i % 10 == 3 else "common"})
            if i % 7 == 0 and i < 42:
                rows.append({"frame": 2001 + 30 * i, "event": "drop"})
        # A boss state machine: idle (60 f) -> windup (24 f) -> attack (12 f) -> recover (36 f) -> idle ...
        f = 4000
        for _ in range(6):
            for st, dur in (("idle", 60), ("windup", 24), ("attack_state", 12), ("recover", 36)):
                rows.append({"frame": f, "event": st, "entity": "boss"})
                f += dur
        # XP per level: 100 * 1.15^(level - 1)
        for lv in range(1, 11):
            rows.append({"frame": 6000 + lv, "event": "level_up", "xp": round(100 * 1.15 ** (lv - 1), 2)})
        with open(self.dir / "events.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["frame", "event", "entity", "loot", "xp"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
        self.rows = rows

    def tearDown(self):
        self.tmp.cleanup()

    def stats(self, *args, code=0):
        proc = run("event_stats.py", self.dir / "events.csv", "--fps", "60", *args, "--json")
        self.assertEqual(proc.returncode, code, proc.stderr)
        return json.loads(proc.stdout)

    def test_fixed_and_random_intervals(self):
        rep = self.stats("--intervals", "spawn", "--by", "entity", "--intervals", "attack")
        spawn, attack = rep["intervals"]
        self.assertEqual(spawn["gaps"], 14)  # 7 per spawner, never across spawners
        self.assertAlmostEqual(spawn["mean_s"], 2.5, places=6)
        self.assertEqual(spawn["pattern"], "fixed")
        attack_gaps = [b["frame"] - a["frame"] for a, b in zip([r for r in self.rows if r["event"] == "attack"],
                                                               [r for r in self.rows if r["event"] == "attack"][1:])]
        self.assertAlmostEqual(attack["mean_s"], sum(attack_gaps) / len(attack_gaps) / 60, places=5)
        self.assertEqual(attack["pattern"], "variable")
        self.assertAlmostEqual(attack["min_s"], min(attack_gaps) / 60, places=5)
        self.assertTrue(any("cooldown" in n for n in attack["notes"]))
        # The 95% interval half-width is t(0.975, n-1) * sd / sqrt(n), combined with the frame quantization.
        n, sd = attack["gaps"], attack["sd_s"]
        want = math.hypot(event_stats.t_ppf(0.975, n - 1) * sd / math.sqrt(n), (1 / 60) / math.sqrt(n))
        self.assertAlmostEqual(attack["mean_ci_halfwidth_s"], want, places=4)
        metrics = {m["metric"]: m for m in rep["measurements"]}
        self.assertEqual(metrics["event_interval_spawn"]["value"], 2.5)

    def test_rates_are_ranges(self):
        rep = self.stats("--rate", "drop/kill", "--rate", "kill:loot=rare", "--plan-halfwidth", "0.05")
        drop, rare = rep["rates"]
        self.assertEqual((drop["successes"], drop["trials"]), (6, 40))
        lo, hi = event_stats.clopper_pearson(6, 40, 0.95)
        self.assertAlmostEqual(drop["interval"][0], lo, places=5)
        self.assertAlmostEqual(drop["interval"][1], hi, places=5)
        self.assertEqual((rare["successes"], rare["trials"]), (4, 40))
        self.assertIn("trials_needed", drop)
        m = next(x for x in rep["measurements"] if x["metric"] == "rate_drop_per_kill")
        self.assertAlmostEqual(m["value"], (lo + hi) / 2, places=5)
        self.assertAlmostEqual(m["uncertainty"], (hi - lo) / 2, places=5)
        self.assertNotIn("15%", json.dumps(rep))

    def test_three_in_twenty_is_never_fifteen_percent(self):
        proc = run("event_stats.py", "--counts", "3/20")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("3 of 20", proc.stdout)
        self.assertIn("0.0321..0.3789", proc.stdout)
        self.assertNotIn("15", proc.stdout)
        self.assertIn("ASSUMED", proc.stdout)

    def test_state_machine(self):
        rep = self.stats("--states", "idle,windup,attack_state,recover,stagger", "--by", "entity")
        s = rep["states"]
        tr = {(t["from"], t["to"]): t["count"] for t in s["transitions"]}
        self.assertEqual(tr[("idle", "windup")], 6)
        self.assertEqual(tr[("recover", "idle")], 5)
        self.assertAlmostEqual(s["dwell"]["windup"]["mean_s"], 24 / 60, places=5)
        self.assertAlmostEqual(s["dwell"]["attack_state"]["mean_s"], 12 / 60, places=5)
        self.assertTrue(any("stagger" in n for n in s["notes"]))

    def test_progression_series(self):
        rep = self.stats("--series", "level_up:xp")
        sr = rep["series"][0]
        self.assertEqual(sr["best"], "exponential")
        best = sr["fits"][0]
        self.assertAlmostEqual(best["params"]["ratio"], 1.15, places=3)
        self.assertAlmostEqual(best["params"]["a"], 100 / 1.15, delta=0.5)

    def test_ledger_import_and_bad_input(self):
        out = self.dir / "stats.json"
        self.stats("--rate", "drop/kill", "--intervals", "spawn", "--by", "entity", "--out", out)
        run("breakdown_init.py", self.dir, "--game", "T")
        ev = run("ledger.py", "add-evidence", self.dir / "remake", "--type", "video", "--title", "loot run", "--source", "l.mp4",
                 "--analysis", "event table").stdout.strip()
        proc = run("ledger.py", "import", self.dir / "remake", out, "--evidence", ev)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ms = json.loads((self.dir / "remake" / "measurements.json").read_text())["measurements"]
        rate = next(m for m in ms if m["metric"] == "rate_drop_per_kill")
        self.assertEqual((rate["successes"], rate["trials"]), (6, 40))
        self.assertEqual(len(rate["interval"]), 2)
        run("ledger.py", "targets", self.dir / "remake")
        self.assertNotIn("rate_drop_per_kill", json.loads((self.dir / "remake" / "targets.json").read_text())["metrics"])
        self.assertEqual(run("event_stats.py", "--counts", "5/3").returncode, 2)
        self.assertEqual(run("event_stats.py", "--counts", "x").returncode, 2)
        self.assertEqual(run("event_stats.py").returncode, 2)
        (self.dir / "bad.csv").write_text("time,what\n1,spawn\n")
        self.assertEqual(run("event_stats.py", self.dir / "bad.csv").returncode, 2)
        self.assertEqual(run("event_stats.py", self.dir / "events.csv").returncode, 2)  # frames without --fps
        self.assertEqual(run("event_stats.py", self.dir / "events.csv", "--fps", "60", "--rate", "kill/drop").returncode, 2)


if __name__ == "__main__":
    unittest.main()
