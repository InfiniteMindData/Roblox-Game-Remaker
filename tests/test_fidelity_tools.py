"""Tests for pose_track, overlay, studio_snippets and the offline lint config."""

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
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "roblox-game-remaker"
SCRIPTS = SKILL / "scripts"
TEMPLATE = SKILL / "assets" / "rojo-template"
SAMPLE = SKILL / "examples" / "04-sample-workspace" / "remake"
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
LUNE_PRELUDE = ('local roblox = require("@lune/roblox"); local game = roblox.Instance.new("DataModel"); '
                "local Instance, Vector3, CFrame, Color3, Enum = roblox.Instance, roblox.Vector3, roblox.CFrame, roblox.Color3, roblox.Enum\n")


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=600)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not installed")
class PoseTrackTests(unittest.TestCase):
    def test_leg_angles_and_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            rng = np.random.default_rng(5)
            bg = (rng.random((360, 480, 3)) * 60 + 40).astype(np.uint8)
            marks = {k: (rng.random((14, 14, 3)) * 255).astype(np.uint8) for k in ("hip", "knee", "foot")}
            truth, seq = [], d / "seq"
            seq.mkdir()
            for i in range(90):
                ph = 2 * math.pi * (i / 60) / 0.5  # 0.5 s cycle = 30 frames
                thigh = 30 * math.sin(ph)
                bend = 20 + 20 * (1 + math.sin(ph - 1.0))
                hip = (240, 120)
                knee = (hip[0] + 90 * math.sin(math.radians(thigh)), hip[1] + 90 * math.cos(math.radians(thigh)))
                shin = thigh - bend
                foot = (knee[0] + 90 * math.sin(math.radians(shin)), knee[1] + 90 * math.cos(math.radians(shin)))
                img = bg.copy()
                for name, (x, y) in (("hip", hip), ("knee", knee), ("foot", foot)):
                    x, y = int(round(x)), int(round(y))
                    img[y - 7:y + 7, x - 7:x + 7] = marks[name]
                Image.fromarray(img).save(seq / f"f{i:04d}.png")
                truth.append((thigh, 180 - bend, foot))
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "60", "-i", str(seq / "f%04d.png"), "-c:v", "ffv1",
                            str(d / "leg.mkv")], check=True)
            run("extract_frames.py", d / "leg.mkv", "--out", d / "ex", "--mode", "all")
            f0 = truth[0][2]
            proc = run("pose_track.py", d / "ex" / "manifest.json", "--point", "hip=240,120", "--point", "knee=240,210",
                       "--point", f"foot={round(f0[0])},{round(f0[1])}", "--patch", "14", "--joint", "knee=hip,knee,foot",
                       "--segment", "thigh=hip,knee", "--cycle", "foot.x", "--out", d / "pose.json", "--table", d / "keys.md")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            pose = json.loads((d / "pose.json").read_text())
            thigh_err = max(abs(r["thigh"] - t[0]) for r, t in zip(pose["samples"], truth))
            knee_err = max(abs(r["knee"] - t[1]) for r, t in zip(pose["samples"], truth))
            self.assertLess(thigh_err, 1.5)
            self.assertLess(knee_err, 2.0)
            self.assertAlmostEqual(pose["cycle"]["period_frames"], 30, delta=0.5)
            self.assertIn("| frame | t (s) | key | knee | thigh |", (d / "keys.md").read_text())

    def test_rejects_unknown_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            Image.new("RGB", (64, 64)).save(d / "a.png")
            (d / "manifest.json").write_text(json.dumps({"frames": [{"index": i, "pts_time": i / 60, "file": "a.png"} for i in range(3)]}))
            proc = run("pose_track.py", d / "manifest.json", "--point", "a=30,30", "--joint", "k=a,b,c")
            self.assertEqual(proc.returncode, 2)
            self.assertIn("unknown point", proc.stderr)


class OverlayTests(unittest.TestCase):
    def test_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            a = np.zeros((40, 60, 3), np.uint8)
            b = np.full((80, 120, 3), 255, np.uint8)  # different size: resized to the reference
            Image.fromarray(a).save(d / "ref.png")
            Image.fromarray(b).save(d / "rec.png")
            for mode in ("blend", "diff", "checker", "wipe"):
                proc = run("overlay.py", mode, d / "ref.png", d / "rec.png", "--out", d / f"{mode}.png")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                with Image.open(d / f"{mode}.png") as im:
                    self.assertEqual(im.size, (60, 40))
            px = np.asarray(Image.open(d / "blend.png"))[20, 30]
            self.assertTrue(all(120 <= v <= 135 for v in px))
            chk = np.asarray(Image.open(d / "checker.png"))
            self.assertEqual(int(chk[0, 0, 0]), 0)
            self.assertEqual(run("overlay.py", "blend", d / "ref.png", d / "rec.png", "--alpha", "2", "--out", d / "x.png").returncode, 2)
            frames = []
            for i in range(4):
                im = np.zeros((40, 60, 3), np.uint8)
                im[10:20, 5 + 10 * i:15 + 10 * i] = 255
                Image.fromarray(im).save(d / f"o{i}.png")
                frames.append({"index": i, "pts_time": i / 60, "file": f"o{i}.png"})
            (d / "manifest.json").write_text(json.dumps({"frames": frames}))
            self.assertEqual(run("overlay.py", "onion", d / "manifest.json", "--out", d / "onion.png").returncode, 0)


class StudioSnippetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def layout(self):
        layout = {"unit": "m", "parts": [
            {"name": "Floor", "size": [20, 0.5, 20], "position": [0, -0.25, 0], "color": "#6E8B5A", "material": "Grass"},
            {"name": "Platform", "size": [3, 0.5, 3], "position": [5, 1.5, 0], "rotation": [0, 45, 0]}],
            "spawn": [0, 0.5, 0]}
        (self.dir / "layout.json").write_text(json.dumps(layout))
        return self.dir / "layout.json"

    def test_greybox_validation(self):
        path = self.layout()
        self.assertEqual(run("studio_snippets.py", "greybox", path, "--out", self.dir / "g.luau").returncode, 2)  # meters need a scale
        bad = json.loads(path.read_text())
        bad["parts"][0]["material"] = "Lava"
        (self.dir / "bad.json").write_text(json.dumps(bad))
        self.assertEqual(run("studio_snippets.py", "greybox", self.dir / "bad.json", "--out", self.dir / "g.luau",
                             "--studs-per-meter", "3.5714").returncode, 2)

    @unittest.skipUnless(shutil.which("lune"), "lune not installed")
    def test_greybox_runs_in_lune(self):
        out = self.dir / "greybox.luau"
        self.assertEqual(run("studio_snippets.py", "greybox", self.layout(), "--out", out, "--studs-per-meter", "3.5714").returncode, 0)
        body = out.read_text()
        script = self.dir / "run.luau"
        script.write_text(LUNE_PRELUDE + "local function build()\n" + body + "end\n"
                          "local n = build(); build()\n"
                          'local f = game:GetService("Workspace"):FindFirstChild("Level_Greybox")\n'
                          'print(n, #game:GetService("Workspace"):GetChildren(), f.Platform.Size.X, f.Floor.Material.Name)\n')
        proc = subprocess.run(["lune", "run", str(script)], capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        last = proc.stdout.strip().splitlines()[-1].split()
        self.assertEqual(last[0], "3")  # 2 parts + spawn
        self.assertEqual(last[1], "1")  # rebuilt, not duplicated
        self.assertAlmostEqual(float(last[2]), 3 * 3.5714, places=3)
        self.assertEqual(last[3], "Grass")

    def test_shots_and_apply(self):
        out = self.dir / "Shots.luau"
        self.assertEqual(run("studio_snippets.py", "shots", SAMPLE / "shots.json", "--out", out).returncode, 0)
        self.assertIn('id = "SHOT-HUD"', out.read_text())
        proc = run("studio_snippets.py", "apply-shot", SAMPLE / "shots.json", "--id", "SHOT-HUD")
        self.assertIn("ShotCamera.apply({", proc.stdout)
        self.assertEqual(run("studio_snippets.py", "apply-shot", SAMPLE / "shots.json", "--id", "NOPE").returncode, 2)
        if shutil.which("stylua"):
            self.assertEqual(subprocess.run(["stylua", "--check", "--syntax", "Luau", str(out)], capture_output=True).returncode in (0, 1), True)

    def test_extract_log_and_inputs(self):
        console = self.dir / "console.txt"
        console.write_text(
            "06:01:02.100  REMAKE_SMOKE PASS module Config  -  Server\n"
            "06:01:02.101  REMAKE_SMOKE FAIL Bootstrap ran  -  Server\n"
            "06:01:03.000  unrelated\n"
            '06:01:04.100  REMAKE_INPUT {"e":"began","kc":"ButtonR2","ut":"Gamepad1","pos":[0,0,0.62],"gp":false}  -  Client\n'
            '06:01:04.200  REMAKE_INPUT {"e":"changed","kc":"ButtonR2","ut":"Gamepad1","pos":[0,0,1.0],"gp":false}  -  Client\n')
        proc = run("studio_snippets.py", "extract-log", console, "--out", self.dir / "run.log")
        self.assertEqual(proc.returncode, 1)  # a smoke check failed
        log = (self.dir / "run.log").read_text().splitlines()
        self.assertEqual(log[1], "REMAKE_SMOKE FAIL Bootstrap ran")
        self.assertEqual(len(log), 4)
        table = run("studio_snippets.py", "inputs", self.dir / "run.log").stdout
        self.assertIn("| ButtonR2 | Gamepad1 | began, changed | 0.00, 0.00, 1.00 | no |", table)


@unittest.skipUnless(shutil.which("selene"), "selene not installed")
class OfflineLintTests(unittest.TestCase):
    def test_offline_config_lints_template_and_flags_deprecated_globals(self):
        proc = subprocess.run(["selene", "--config", "selene.offline.toml", "src", "tests/studio"], cwd=TEMPLATE, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.luau"
            bad.write_text("wait(1)\n")
            proc = subprocess.run(["selene", "--config", "selene.offline.toml", str(bad)], cwd=TEMPLATE, capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("`wait` is not defined", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
