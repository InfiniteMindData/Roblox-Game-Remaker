"""UI layout verification: ignore lists, measuring a recreation capture, scoring, and phase gates."""

from __future__ import annotations

import json
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
import breakdown_check  # noqa: E402

PARCHMENT = (219, 216, 209)
INK = (66, 32, 20)
STRIP = (49, 40, 36)


def run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", timeout=600)


def write(path: Path, data) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


REF = {
    "reference_resolution": [1920, 1080], "scale_rule": "height",
    "elements": [
        {"name": "Panel", "bbox": [68, 205, 322, 660]},
        {"name": "Title", "gui": "TitleLabel", "bbox": [90, 243, 172, 46], "ignore": ["w"]},
        {"name": "Store", "bbox": [1495, 872, 373, 146], "anchor": "bottom-right"},
    ],
}


def draw_capture(path: Path, cw: int, ch: int) -> dict:
    """Render a recreation of REF at cw x ch under the height rule and return the matching ui-rects JSON."""
    s = ch / 1080
    img = np.zeros((ch, cw, 3), np.uint8)
    img[:] = (40, 90, 140)  # scene

    def box(x, y, w, h, color):
        img[int(round(y)):int(round(y + h)), int(round(x)):int(round(x + w))] = color

    px, py, pw, ph = 68 * s, 205 * s, 322 * s, 660 * s
    box(px, py, pw, ph, PARCHMENT)
    # text: glyphs (a word of a different length than the reference's), 46 px capitals at y 243
    gx, gy, gw, gh = 90 * s, 243 * s, 120 * s, 46 * s
    for k in range(5):
        box(gx + k * gw / 5, gy, gw / 5 - 3 * s, gh, INK)
    # a dark strip right under the text, inside the label's line box (it must not count as text)
    box(0, (243 + 46 + 2) * s, 680 * s, 38 * s, STRIP)
    # right-anchored store tile: 52 px from the right edge, 62 from the bottom, in reference px
    sx, sy, sw, sh = cw - (52 + 373) * s, ch - (62 + 146) * s, 373 * s, 146 * s
    box(sx, sy, sw, sh, (200, 120, 80))
    Image.fromarray(img).save(path)
    line_top = gy - 0.235 * (46 / 0.575) * s
    return {"tool": "ui_rects", "viewport": [cw, ch], "inset": [0, 58], "elements": [
        {"name": "Panel", "kind": "panel", "anchor": [0, 0.5], "x": px, "y": py, "w": pw, "h": ph},
        {"name": "TitleLabel", "kind": "text", "anchor": [0, 0], "x": gx, "y": line_top, "w": 320 * s, "h": 120 * s,
         "text": {"x": gx, "y": line_top, "w": gw + 2, "h": 1.48 * (46 / 0.575) * s}},
        {"name": "Store", "kind": "panel", "anchor": [1, 1], "x": sx, "y": sy, "w": sw, "h": sh},
    ]}


class UILayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.ref = write(self.dir / "ref-boxes.json", REF)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ignore_skips_a_dimension(self):
        rec = json.loads(json.dumps(REF))
        rec["elements"][1]["bbox"][2] = 260  # different word, much wider
        write(self.dir / "rec.json", rec)
        ok = run("ui_measure.py", "--compare", self.ref, self.dir / "rec.json", "--out", self.dir / "diff" / "ui-1.json")
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertIn("(ign)", ok.stdout)
        report = json.loads((self.dir / "diff" / "ui-1.json").read_text(encoding="utf-8"))
        self.assertEqual((report["tool"], report["mode"]), ("ui_measure", "compare"))
        strict = json.loads(json.dumps(REF))
        del strict["elements"][1]["ignore"]
        del rec["elements"][1]["ignore"]  # an ignore list in either file applies
        write(self.dir / "ref-strict.json", strict)
        write(self.dir / "rec-strict.json", rec)
        self.assertEqual(run("ui_measure.py", "--compare", self.dir / "ref-strict.json", self.dir / "rec-strict.json").returncode, 1)

    def test_from_capture_maps_any_aspect_to_the_reference(self):
        for cw, ch in ((960, 540), (1260, 540)):  # 16:9 and a wide, docked-viewport aspect
            rects = write(self.dir / f"rects-{cw}.json", draw_capture(self.dir / f"cap-{cw}.png", cw, ch))
            out = self.dir / f"rec-{cw}.json"
            proc = run("ui_measure.py", "--from-capture", self.dir / f"cap-{cw}.png", rects, "--ref", self.ref, "--out", out)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            got = {e["name"]: e for e in json.loads(out.read_text(encoding="utf-8"))["elements"]}
            px = 1080 / ch  # one capture pixel in reference pixels
            for name, want in (("Panel", [68, 205, 322, 660]), ("Store", [1495, 872, 373, 146])):
                for g, w in zip(got[name]["bbox"], want):
                    self.assertAlmostEqual(g, w, delta=1.5 * px, msg=f"{cw}: {name} {got[name]['bbox']}")
            title = got["Title"]
            self.assertEqual(title["method"], "ink pixels in the drawn text")
            self.assertAlmostEqual(title["bbox"][1], 243, delta=2 * px, msg=title)  # glyph top, not the line top
            self.assertAlmostEqual(title["bbox"][3], 46, delta=2 * px, msg=title)  # the strip below is not ink
            cmp = run("ui_measure.py", "--compare", self.ref, out, "--tolerance", "1.0")
            self.assertEqual(cmp.returncode, 0, cmp.stdout)

    def test_fidelity_report_scores_layout(self):
        remake = self.dir / "remake"
        (remake / "diff").mkdir(parents=True)
        rec = json.loads(json.dumps(REF))
        rec["elements"][0]["bbox"][0] += 9.6  # 0.5% of the width
        write(self.dir / "rec.json", rec)
        run("ui_measure.py", "--compare", self.ref, self.dir / "rec.json", "--out", remake / "diff" / "ui-1.json")
        proc = run("fidelity_report.py", remake, "--dry-run", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        systems = json.loads(proc.stdout)["systems"]
        self.assertEqual(systems["ui:ref-boxes"]["status"], "pass")
        self.assertAlmostEqual(systems["ui:ref-boxes"]["r"], 0.5, places=2)

    def test_status_accepts_screenshot_boxes_for_phase_2(self):
        remake = self.dir / "remake"
        (remake / "ui").mkdir(parents=True)
        write(remake / "ui" / "ref-boxes.json", REF)
        write(remake / "measurements.json", {"measurements": [{"id": "MS-001", "what": "panel box", "value": "68,205,322,660",
                                                               "unit": "px", "uncertainty": 4, "method": "frame_zoom", "evidence": ["EV-002"]}]})
        proc = run("remake_status.py", remake, "--json")
        gates = json.loads(proc.stdout)["gates"]
        self.assertTrue(gates[2]["ok"], gates[2])
        self.assertIn("1 UI box sets", gates[2]["detail"])

    def test_breakdown_accepts_box_values(self):
        self.assertTrue(breakdown_check.VALUE_RE.match("panel_box = 68, 205, 322, 660 ± 4 px"))
        self.assertTrue(breakdown_check.VALUE_RE.match("apex_height = 7.4 ± 0.3 studs"))
        self.assertFalse(breakdown_check.VALUE_RE.match("panel_box = 68, 205, about 322 ± 4 px"))

    def test_ui_rects_snippet(self):
        proc = run("studio_snippets.py", "ui-rects", self.ref, "--gui", "MainMenu")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('local NAMES = { "Panel", "TitleLabel", "Store" }', proc.stdout)
        self.assertIn("GetGuiInset", proc.stdout)
        bad = json.loads(json.dumps(REF))
        bad["elements"][0]["name"] = 'x"; os.exit()'
        write(self.dir / "bad.json", bad)
        self.assertEqual(run("studio_snippets.py", "ui-rects", self.dir / "bad.json").returncode, 2)


if __name__ == "__main__":
    unittest.main()
