"""End-to-end and unit tests for the roblox-game-remaker skill.

Run: python -m unittest discover -s tests -v
Tests that need ffmpeg, Lune, StyLua, Rojo or the Roblox API reference are skipped when the
tool is missing. Set ROBLOX_API_DOCS to creator-docs/content/en-us/reference/engine to enable
the API cross-check tests.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "roblox-game-remaker"
SCRIPTS = SKILL / "scripts"
TEMPLATE = SKILL / "assets" / "rojo-template"
sys.path.insert(0, str(SCRIPTS))

import numpy as np  # noqa: E402
from PIL import Image, ImageEnhance  # noqa: E402

import blender_roblox_export as bre  # noqa: E402
import remake_calc  # noqa: E402
import visual_compare  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def run(script: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd, timeout=600)


def run_json(script: str, *args: str) -> dict:
    proc = run(script, *args, "--json")
    if proc.returncode not in (0, 1):
        raise AssertionError(f"{script} failed: {proc.stderr}")
    return json.loads(proc.stdout)


class ValidatorTests(unittest.TestCase):
    def test_skill_is_valid(self):
        proc = subprocess.run([sys.executable, str(ROOT / "tools" / "validate_skill.py"), str(SKILL), "--strict", "--run-help"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_broken_skill_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad-skill"
            bad.mkdir()
            (bad / "SKILL.md").write_text("---\nname: Bad--Skill\ndescription: x\nfoo: 1\n---\nSee [ref](references/missing.md)\n")
            proc = subprocess.run([sys.executable, str(ROOT / "tools" / "validate_skill.py"), str(bad), "--json"],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1)
            errs = "\n".join(json.loads(proc.stdout)["errors"])
            self.assertIn("unknown field 'foo'", errs)
            self.assertIn("single hyphens", errs)
            self.assertIn("directory name", errs)
            self.assertIn("missing path", errs)


class CalcTests(unittest.TestCase):
    def test_fov(self):
        self.assertAlmostEqual(remake_calc.vfov_from_hfov(90, 16 / 9), 58.7155, places=3)
        v = remake_calc.vfov_from_hfov(103, 21 / 9)
        self.assertAlmostEqual(remake_calc.hfov_from_vfov(v, 21 / 9), 103, places=9)
        self.assertAlmostEqual(remake_calc.vfov_from_dfov(remake_calc.dfov_from_vfov(70, 1.6), 1.6), 70, places=9)

    def test_jump(self):
        d = remake_calc.solve_jump(7.4, 0.383, 0.3, 3.0, 0.05)
        self.assertAlmostEqual(d["takeoff_speed"], 38.6423, places=3)
        self.assertAlmostEqual(d["g_rise"], 100.8937, places=3)
        self.assertAlmostEqual(d["fall_multiplier"], 1.6299, places=3)
        self.assertAlmostEqual(d["release_multiplier"], 4.6851, places=3)
        self.assertFalse(d["roblox"]["CharacterUseJumpPower"])

    def test_accel_and_spring(self):
        a = remake_calc.solve_accel(20, t90=0.18)
        self.assertAlmostEqual(a["linear"]["acceleration"], 100.0, places=6)
        self.assertAlmostEqual(a["exponential"]["tau"], 0.0782, places=4)
        s = remake_calc.solve_spring(0.0, 0.35)
        self.assertEqual(s["damping_ratio"], 1.0)
        self.assertAlmostEqual(s["angular_frequency"], 16.6657, places=2)
        u = remake_calc.solve_spring(0.08, 0.35)
        self.assertAlmostEqual(u["damping_ratio"], 0.6266, places=3)

    def test_cli_rejects_bad_input(self):
        self.assertEqual(run("remake_calc.py", "fov", "--aspect", "16:9").returncode, 2)
        self.assertEqual(run("remake_calc.py", "jump", "--apex", "-1", "--rise-time", "0.3").returncode, 2)


class ColorTests(unittest.TestCase):
    def test_ciede2000_reference_pairs(self):
        pairs = [((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
                 ((50, -1.3802, -84.2814), (50, 0, -82.7485), 1.0000),
                 ((50, 2.5, 0), (73, 25, -18), 27.1492),
                 ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644)]
        for a, b, expected in pairs:
            self.assertAlmostEqual(float(visual_compare.ciede2000(np.array(a, float), np.array(b, float))), expected, places=4)

    def test_lab_of_white_and_black(self):
        lab = visual_compare.srgb_to_lab(np.array([[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]]))
        self.assertAlmostEqual(lab[0, 0], 100, places=3)
        self.assertAlmostEqual(lab[1, 0], 0, places=3)


class ImageToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        rng = np.random.default_rng(0)
        img = (rng.random((240, 320, 3)) * 200 + 20).astype(np.uint8)
        img[100:140, 100:220] = (200, 40, 50)
        Image.fromarray(img).save(self.dir / "ref.png")
        ImageEnhance.Brightness(Image.fromarray(img)).enhance(0.75).save(self.dir / "dark.png")

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_images(self):
        rep = run_json("visual_compare.py", "pair", self.dir / "ref.png", self.dir / "ref.png", "--out", self.dir / "same")
        m = rep["metrics"]
        self.assertAlmostEqual(m["ssim"], 1.0, places=4)
        self.assertAlmostEqual(m["delta_e_mean"], 0.0, places=4)
        self.assertEqual(m["hints"], [])
        for name in ("side_by_side.png", "heatmap.png", "edges.png", "blink.gif", "report.json"):
            self.assertTrue((self.dir / "same" / name).is_file(), name)

    def test_darker_recreation_is_diagnosed(self):
        proc = run("visual_compare.py", "pair", self.dir / "ref.png", self.dir / "dark.png", "--out", self.dir / "dark",
                   "--fail-under-ssim", "0.999", "--json")
        self.assertEqual(proc.returncode, 1)
        m = json.loads(proc.stdout)["metrics"]
        self.assertLess(m["lab_shift"]["dL"], -5)
        self.assertTrue(any("ExposureCompensation" in h for h in m["hints"]))

    def test_mask_and_edges_only(self):
        mask = Image.new("L", (320, 240), 0)
        mask.paste(255, (0, 0, 320, 120))
        mask.save(self.dir / "mask.png")
        rep = run_json("visual_compare.py", "pair", self.dir / "ref.png", self.dir / "dark.png", "--out", self.dir / "m",
                       "--mask", self.dir / "mask.png")
        self.assertEqual(rep["compared_pixels"], 320 * 120)
        rep2 = run_json("visual_compare.py", "pair", self.dir / "ref.png", self.dir / "ref.png", "--out", self.dir / "e", "--edges-only")
        self.assertEqual(rep2["metrics"]["edge_iou"], 1.0)
        self.assertNotIn("ssim", rep2["metrics"])

    def test_batch(self):
        shots = {"shots": [
            {"id": "A", "reference": "ref.png", "recreation": "ref.png", "thresholds": {"ssim": 0.95}},
            {"id": "B", "reference": "ref.png", "recreation": "missing.png"},
        ]}
        (self.dir / "shots.json").write_text(json.dumps(shots))
        proc = run("visual_compare.py", "batch", self.dir / "shots.json", "--out", self.dir / "batch", "--root", self.dir)
        self.assertEqual(proc.returncode, 1)
        proc2 = run("visual_compare.py", "batch", self.dir / "shots.json", "--out", self.dir / "batch2", "--root", self.dir, "--allow-missing")
        self.assertEqual(proc2.returncode, 0, proc2.stdout)
        summary = json.loads((self.dir / "batch2" / "summary.json").read_text())
        self.assertEqual([s["status"] for s in summary["shots"]], ["pass", "missing-capture"])

    def test_palette(self):
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:, :70] = (200, 40, 50)
        img[:, 70:] = (20, 60, 200)
        Image.fromarray(img).save(self.dir / "pal.png")
        rep = run_json("palette_extract.py", self.dir / "pal.png", "--k", "2")
        colors = {c["hex"]: c["share"] for c in rep["colors"]}
        self.assertAlmostEqual(colors["#C82832"], 0.7, delta=0.02)
        self.assertAlmostEqual(colors["#143CC8"], 0.3, delta=0.02)
        pts = run_json("palette_extract.py", self.dir / "pal.png", "--points", "10,10;90,90")
        self.assertEqual([c["hex"] for c in pts["colors"]], ["#C82832", "#143CC8"])


class UiMeasureTests(unittest.TestCase):
    def test_layout_and_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            boxes = {"reference_resolution": [1920, 1080], "scale_rule": "height", "elements": [
                {"name": "Health", "bbox": [48, 980, 420, 36], "anchor": "bottom-left"},
                {"name": "Ammo", "bbox": [1700, 960, 172, 72]},
                {"name": "Cross", "bbox": [944, 524, 32, 32]}]}
            (d / "ref.json").write_text(json.dumps(boxes))
            out = json.loads(run("ui_measure.py", d / "ref.json", "--json").stdout)
            by = {e["name"]: e for e in out["elements"]}
            self.assertEqual(by["Health"]["offset_strategy"]["Position"], {"XScale": 0.0, "XOffset": 48.0, "YScale": 1.0, "YOffset": -64.0})
            self.assertEqual(by["Ammo"]["anchor"], "bottom-right")
            self.assertEqual(by["Cross"]["anchor"], "center")
            self.assertEqual(by["Health"]["scale_strategy"]["Size"]["SizeConstraint"], "RelativeYY")
            luau = run("ui_measure.py", d / "ref.json", "--luau").stdout
            self.assertIn("UDim2.new(0.0, 48.0, 1.0, -64.0)", luau)
            boxes["elements"][0]["bbox"] = [60, 985, 420, 36]
            (d / "rec.json").write_text(json.dumps(boxes))
            self.assertEqual(run("ui_measure.py", "--compare", d / "ref.json", d / "rec.json", "--tolerance", "0.5").returncode, 1)
            self.assertEqual(run("ui_measure.py", "--compare", d / "ref.json", d / "rec.json", "--tolerance", "1.0").returncode, 0)


class BreakdownTests(unittest.TestCase):
    def test_init_never_overwrites_and_template_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            self.assertEqual(run("breakdown_init.py", proj, "--game", "Test Game", "--version", "2.0").returncode, 0)
            intake = proj / "remake" / "00-intake.md"
            self.assertIn("Test Game", intake.read_text())
            intake.write_text("edited")
            run("breakdown_init.py", proj, "--game", "Other")
            self.assertEqual(intake.read_text(), "edited")
            json.loads((proj / "remake" / "evidence.json").read_text())
            self.assertEqual(run("breakdown_check.py", proj / "remake").returncode, 0)
            self.assertEqual(run("breakdown_check.py", proj / "remake", "--strict").returncode, 1)

    def test_sample_workspace_passes_strict(self):
        proc = run("breakdown_check.py", SKILL / "examples" / "04-sample-workspace" / "remake", "--strict", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        data = json.loads(proc.stdout)
        self.assertEqual(data["summary"]["by_status"]["MEASURED"], 3)

    def test_rules_are_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "remake"
            root.mkdir()
            (root / "evidence.json").write_text(json.dumps({"evidence": [
                {"id": "EV-001", "type": "video", "accessible": False, "source": "x"},
                {"id": "EV-002", "type": "wiki", "accessible": True, "source": "y"}]}))
            (root / "measurements.json").write_text(json.dumps({"measurements": [
                {"id": "MS-001", "evidence": ["EV-001"], "value": 1, "unit": "s", "uncertainty": 0.1, "method": "m"}]}))
            cats = ["CTRL", "MOVE", "CAM", "MECH", "CHAR", "ANIM", "UI", "ENV", "VFX", "AUD", "AI", "SYS"]
            text = "## Coverage\n- n/a: " + "\n- n/a: ".join(c + " (test)" for c in cats[1:]) + "\n- n/a: VR (test)\n\n"
            text += ("### CTRL-001: Measured from inaccessible video\n- status: MEASURED\n- evidence: EV-001, MS-001\n"
                     "- value: x = 1 ± 0.1 s\n- roblox: r\n- accept: a\n\n"
                     "### CTRL-002: Verified from a wiki\n- status: VERIFIED\n- evidence: EV-002\n- roblox: r\n- accept: a\n\n"
                     "### CTRL-003: Unknown without question\n- status: UNKNOWN\n- roblox: r\n- accept: a\n\n"
                     "### CTRL-004: Bad id reference\n- status: OBSERVED\n- evidence: EV-999\n- roblox: r\n- accept: a\n")
            (root / "breakdown.md").write_text(text)
            proc = run("breakdown_check.py", root, "--json")
            self.assertEqual(proc.returncode, 1)
            messages = "\n".join(e["message"] for e in json.loads(proc.stdout)["errors"])
            self.assertIn("MS-001: measured from inaccessible evidence EV-001", messages)
            self.assertIn("CTRL-001: MEASURED but none of its evidence is accessible", messages)
            self.assertIn("CTRL-002: VERIFIED needs an authoritative source", messages)
            self.assertIn("CTRL-003: UNKNOWN without an 'open:' question", messages)
            self.assertIn("CTRL-004: cites unknown evidence EV-999", messages)
        self.assertEqual(run("breakdown_check.py", "/nonexistent/remake").returncode, 2)


class MeasureCompareTests(unittest.TestCase):
    def make_log(self, path: Path) -> None:
        dt, lines, batch = 1 / 60, ['x REMAKE_MEASURE {"k":"e","t":0.5,"n":"move_start"}'], []
        g_r, g_f, v0 = 2 * 7.4 / 0.383 ** 2, 2 * 7.4 / 0.3 ** 2, 2 * 7.4 / 0.383
        y, vy, jumping, done, x = 3.0, 0.0, False, False, 0.0
        for i in range(300):
            t = i * dt
            vx = min(20.0, (t - 0.5) / 0.2 * 20.0) if t >= 0.5 else 0.0
            st = 1
            if t >= 3.0 and not jumping and not done:
                jumping, vy = True, v0
                lines.append(f'REMAKE_MEASURE {{"k":"e","t":{t:.4f},"n":"jump"}}')
            if jumping:
                g = g_r if vy > 0 else g_f
                y += vy * dt - 0.5 * g * dt * dt
                vy -= g * dt
                st = 2 if vy > 0 else 3
                if y <= 3.0:
                    y, vy, jumping, done, st = 3.0, 0.0, False, True, 1
                    lines.append(f'REMAKE_MEASURE {{"k":"e","t":{t:.4f},"n":"land"}}')
            x += vx * dt
            batch.append([round(t, 4), round(x, 3), round(y, 4), 0, round(vx, 3), round(vy, 3), 0, st, 1.0 if t >= 0.5 else 0.0])
            if len(batch) == 30:
                lines.append("REMAKE_MEASURE " + json.dumps({"k": "b", "s": batch}))
                batch = []
        path.write_text("\n".join(lines) + "\n")

    def test_metrics_and_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.make_log(d / "run.log")
            targets = {"metrics": {"ground_speed": {"target": 20, "tolerance_pct": 3},
                                   "accel_t90": {"target": 0.18, "tolerance": 0.017},
                                   "jump_apex": {"target": 7.4, "tolerance": 0.3},
                                   "jump_fall_time": {"target": 0.3, "tolerance": 0.017}}}
            (d / "t.json").write_text(json.dumps(targets))
            proc = run("measure_compare.py", d / "run.log", "--targets", d / "t.json", "--json")
            self.assertEqual(proc.returncode, 0, proc.stdout)
            m = json.loads(proc.stdout)["metrics"]
            self.assertAlmostEqual(m["jump_apex"]["mean"], 7.4, delta=0.05)
            targets["metrics"]["jump_apex"]["target"] = 9.0
            targets["metrics"]["decel_t10"] = {"target": 0.1, "tolerance": 0.02}
            (d / "t2.json").write_text(json.dumps(targets))
            proc2 = run("measure_compare.py", d / "run.log", "--targets", d / "t2.json", "--json")
            self.assertEqual(proc2.returncode, 1)
            data = json.loads(proc2.stdout)
            self.assertEqual(data["failed"], ["jump_apex"])
            self.assertEqual(data["missing"], ["decel_t10"])


class BlenderHelperTests(unittest.TestCase):
    def test_r15_hierarchy(self):
        parents = dict(bre.R15_PARENTS)
        parents["Root"] = None
        self.assertEqual(bre.check_r15(parents), [])
        broken = dict(parents)
        broken["LeftHand"] = "UpperTorso"
        del broken["RightFoot"]
        errs = bre.check_r15(broken)
        self.assertTrue(any("LeftHand" in e for e in errs))
        self.assertTrue(any("RightFoot" in e for e in errs))

    def test_limits(self):
        self.assertEqual(bre.check_triangles("m", 20000), [])
        self.assertTrue(bre.check_triangles("m", 20001))
        self.assertEqual(bre.check_influences("m", [[0.5, 0.5], [0.25] * 4]), [])
        self.assertTrue(bre.check_influences("m", [[0.2] * 5]))
        self.assertTrue(bre.check_root_influence("m", ["Root", "Arm"], {"Root"}))
        self.assertEqual(bre.check_cage_names(["Shirt", "Shirt_InnerCage", "Shirt_OuterCage"]), [])
        self.assertTrue(bre.check_cage_names(["Shirt", "Shirt_innercage"]))
        self.assertTrue(bre.check_cage_names(["Pants_OuterCage"]))
        self.assertTrue(bre.check_transform("o", (0.1, 0, 0), (1, 1, 1)))
        self.assertEqual(bre.check_transform("o", (0, 0, 0), (1, 1, 1)), [])


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not installed")
class VideoPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        subprocess.run([sys.executable, str(SKILL / "examples" / "demo" / "make_demo_footage.py"), "--out", str(cls.dir)],
                       check=True, capture_output=True)
        cls.truth = json.loads((cls.dir / "ground_truth.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_probe(self):
        rep = run_json("probe_video.py", self.dir / "demo_jump.mkv")
        self.assertAlmostEqual(rep["fps_nominal"], 60, places=3)
        self.assertFalse(rep["vfr"])
        self.assertEqual(rep["timestamps"]["frames_counted"], 80)

    def test_duplicate_detection(self):
        frames = self.dir / "dup_frames"
        frames.mkdir()
        rng = np.random.default_rng(3)
        for i in range(60):
            Image.fromarray((rng.random((90, 160, 3)) * 255).astype(np.uint8)).save(frames / f"s{i:03d}.png")
        seq = self.dir / "dup_seq"
        seq.mkdir()
        for i in range(120):  # each frame shown twice: 30 fps content in a 60 fps file
            shutil.copy(frames / f"s{i // 2:03d}.png", seq / f"f{i:04d}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "60", "-i", str(seq / "f%04d.png"), "-c:v", "ffv1",
                        str(self.dir / "dup.mkv")], check=True)
        rep = run_json("probe_video.py", self.dir / "dup.mkv", "--dupes")
        self.assertAlmostEqual(rep["effective_fps"], 30, delta=0.6)

    def test_extract_manifest(self):
        out = self.dir / "ex_range"
        proc = run("extract_frames.py", self.dir / "demo_jump.mkv", "--out", out, "--mode", "range", "--start", "10", "--end", "19")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        man = json.loads((out / "manifest.json").read_text())
        self.assertEqual([f["index"] for f in man["frames"]], list(range(10, 20)))
        self.assertAlmostEqual(man["frames"][0]["pts_time"], 10 / 60, delta=0.002)
        self.assertTrue(all((out / f["file"]).is_file() for f in man["frames"]))
        self.assertEqual(run("extract_frames.py", self.dir / "demo_jump.mkv", "--out", out, "--mode", "range",
                             "--start", "0", "--end", "1").returncode, 2, "non-empty output dir must be refused")
        times = self.dir / "ex_times"
        run("extract_frames.py", self.dir / "demo_jump.mkv", "--out", times, "--mode", "times", "--times", "0.5,1.0", "--crop", "0,0,100,50")
        man2 = json.loads((times / "manifest.json").read_text())
        self.assertEqual([f["index"] for f in man2["frames"]], [30, 60])
        with Image.open(times / man2["frames"][0]["file"]) as im:
            self.assertEqual(im.size, (100, 50))

    def test_jump_measurement_matches_truth(self):
        out = self.dir / "ex_jump"
        run("extract_frames.py", self.dir / "demo_jump.mkv", "--out", out, "--mode", "all")
        run("motion_track.py", out / "manifest.json", "--bbox", "288,288,24,24", "--px-per-unit", "20",
            "--analyze", "jump", "--out", self.dir / "jump.json")
        j = json.loads((self.dir / "jump.json").read_text())["jump"]
        t = self.truth["jump"]
        self.assertAlmostEqual(j["apex_height"], t["apex_height"], delta=0.1)
        self.assertAlmostEqual(j["rise_time_s"], t["rise_time_s"], delta=1 / 60)
        self.assertAlmostEqual(j["fall_time_s"], t["fall_time_s"], delta=1 / 60)
        self.assertAlmostEqual(j["g_rise"], t["g_rise"], delta=3)
        self.assertAlmostEqual(j["g_fall"], t["g_fall"], delta=6)
        self.assertTrue(j["asymmetric"])

    def test_run_measurement_with_camera_pan(self):
        out = self.dir / "ex_run"
        run("extract_frames.py", self.dir / "demo_run.mkv", "--out", out, "--mode", "all")
        proc = run("motion_track.py", out / "manifest.json", "--bbox", "90,200,20,20", "--anchor-bbox", "400,20,40,40",
                   "--search", "40", "--px-per-unit", "20", "--analyze", "speed", "--out", self.dir / "run.json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        s = json.loads((self.dir / "run.json").read_text())["speed"]
        t = self.truth["run"]
        self.assertAlmostEqual(s["steady_speed"], t["steady_speed"], delta=0.3)
        self.assertAlmostEqual(s["t90_s"], t["t90_s"], delta=1 / 60)
        self.assertEqual(s["preferred_model"], "linear_ramp")
        self.assertAlmostEqual(s["linear_ramp"]["time_to_full_s"], t["ramp_time_s"], delta=1 / 60)

    def test_contact_sheet(self):
        out = self.dir / "ex_sheet"
        run("extract_frames.py", self.dir / "demo_jump.mkv", "--out", out, "--mode", "every", "--step", "10")
        proc = run("contact_sheet.py", out / "manifest.json", "--out", self.dir / "sheet.png", "--cols", "4", "--tile-width", "100")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with Image.open(self.dir / "sheet.png") as im:
            self.assertEqual(im.width, 400)

    def test_audio_onsets(self):
        rate = 44100
        x = np.random.default_rng(0).normal(0, 0.003, rate * 2)
        for onset in (0.5, 1.0, 1.37):
            i, n = int(onset * rate), int(0.08 * rate)
            x[i:i + n] += 0.6 * np.exp(-np.arange(n) / (0.01 * rate)) * np.sin(2 * np.pi * 900 * np.arange(n) / rate)
        with wave.open(str(self.dir / "clicks.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
        rep = run_json("audio_onsets.py", self.dir / "clicks.wav", "--fps", "60")
        found = [o["t"] for o in rep["onsets"]]
        self.assertEqual(len(found), 3)
        for got, want in zip(found, (0.5, 1.0, 1.37)):
            self.assertAlmostEqual(got, want, delta=0.005)


class DoctorTests(unittest.TestCase):
    def test_doctor_json(self):
        proc = run("doctor.py", ROOT, "--json")
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertIn("capabilities", data)
        self.assertIn("ffmpeg", data["tools"])


@unittest.skipUnless(shutil.which("lune"), "lune not installed")
class LuauUnitTests(unittest.TestCase):
    def test_lune_specs(self):
        proc = subprocess.run(["lune", "run", "tests/lune/run.luau"], cwd=TEMPLATE, capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("0 failed", proc.stdout)


@unittest.skipUnless(shutil.which("stylua"), "stylua not installed")
class LuauFormatTests(unittest.TestCase):
    def test_stylua_check(self):
        proc = subprocess.run(["stylua", "--check", "src", "tests"], cwd=TEMPLATE, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


@unittest.skipUnless(shutil.which("rojo"), "rojo not installed")
class RojoBuildTests(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "remake.rbxlx"
            proc = subprocess.run(["rojo", "build", "default.project.json", "-o", str(out)], cwd=TEMPLATE, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            text = out.read_text(encoding="utf-8")
            for name in ("Bootstrap", "Main", "MovementFeel", "Config", "MeasurementHarness"):
                self.assertIn(f">{name}<", text)


@unittest.skipUnless(os.environ.get("ROBLOX_API_DOCS"), "set ROBLOX_API_DOCS to creator-docs/content/en-us/reference/engine")
class ApiCrossCheckTests(unittest.TestCase):
    def test_skill_matches_api_reference(self):
        proc = subprocess.run([sys.executable, str(ROOT / "tools" / "check_roblox_api.py"), "--docs", os.environ["ROBLOX_API_DOCS"],
                               str(SKILL), "--strict"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_checker_catches_mistakes(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.luau"
            bad.write_text('local Lighting = game:GetService("Lighting")\n'
                           'Lighting.Technolgy = Enum.Technology.Future\n'
                           'local h = Enum.HumanoidStateType.Jumpin\n'
                           'local p = Instance.new("BodyVelocity")\n')
            proc = subprocess.run([sys.executable, str(ROOT / "tools" / "check_roblox_api.py"), "--docs", os.environ["ROBLOX_API_DOCS"],
                                   str(bad), "--json"], capture_output=True, text=True)
            data = json.loads(proc.stdout)
            msgs = "\n".join(i["message"] for i in data["errors"] + data["warnings"])
            self.assertIn("Lighting.Technolgy: no such member", msgs)
            self.assertIn("Enum.HumanoidStateType.Jumpin", msgs)
            self.assertIn("BodyVelocity is deprecated", msgs)


if __name__ == "__main__":
    unittest.main()
