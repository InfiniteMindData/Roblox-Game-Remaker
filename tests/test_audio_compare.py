"""Tests for audio_compare.py on synthetic sounds with known duration, level, pitch and brightness."""

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

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "roblox-game-remaker"
SCRIPTS = SKILL / "scripts"
RATE = 44100


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=600)


def burst(path: Path, f0: float, amp: float, dur: float, start: float, *, total=1.5, f1=None, harmonic=0.0):
    """A tone burst with 5 ms fades over a -60 dBFS noise floor (f1: a linear chirp to f1)."""
    t = np.arange(int(total * RATE)) / RATE
    x = np.random.default_rng(0).normal(0, 0.001, len(t))
    m = (t >= start) & (t < start + dur)
    tt = t[m] - start
    ph = 2 * np.pi * (f0 * tt + (0.5 * (f1 - f0) / dur * tt * tt if f1 else 0.0))
    fade = np.minimum(1, np.minimum(tt / 0.005, (dur - tt) / 0.005))
    x[m] += amp * fade * (np.sin(ph) + harmonic * np.sin(2 * ph))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class AudioCompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def analyze(self, path, *args):
        proc = run("audio_compare.py", "analyze", path, "--json", *args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_tone_features(self):
        f = self.analyze(burst(self.dir / "tone.wav", 440, 0.5, 0.25, 0.5))["features"]
        self.assertAlmostEqual(f["onset_s"], 0.5, delta=0.002)
        self.assertAlmostEqual(f["duration_s"], 0.25, delta=0.003)
        self.assertAlmostEqual(f["dominant_hz_median"], 440, delta=1.0)
        self.assertAlmostEqual(f["centroid_hz"], 440, delta=440 * 0.02)
        rms = 0.5 / math.sqrt(2)  # a sine of amplitude 0.5; the 5 ms fades cost about 0.1 dB
        self.assertAlmostEqual(f["level_dbfs"], 20 * math.log10(rms), delta=0.3)
        h = self.analyze(burst(self.dir / "harm.wav", 440, 0.3, 0.25, 0.5, harmonic=1.0))["features"]
        self.assertAlmostEqual(h["centroid_hz"], 660, delta=660 * 0.02)  # equal-power partials at 440 and 880
        seg = self.analyze(self.dir / "tone.wav", "--start", "0.3", "--end", "1.0")["features"]
        self.assertAlmostEqual(seg["onset_s"], 0.5, delta=0.002)  # times stay in source seconds

    def test_dominant_frequency_follows_a_chirp(self):
        f = self.analyze(burst(self.dir / "chirp.wav", 300, 0.5, 0.5, 0.2, f1=900))["features"]
        self.assertAlmostEqual(f["duration_s"], 0.5, delta=0.003)
        errs = [abs(hz - (300 + 1200 * (t - 0.2))) / (300 + 1200 * (t - 0.2))
                for t, hz in zip(f["track_t_s"], f["dominant_hz"]) if hz is not None and 0.3 <= t <= 0.6]
        self.assertGreater(len(errs), 20)
        self.assertLess(float(np.median(errs)), 0.01)

    def test_compare_reports_differences_and_hints(self):
        ref = burst(self.dir / "ref.wav", 440, 0.5, 0.25, 0.5)
        rep = burst(self.dir / "rep.wav", 440 * 2 ** (100 / 1200), 0.5 * 10 ** (3 / 20), 0.30, 0.7)
        proc = run("audio_compare.py", "compare", ref, rep, "--json", "--plot", self.dir / "cmp.png")
        self.assertEqual(proc.returncode, 1)
        c = json.loads(proc.stdout)
        self.assertAlmostEqual(c["comparison"]["level_db"], 3.0, delta=0.2)
        self.assertAlmostEqual(c["comparison"]["duration_ratio"], 1.2, delta=0.02)
        self.assertAlmostEqual(c["comparison"]["pitch_cents"], 100, delta=3)
        self.assertLess(c["comparison"]["envelope_db"], 1.0)  # same shape, only longer
        self.assertEqual(set(c["failures"]), {"level_db", "duration_ratio", "pitch_cents"})
        hints = " ".join(c["hints"])
        self.assertIn("AudioPitchShifter.Pitch x0.94", hints)
        self.assertIn("AudioPlayer.Volume x0.70", hints)
        self.assertTrue((self.dir / "cmp.png").is_file())

    def test_speed_change_is_recognised_and_identical_passes(self):
        ref = burst(self.dir / "ref.wav", 440, 0.5, 0.25, 0.5)
        fast = burst(self.dir / "fast.wav", 440 * 1.06, 0.5, 0.25 / 1.06, 0.4)
        c = json.loads(run("audio_compare.py", "compare", ref, fast, "--json").stdout)
        self.assertTrue(any("PlaybackSpeed x0.94" in h and "fixes both" in h for h in c["hints"]), c["hints"])
        same = burst(self.dir / "same.wav", 440, 0.5, 0.25, 0.3)
        proc = run("audio_compare.py", "compare", ref, same, "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertGreater(json.loads(proc.stdout)["score"], 95)

    def test_ledger_import_and_bad_input(self):
        out = self.dir / "a.json"
        tone = burst(self.dir / "tone.wav", 440, 0.5, 0.25, 0.5)
        self.assertEqual(run("audio_compare.py", "analyze", tone, "--out", out).returncode, 0)
        run("breakdown_init.py", self.dir, "--game", "T")
        ev = run("ledger.py", "add-evidence", self.dir / "remake", "--type", "video", "--title", "jump sfx", "--source", "j.wav",
                 "--analysis", "audio_compare").stdout.strip()
        self.assertEqual(run("ledger.py", "import", self.dir / "remake", out, "--evidence", ev).returncode, 0)
        ms = json.loads((self.dir / "remake" / "measurements.json").read_text())["measurements"]
        self.assertEqual([m["metric"] for m in ms], ["audio_duration", "audio_dominant_hz", "audio_level_dbfs"])
        self.assertEqual(run("audio_compare.py", "analyze", self.dir / "missing.wav").returncode, 2)
        self.assertEqual(run("audio_compare.py", "analyze", tone, "--start", "1", "--end", "0.5").returncode, 2)
        silent = self.dir / "silent.wav"
        with wave.open(str(silent), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(np.zeros(RATE, np.int16).tobytes())
        proc = run("audio_compare.py", "analyze", silent)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("stands out", proc.stderr)


if __name__ == "__main__":
    unittest.main()
