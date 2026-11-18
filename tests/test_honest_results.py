"""A tool must never report "pass", "reliable" or a tight ± for something it did not measure.

Regression tests for the honest-results audit (findings 5, 6, 7, 8, 11, 12 and the probe_video memory
note): checks that were asked for but not computed, missing events and targets, per-trial
acceptance, off-path error, unit conversion before Roblox values, audio stream offsets and variable
frame rates, camera uncertainty and letterboxing, model-conditional fit uncertainty, sparse frame
quantization, aspect-changing UI layouts, masked and local SSIM.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "roblox-game-remaker" / "scripts"
sys.path.insert(0, str(SCRIPTS))

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", timeout=600)


def run_json(script: str, *args) -> tuple[int, dict]:
    p = run(script, *args, "--json")
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{script} printed no JSON (exit {p.returncode}):\n{p.stdout}\n{p.stderr}") from exc


def ffmpeg(*args) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True, capture_output=True)


def write_wav(path: Path, x, sr: int) -> Path:
    with wave.open(str(path), "wb") as f:
        f.setparams((1, 2, sr, 0, "NONE", ""))
        f.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def bursts(sr: int, onsets, length_s: float, seed: int = 42):
    rng = np.random.default_rng(seed)
    x = np.zeros(int(length_s * sr))
    n = int(0.08 * sr)
    burst = 0.7 * rng.uniform(-1, 1, n) * np.exp(-np.arange(n) / (sr * 0.025))
    for o in onsets:
        j = int(round(o * sr))
        x[j:j + n] = burst
    return x


class Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def js(self, name: str, data) -> Path:
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
        return p


# ----------------------------------------------------------------- visual_compare / fidelity_report

def scene(w=640, h=360):
    """A textured scene: gradient sky, checker ground, diagonal lines and a red HUD bar."""
    y, x = np.indices((h, w))
    a = np.stack([30 + x * 100 / w, 70 + y * 100 / h, 120 + x * 60 / w], -1).astype(np.uint8)
    g = y > h * 0.6
    a[g] = np.stack([50 + ((x // 16 + y // 16) % 2) * 50, 80 + ((x // 16) % 2) * 30, 45 + ((y // 16) % 2) * 30], -1)[g]
    im = Image.fromarray(a)
    dr = ImageDraw.Draw(im)
    for i in range(30):
        xx = 60 + i * 18
        dr.line((xx, 100, xx + 30, 215), fill=(200, 170, 140), width=2)
    dr.rectangle((10, 10, 120, 24), fill=(210, 30, 30))
    return np.array(im)


class VisualCompareHonesty(Tmp):
    def save(self, name, a) -> Path:
        p = self.dir / name
        Image.fromarray(a.astype(np.uint8)).save(p)
        return p

    def test_edges_only_with_an_ssim_threshold_fails_instead_of_passing(self):
        ref = self.save("ref.png", np.full((64, 64, 3), 100))
        b = np.full((64, 64, 3), 100)
        b[:, 32:] = 200
        rec = self.save("rec.png", b)
        code, rep = run_json("visual_compare.py", "pair", ref, rec, "--edges-only", "--fail-under-ssim", ".99",
                             "--out", self.dir / "o")
        self.assertEqual(rep["status"], "fail")
        self.assertEqual(code, 1)
        self.assertTrue(any("ssim was not measured" in f for f in rep["failures"]), rep["failures"])

    def test_masked_pixels_do_not_change_ssim(self):
        r = np.full((256, 256, 3), 100)
        q = r.copy()
        yy, xx = np.indices((256, 128))
        q[:, 128:] = np.where(((xx + yy) % 2)[..., None], 255, 0)
        m = np.zeros((256, 256))
        m[:, 128:] = 255
        code, rep = run_json("visual_compare.py", "pair", self.save("r.png", r), self.save("q.png", q),
                             "--mask", self.save("m.png", m), "--fail-under-ssim", ".9999", "--out", self.dir / "o")
        self.assertEqual(rep["metrics"]["ssim"], 1.0)  # was 0.97 before masked windows were normalized
        self.assertEqual(code, 0)

    def test_a_small_icon_changed_completely_is_caught_by_local_ssim(self):
        a = scene()
        b = a.copy()
        b[40:72, 300:332] = [30, 210, 30]  # a 32x32 HUD icon replaced by a flat green square
        ref, rec = self.save("ref.png", a), self.save("rec.png", b)
        code, rep = run_json("visual_compare.py", "pair", ref, rec, "--fail-under-ssim", ".98", "--out", self.dir / "o")
        m = rep["metrics"]
        self.assertGreater(m["ssim"], 0.98)  # the global figure alone passes
        self.assertLess(m["local_ssim"], 0.75)
        x, y, w, h = m["local_ssim_box"]
        self.assertTrue(300 - w <= x <= 332 and 40 - h <= y <= 72, m["local_ssim_box"])
        self.assertTrue(any("small region differs strongly" in n for n in rep["notes"]), rep["notes"])
        code, rep = run_json("visual_compare.py", "pair", ref, rec, "--fail-under-ssim", ".98",
                             "--fail-under-local-ssim", ".8", "--out", self.dir / "o2")
        self.assertEqual((code, rep["status"]), (1, "fail"))
        code, rep = run_json("visual_compare.py", "pair", ref, ref, "--fail-under-local-ssim", ".8", "--out", self.dir / "o3")
        self.assertEqual((code, rep["status"]), (0, "pass"))

    def test_failed_batch_stays_failed_in_the_scorecard(self):
        flat = self.save("flat.png", np.full((128, 128, 3), 128))
        pat = np.zeros((128, 128, 3))
        pat[:, :64] = 255
        pattern = self.save("pattern.png", pat)
        # The shots file lives outside the remake folder: fidelity_report cannot read thresholds from
        # remake/shots.json, so they must travel with the batch result.
        shots = self.js("elsewhere/batch.json", {"shots": [{"id": "main", "reference": str(flat), "recreation": str(pattern),
                                                           "thresholds": {"ssim": 0.98}}]})
        remake = self.dir / "remake"
        (remake / "diff").mkdir(parents=True)
        p = run("visual_compare.py", "batch", shots, "--out", remake / "diff" / "batch")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        summary = json.loads((remake / "diff" / "batch" / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["shots"][0]["thresholds"], {"ssim": 0.98})
        code, rep = run_json("fidelity_report.py", remake, "--fail-on-fail", "--dry-run")
        self.assertEqual(rep["systems"]["shot:main"]["status"], "fail")  # was "info"
        self.assertEqual(rep["counts"]["fail"], 1)
        self.assertEqual(code, 1)  # was 0

    def test_two_references_with_the_same_file_name_are_scored_separately(self):
        t = np.arange(0, 5.001, 1 / 30)

        def track(speed, start):
            u = speed * np.maximum(t - start, 0)
            return {"tool": "motion_track", "unit": "studs",
                    "samples": [{"t": float(a), "u": float(b), "v": 0.0, "index": i} for i, (a, b) in enumerate(zip(t, u))]}

        remake = self.dir / "remake"
        (remake / "diff").mkdir(parents=True)
        codes = []
        for i, (speed, ok) in enumerate(((10, True), (12, False))):
            ref = self.js(f"action{i}/manifest.json", track(10, 1))
            rec = self.js(f"rec{i}.json", track(speed, 1))
            codes.append(run("clip_compare.py", ref, rec, "--tol-rms", ".1", "--out", remake / "diff" / f"action{i}.json").returncode)
        self.assertEqual(codes, [0, 1])
        code, rep = run_json("fidelity_report.py", remake, "--fail-on-fail", "--dry-run")
        clips = {k: v["status"] for k, v in rep["systems"].items() if k.startswith("clip:")}
        self.assertEqual(sorted(clips.values()), ["fail", "pass"], clips)  # one used to overwrite the other
        self.assertEqual(code, 1)


# ----------------------------------------------------------------- clip_compare

class ClipCompareHonesty(Tmp):
    def ground(self, name, lateral):
        t = np.arange(0, 5 + 1 / 120, 1 / 60)
        dt = np.maximum(t - 1, 0)
        z, x = 10 * dt, lateral * np.sin(np.pi * dt / 4)
        return self.js(name, {"tool": "camera_solve", "unit": "studs",
                              "track": {"samples": [{"t": float(a), "X": float(b), "Z": float(c)} for a, b, c in zip(t, x, z)]}})

    def test_a_sideways_detour_fails(self):
        straight, curved = self.ground("straight.json", 0), self.ground("curved.json", 10)
        code, rep = run_json("clip_compare.py", straight, curved, "--tol-rms", ".1", "--tol-max", ".1")
        self.assertEqual(rep["status"], "fail")
        self.assertEqual(code, 1)
        self.assertIn("lateral", rep["per_axis"])
        self.assertAlmostEqual(rep["per_axis"]["lateral"]["max"], 10.0, delta=0.05)
        self.assertEqual(rep["per_axis"]["along"]["rms"], 0.0)  # the old measure saw nothing
        code, rep = run_json("clip_compare.py", straight, straight, "--tol-rms", ".1", "--tol-max", ".1")
        self.assertEqual((code, rep["status"]), (0, "pass"))

    def test_a_reference_event_missing_from_the_build_fails(self):
        def track(name, fps, vertical):
            t = np.arange(0, 5 + 0.5 / fps, 1 / fps)
            dt = np.maximum(t - 1, 0)
            v = np.maximum(0, 8 * dt - 8 * dt * dt) if vertical else np.zeros_like(t)
            return self.js(name, {"tool": "motion_track", "unit": "studs",
                                  "samples": [{"t": float(a), "u": float(b), "v": float(c), "index": i}
                                              for i, (a, b, c) in enumerate(zip(t, dt, v))]})

        jump, flat = track("jump.json", 60, True), track("flat.json", 30, False)
        code, rep = run_json("clip_compare.py", jump, flat, "--tol-event", ".05")
        self.assertEqual((code, rep["status"]), (1, "fail"))
        self.assertEqual(rep["events"]["apex"]["missing_in"], "recreation")
        self.assertTrue(any(f.startswith("apex:") for f in rep["failures"]), rep["failures"])
        code, rep = run_json("clip_compare.py", jump, flat)  # no event tolerance: not judged, but said
        self.assertTrue(any("apex" in w for w in rep["warnings"]), rep["warnings"])


# ----------------------------------------------------------------- measure_compare

def log_lines(rows) -> str:
    return "".join("REMAKE_MEASURE " + json.dumps(r) + "\n" for r in rows)


class MeasureCompareHonesty(Tmp):
    def log(self, name, rows) -> Path:
        p = self.dir / name
        p.write_text(log_lines(rows), encoding="utf-8")
        return p

    def ramp(self, name, hold):
        rows = [{"k": "e", "t": 0, "n": "move_start"}, {"k": "e", "t": hold + 0.01, "n": "move_stop"}]
        rows += [{"k": "s", "t": float(t), "p": [0, 0, 0], "v": [float(min(8 * t, 16)), 0, 0], "st": "Running", "mv": 1}
                 for t in np.arange(0, hold + 0.001, 1 / 60)]
        return self.log(name, rows)

    def test_a_required_target_with_no_data_is_missing(self):
        rows = [{"k": "e", "t": 0, "n": "move_start"}]
        rows += [{"k": "s", "t": float(t), "p": [16 * t, 0, 0], "v": [16, 0, 0], "st": "Running", "mv": 1}
                 for t in np.arange(0, 2, 1 / 60)]
        log = self.log("constant.log", rows)
        targets = self.js("t.json", {"metrics": {"ground_speed": {"target": 16, "tolerance": 0.1},
                                                 "ground_speed[run]": {"target": 20, "tolerance": 0.1},
                                                 "jump_apexx": {"target": 7, "tolerance": 0.1}}})
        code, rep = run_json("measure_compare.py", log, "--targets", targets)
        self.assertEqual((code, rep["status"], rep["pass"]), (1, "fail", False))
        self.assertEqual(sorted(rep["missing"]), ["ground_speed[run]", "jump_apexx"])
        self.assertEqual(rep["metrics"]["jump_apexx"]["status"], "unknown-metric")
        self.assertEqual(rep["metrics"]["ground_speed"]["status"], "pass")

    def test_trials_of_4_and_12_do_not_average_into_a_pass_against_8(self):
        rows = []
        for k, apex in enumerate((4, 12)):
            T, base = 0.4, 3 * k
            g = 2 * apex / T ** 2
            rows.append({"k": "s", "t": base - 0.1, "p": [0, 0, 0], "v": [0, 0, 0], "st": "Running", "mv": 0})
            rows.append({"k": "e", "t": base, "n": "jump"})
            rows += [{"k": "s", "t": float(base + tt), "p": [0, float(g * T * tt - g * tt * tt / 2), 0],
                      "v": [0, float(g * T - g * tt), 0], "st": "Freefall", "mv": 0} for tt in np.arange(0, 2 * T + 1e-9, 1 / 60)]
            rows.append({"k": "e", "t": base + 2 * T + 0.01, "n": "land"})
        log = self.log("jumps.log", rows)
        code, rep = run_json("measure_compare.py", log, "--targets", self.js("t.json", {"metrics": {"jump_apex": {"target": 8, "tolerance": 0.5}}}))
        m = rep["metrics"]["jump_apex"]
        self.assertAlmostEqual(m["mean"], 8.0, delta=0.01)
        self.assertEqual((m["status"], m["within"], code), ("fail", 0, 1))
        self.assertIn("only 0 of 2 trials", m["note"])
        # The old mean-only judgement stays available when it is what the target means.
        code, rep = run_json("measure_compare.py", log, "--targets",
                             self.js("t2.json", {"metrics": {"jump_apex": {"target": 8, "tolerance": 0.5, "aggregate": "mean"}}}))
        self.assertEqual((rep["metrics"]["jump_apex"]["status"], code), ("pass", 0))

    def test_a_run_that_never_reaches_top_speed_reports_no_steady_speed(self):
        code, rep = run_json("measure_compare.py", self.ramp("short.log", 1.5))
        self.assertEqual(rep["metrics"]["ground_speed"]["status"], "not-observed")  # was 8 (truth 16)
        self.assertEqual(rep["metrics"]["accel_t90"]["status"], "not-observed")  # was 0.9 (truth 1.8)
        self.assertTrue(any("never reached a steady speed" in w for w in rep["warnings"]), rep["warnings"])
        code, rep = run_json("measure_compare.py", self.ramp("slow.log", 5.0))
        self.assertAlmostEqual(rep["metrics"]["ground_speed"]["mean"], 16.0, delta=0.01)
        self.assertAlmostEqual(rep["metrics"]["accel_t90"]["mean"], 1.8, delta=0.02)
        self.assertEqual(rep["warnings"], [])


# ----------------------------------------------------------------- remake_calc

class RemakeCalcUnits(unittest.TestCase):
    def test_meters_are_converted_to_studs_before_roblox_values(self):
        code, d = run_json("remake_calc.py", "jump", "--apex", "1.4", "--rise-time", "0.4", "--unit", "meters")
        self.assertEqual(code, 0)
        r = d["roblox"]
        self.assertAlmostEqual(r["CharacterJumpHeight"], 5.0, places=6)  # was 1.4
        self.assertAlmostEqual(r["Workspace.Gravity"], 62.5, places=6)  # was 17.5
        self.assertAlmostEqual(r["equivalent_JumpPower"], 25.0, places=6)
        p = run("remake_calc.py", "jump", "--apex", "1.4", "--rise-time", "0.4", "--unit", "meters", "--luau")
        self.assertIn("Gravity = 62.500", p.stdout)
        self.assertIn("JumpApex = 5.000", p.stdout)
        self.assertNotIn("Workspace.Gravity = 17.5", p.stdout)

    def test_feet_and_custom_scale(self):
        _, d = run_json("remake_calc.py", "jump", "--apex", "1", "--rise-time", "0.5", "--unit", "ft", "--studs-per-meter", "4")
        self.assertAlmostEqual(d["roblox"]["CharacterJumpHeight"], 0.3048 * 4, places=6)

    def test_an_unknown_unit_prints_no_roblox_values(self):
        code, d = run_json("remake_calc.py", "jump", "--apex", "40", "--rise-time", "0.4", "--unit", "px")
        self.assertIsNone(d["roblox"])
        p = run("remake_calc.py", "jump", "--apex", "40", "--rise-time", "0.4", "--unit", "px", "--luau")
        self.assertNotIn("Workspace.Gravity =", p.stdout)
        self.assertNotIn("Gravity = ", p.stdout)

    def test_studs_output_is_unchanged(self):
        _, d = run_json("remake_calc.py", "jump", "--apex", "6.371049949", "--rise-time", "0.254841998")
        self.assertAlmostEqual(d["roblox"]["Workspace.Gravity"], 196.2, places=3)
        self.assertAlmostEqual(d["roblox"]["equivalent_JumpPower"], 50.0, places=3)

    def test_contradictory_accel_times_warn(self):
        p = run("remake_calc.py", "accel", "--top-speed", "16", "--t90", ".18", "--time-to-top", "2")
        self.assertIn("disagree", p.stderr)


# ----------------------------------------------------------------- audio

@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class AudioTiming(Tmp):
    def test_audio_stream_start_offset_is_honoured(self):
        wav = write_wav(self.dir / "b.wav", bursts(48000, (1, 2, 3), 4), 48000)
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=6", "-c:v", "libx264", "-preset", "ultrafast", self.dir / "v.mp4")
        clip = self.dir / "offset clip.mkv"
        ffmpeg("-i", self.dir / "v.mp4", "-itsoffset", "2", "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
               "-c:a", "pcm_s16le", clip)
        _, d = run_json("audio_onsets.py", clip)
        self.assertEqual([round(o["t"], 2) for o in d["onsets"]], [3.0, 4.0, 5.0])  # were 2 s early
        self.assertEqual([o["frame"] for o in d["onsets"]], [90, 120, 150])
        for start in ("1", "2.5"):  # --start before and after the audio begins
            _, d = run_json("audio_onsets.py", clip, "--start", start)
            self.assertEqual(round(d["onsets"][-1]["t"], 2), 5.0, start)
        _, d = run_json("audio_compare.py", "analyze", clip, "--start", "2.5", "--end", "3.5")
        self.assertAlmostEqual(d["features"]["onset_s"], 3.0, delta=0.01)

    def test_variable_frame_rate_uses_real_frame_timestamps(self):
        vfr = self.dir / "vfr.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=160x90:r=60:d=6", "-vf", "select='if(lt(t,3),not(mod(n,2)),1)'",
               "-fps_mode", "vfr", "-c:v", "libx264", "-preset", "ultrafast", vfr)
        wav = write_wav(self.dir / "b.wav", bursts(48000, (1, 4, 5), 6), 48000)
        clip = self.dir / "vfr_a.mkv"
        ffmpeg("-i", vfr, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "pcm_s16le", clip)
        _, d = run_json("audio_onsets.py", clip)
        self.assertEqual(d["frame_mapping"], "timestamps")
        self.assertEqual([o["frame"] for o in d["onsets"]], [30, 150, 210])  # 4 s used to map to 180
        _, d = run_json("audio_onsets.py", clip, "--fps", "45")
        self.assertTrue(any("variable frame rate" in w for w in d["warnings"]), d["warnings"])

    def test_identical_bursts_are_all_found_whatever_the_hop_phase(self):
        wav = write_wav(self.dir / "identical.wav", bursts(22050, range(1, 20), 20), 22050)
        _, d = run_json("audio_onsets.py", wav)
        self.assertEqual([round(o["t"]) for o in d["onsets"]], list(range(1, 20)))  # the one at 3 s was dropped

    def test_bad_hop_is_a_clean_error(self):
        wav = write_wav(self.dir / "t.wav", bursts(22050, (0.5,), 1), 22050)
        for args in (("--hop", "0"), ("--window", "0"), ("--hop", "600", "--window", "512")):
            p = run("audio_onsets.py", wav, *args)
            self.assertEqual(p.returncode, 2, args)
            self.assertNotIn("Traceback", p.stderr)
        p = run("audio_compare.py", "analyze", wav, "--hop", "0")
        self.assertEqual(p.returncode, 2)
        self.assertNotIn("Traceback", p.stderr)

    def test_peak_dbfs_is_the_sample_peak(self):
        sr = 22050
        t = np.arange(3 * sr) / sr
        tone = write_wav(self.dir / "tone.wav", 0.5 * np.sin(2 * np.pi * 440 * t) * ((t >= 0.5) & (t < 1.5)), sr)
        _, d = run_json("audio_compare.py", "analyze", tone)
        f = d["features"]
        self.assertAlmostEqual(f["peak_dbfs"], 20 * math.log10(0.5), delta=0.1)  # was -9 (an RMS window)
        self.assertAlmostEqual(f["envelope_peak_dbfs"], 20 * math.log10(0.5 / math.sqrt(2)), delta=0.2)


# ----------------------------------------------------------------- camera_solve

def project(points, active_h=1080, w=1920, h=1080):
    """Independent pinhole projection: camera 8 studs up, pitch -25, yaw 30 deg, vertical FOV 70 over active_h."""
    pitch, yaw = np.deg2rad([25, 30])
    right = np.array([np.cos(yaw), 0, -np.sin(yaw)])
    forward = np.array([np.sin(yaw) * np.cos(pitch), -np.sin(pitch), np.cos(yaw) * np.cos(pitch)])
    R = np.stack([right, np.cross(right, forward), forward])
    q = (np.asarray(points, float) - [0, 8, 0]) @ R.T
    f = active_h / (2 * np.tan(np.deg2rad(35)))
    return q[:, :2] / q[:, 2:] * f + [w / 2, h / 2]


def corners_arg(pts) -> str:
    return ";".join(f"{x:.7f},{y:.7f}" for x, y in pts)


class CameraSolveHonesty(unittest.TestCase):
    RECT = [[-4, 0, 16], [4, 0, 16], [4, 0, 26], [-4, 0, 26]]

    def test_ground_mode_reports_camera_uncertainty(self):
        c = project(self.RECT)
        code, d = run_json("camera_solve.py", "ground", "--image", "1920x1080", "--corners", corners_arg(c), "--rect", "8x10")
        cam = d["camera_from_rect"]
        self.assertAlmostEqual(cam["vfov_deg"], 70.0, delta=0.01)
        self.assertGreater(cam["uncertainty"]["vfov_deg"], 2.0)  # a 4-corner camera is loosely pinned (was no field)
        self.assertGreater(cam["worst_case"]["vfov_deg"], cam["uncertainty"]["vfov_deg"])
        p = run("camera_solve.py", "ground", "--image", "1920x1080", "--corners", corners_arg(c), "--rect", "8x10", "--luau")
        self.assertIn("vertical FOV ± 2.", p.stdout)

    def test_letterboxed_viewport_gives_the_game_fov(self):
        c = project(self.RECT, active_h=800)
        args = ["ground", "--image", "1920x1080", "--corners", corners_arg(c), "--rect", "8x10"]
        _, d = run_json("camera_solve.py", *args)
        self.assertAlmostEqual(d["camera_from_rect"]["vfov_deg"], 86.78, delta=0.05)  # the whole frame's FOV
        _, d = run_json("camera_solve.py", *args, "--viewport", "0,140,1920,800")
        self.assertAlmostEqual(d["camera_from_rect"]["vfov_deg"], 70.0, delta=0.01)
        self.assertAlmostEqual(d["camera_from_rect"]["pitch_deg"], -25.0, delta=0.01)

    def test_a_third_valid_line_set_does_not_break_a_solvable_camera(self):
        # A frontal camera (yaw 0): world X lines stay parallel in the image (vanishing point at infinity).
        pitch = np.deg2rad(25)
        forward = np.array([0, -np.sin(pitch), np.cos(pitch)])
        right = np.array([1.0, 0, 0])
        R = np.stack([right, np.cross(right, forward), forward])
        f = 540 / np.tan(np.deg2rad(35))

        def p(pt):
            q = (np.asarray(pt, float) - [0, 8, 0]) @ R.T
            return list(q[:2] / q[2] * f + [960, 540])

        def lines(pairs):
            return ";".join(",".join(f"{v:.7f}" for v in p(a) + p(b)) for a, b in pairs)

        A, B, C, D = [-4, 0, 16], [4, 0, 16], [4, 0, 26], [-4, 0, 26]
        X = lines([(A, B), (D, C)])
        Z = lines([(A, D), (B, C)])
        Y = lines([(A, [-4, 4, 16]), (C, [4, 4, 26])])
        code, d = run_json("camera_solve.py", "vanishing", "--image", "1920x1080", f"--lines-x={X}", f"--lines-z={Z}", f"--lines-y={Y}")
        self.assertEqual(code, 0)  # was exit 1
        self.assertAlmostEqual(d["result"]["vfov_deg"], 70.0, delta=0.01)
        self.assertAlmostEqual(d["result"]["pitch_deg"], -25.0, delta=0.01)
        self.assertEqual(d["focal_pairs"], ["z-y"])
        self.assertTrue(any("skipped" in w for w in d["warnings"]))


# ----------------------------------------------------------------- fit_curve / event_stats

class FitAndStatsHonesty(Tmp):
    def csv(self, name, t, y) -> Path:
        p = self.dir / name
        p.write_text("t,y\n" + "".join(f"{a},{b}\n" for a, b in zip(t, y)), encoding="utf-8")
        return p

    def test_a_curve_no_candidate_matches_does_not_get_a_tight_interval(self):
        t = np.arange(-0.2, 1.401, 1 / 60)
        u = np.clip(t, 0, 1)
        _, d = run_json("fit_curve.py", "--csv", self.csv("smooth.csv", t, u * u * (3 - 2 * u)))
        self.assertFalse(d["model_confirmed"])
        self.assertTrue(any("MODEL NOT CONFIRMED" in w for w in d["warnings"]), d["warnings"])
        dur, unc = d["best"]["duration_s"], d["uncertainty"]["duration_s"]
        self.assertGreater(unc, 4 * d["uncertainty_conditional"]["duration_s"])  # was ± 0.008 conditional only
        self.assertLessEqual(abs(dur - 1.0), unc)  # the widened interval covers the true 1 s
        self.assertEqual(d["measurements"][0]["uncertainty"], round(unc, 4))
        self.assertFalse(d["measurements"][0]["model_confirmed"])

    def test_a_matching_curve_keeps_its_interval(self):
        t = np.arange(-0.2, 1.401, 1 / 60)
        u = np.clip(t, 0, 1)
        y = 0.5 - 0.5 * np.cos(np.pi * u) + np.random.default_rng(1).normal(0, 0.003, len(t))
        _, d = run_json("fit_curve.py", "--csv", self.csv("sine.csv", t, y))
        self.assertEqual(d["best"]["name"], "Sine InOut")
        self.assertFalse(d["residuals"]["systematic"])
        self.assertEqual(d["uncertainty"]["duration_s"], d["uncertainty_conditional"]["duration_s"])

    def test_sparse_frames_use_the_source_frame_interval(self):
        manifest = self.js("frames/manifest.json", {"tool": "extract_frames", "frames": [
            {"index": i, "pts_time": i / 30, "file": f"f{i}.png"} for i in (30, 90, 150)]})
        events = self.dir / "sparse.csv"
        events.write_text("frame,event\n30,fire\n90,fire\n150,fire\n", encoding="utf-8")
        _, d = run_json("event_stats.py", events, "--manifest", manifest, "--intervals", "fire")
        st = d["intervals"][0]
        self.assertAlmostEqual(st["quantization_s"], 1 / 30, places=4)  # was 2.0 (the gap between extracted frames)
        self.assertAlmostEqual(st["mean_ci_halfwidth_s"], 0.0236, delta=0.001)  # was 1.41
        self.assertTrue(any("sparsely" in w for w in d["warnings"]))


# ----------------------------------------------------------------- ui_measure

class UiCompareAspect(Tmp):
    def test_height_scaled_corner_anchored_layout_on_another_aspect_passes(self):
        W, H, cw, ch = 1920, 1080, 1280, 1024
        s = ch / H
        rb = [1600, 1000, 240, 40]
        qb = [cw + (rb[0] - W) * s, ch + (rb[1] - H) * s, rb[2] * s, rb[3] * s]
        ref = self.js("ref.json", {"reference_resolution": [W, H], "scale_rule": "height",
                                   "elements": [{"name": "Health", "bbox": rb, "anchor": "bottom-right"}]})
        rec = self.js("rec.json", {"reference_resolution": [cw, ch], "scale_rule": "height",
                                   "elements": [{"name": "Health", "bbox": qb, "anchor": "bottom-right"}]})
        code, d = run_json("ui_measure.py", "--compare", ref, rec, "--tolerance", ".1")
        self.assertEqual(code, 0)  # was off by 7%
        self.assertLess(d["worst_pct"], 0.01)
        # A real misplacement on the same screen still fails.
        bad = self.js("bad.json", {"reference_resolution": [cw, ch], "scale_rule": "height",
                                   "elements": [{"name": "Health", "bbox": [qb[0] - 60, qb[1], qb[2], qb[3]]}]})
        code, d = run_json("ui_measure.py", "--compare", ref, bad, "--tolerance", ".1")
        self.assertEqual(code, 1)


# ----------------------------------------------------------------- probe_video

@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class ProbeVideoStreaming(Tmp):
    def test_dupes_streams_frames_and_still_finds_doubled_frames(self):
        src = self.dir / "c30.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3", "-c:v", "libx264", "-preset", "ultrafast", src)
        dup = self.dir / "dup60.mp4"
        ffmpeg("-i", src, "-vf", "fps=60", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0", dup)
        _, d = run_json("probe_video.py", dup, "--dupes")
        self.assertAlmostEqual(d["dupes"]["duplicate_ratio_moving"], 0.5, delta=0.05)
        self.assertAlmostEqual(d["effective_fps"], 30, delta=1.5)
        import probe_video

        self.assertTrue(hasattr(probe_video, "stream_differences"))  # frames are read one at a time, not all at once


if __name__ == "__main__":
    unittest.main()
