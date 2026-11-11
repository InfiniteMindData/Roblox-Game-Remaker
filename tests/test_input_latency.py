"""Input response time: event_stats --latency (footage) -> ledger -> targets -> measure_compare (harness)."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "roblox-game-remaker"
SCRIPTS = SKILL / "scripts"
TEMPLATE = SKILL / "assets" / "rojo-template"


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=600)


def harness_log(path: Path, presses):
    """presses: (key, frames, frame_duration); frames -1 = no visible change before the timeout."""
    lines = ['12:00:00.000  REMAKE_MEASURE {"k":"e","t":0,"n":"session"}  -  Client']
    for i, (key, f, fd) in enumerate(presses):
        lines.append(f'12:00:01.{i:03d}  REMAKE_MEASURE {json.dumps({"k": "l", "t": 1 + i, "in": key, "f": f, "fd": fd, "dt": 0.02})}  -  Client')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class InputLatencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_harness_latency_metric(self):
        log = harness_log(self.dir / "run.log", [("Space", 2, 1 / 60)] * 4 + [("Space", 3, 1 / 60), ("Space", -1, 1 / 60), ("W", 6, 1 / 60)])
        targets = {"metrics": {"input_latency": {"target": 0.04, "tolerance": 0.017}}}
        (self.dir / "t.json").write_text(json.dumps(targets), encoding="utf-8")
        proc = run("measure_compare.py", log, "--targets", self.dir / "t.json", "--latency-key", "Space", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        rep = json.loads(proc.stdout)
        m = rep["metrics"]["input_latency"]
        self.assertEqual(m["n"], 5)  # the timeout is counted, not averaged
        self.assertAlmostEqual(m["mean"], (4 * 2 + 3) / 5 / 60, places=4)
        self.assertAlmostEqual(rep["metrics"]["input_latency_frames"]["mean"], 2.2, places=4)
        self.assertEqual(rep["latency_timeouts"], 1)
        targets["metrics"]["input_latency"]["target"] = 0.1
        (self.dir / "t.json").write_text(json.dumps(targets), encoding="utf-8")
        self.assertEqual(run("measure_compare.py", log, "--targets", self.dir / "t.json").returncode, 1)

    def test_footage_latency_to_targets_to_harness(self):
        rows = []
        for i, delay in enumerate((3, 4, 3, 3, 4, 3, 3, 3)):  # frames at 60 fps from the overlay press to the first move
            rows += [{"frame": 100 + 90 * i, "event": "press"}, {"frame": 100 + 90 * i + delay, "event": "move"}]
        rows.append({"frame": 900, "event": "press"})  # a press with no response
        rows.append({"frame": 950, "event": "press"})
        rows.append({"frame": 953, "event": "move"})
        with open(self.dir / "latency.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["frame", "event"])
            w.writeheader()
            w.writerows(rows)
        proc = run("event_stats.py", self.dir / "latency.csv", "--fps", "60", "--latency", "press/move", "--json",
                   "--out", self.dir / "lat.json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        st = json.loads(proc.stdout)["latency"][0]
        delays = [3, 4, 3, 3, 4, 3, 3, 3, 3]
        self.assertEqual(st["pairs"], 9)
        self.assertEqual(st["unanswered"], 1)
        self.assertAlmostEqual(st["mean_s"], sum(delays) / len(delays) / 60, places=5)
        self.assertGreaterEqual(st["uncertainty_s"], 1 / 60)  # never finer than a frame
        run("breakdown_init.py", self.dir, "--game", "T")
        remake = self.dir / "remake"
        ev = run("ledger.py", "add-evidence", remake, "--type", "video", "--title", "overlay capture", "--source", "o.mp4",
                 "--analysis", "event table with input overlay").stdout.strip()
        self.assertEqual(run("ledger.py", "import", remake, self.dir / "lat.json", "--evidence", ev).returncode, 0)
        self.assertEqual(run("ledger.py", "targets", remake, "--tier", "A").returncode, 0)
        target = json.loads((remake / "targets.json").read_text(encoding="utf-8"))["metrics"]["input_latency"]
        self.assertAlmostEqual(target["target"], st["mean_s"], places=5)
        good = harness_log(self.dir / "good.log", [("Space", 3, 1 / 60)] * 5)
        slow = harness_log(self.dir / "slow.log", [("Space", 9, 1 / 60)] * 5)
        self.assertEqual(run("measure_compare.py", good, "--targets", remake / "targets.json", "--allow-missing").returncode, 0)
        self.assertEqual(run("measure_compare.py", slow, "--targets", remake / "targets.json", "--allow-missing").returncode, 1)
        self.assertEqual(run("event_stats.py", self.dir / "latency.csv", "--fps", "60", "--latency", "press-move").returncode, 2)
        self.assertEqual(run("event_stats.py", self.dir / "latency.csv", "--fps", "60", "--latency", "move/nothing").returncode, 1)

    def test_template_harness_has_the_latency_mode(self):
        """Static check of the Luau (it was not run in Studio): the mode, its log line and its Config switches exist."""
        harness = (TEMPLATE / "src" / "client" / "DevTools" / "MeasurementHarness.luau").read_text(encoding="utf-8")
        for needle in ('k = "l"', '["in"] = p.key', "RunService.PreRender:Connect", "UserInputService.InputBegan:Connect",
                       'Workspace:GetAttribute("RemakeMeasureLatency")'):
            self.assertIn(needle, harness)
        config = (TEMPLATE / "src" / "shared" / "Remake" / "Config.luau").read_text(encoding="utf-8")
        for needle in ("MeasureLatency = false", "LatencyKeys = {", "LatencyTimeout = 1"):
            self.assertIn(needle, config)


if __name__ == "__main__":
    unittest.main()
