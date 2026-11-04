#!/usr/bin/env python3
"""Generate synthetic "reference footage" with known ground truth, to rehearse the pipeline.

Writes into --out (created if missing):
  demo_jump.mkv    side-on standing jump, 60 fps: apex 8 studs, rise 0.4 s, falls twice as hard
  demo_run.mkv     standing start on a panning camera: 20 studs/s after a 0.25 s linear ramp
  demo_hud.png     a 1920x1080 "reference" HUD screenshot
  demo_hud_rec.png the same HUD as a slightly-off "recreation" (darker, shifted health bar)
  hud_boxes.json   reference UI boxes for ui_measure.py
  ground_truth.json the true values, so you can check what the tools measured

Scale: 20 pixels per stud at the subject's depth. Lossless FFV1 video (no compression noise).
This footage is synthetic and original; it is not from any game.

Example:
  python examples/demo/make_demo_footage.py --out /tmp/remake-demo
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError:
    print("error: numpy and Pillow are required: pip install -r scripts/requirements.txt", file=sys.stderr)
    sys.exit(2)

FPS = 60
PPU = 20.0
TRUTH = {
    "px_per_unit": PPU,
    "fps": FPS,
    "jump": {"apex_height": 8.0, "rise_time_s": 0.4, "fall_time_s": 0.282843, "g_rise": 100.0, "g_fall": 200.0,
             "takeoff_speed": 40.0, "takeoff_time_s": 0.2},
    "run": {"steady_speed": 20.0, "ramp_time_s": 0.25, "t90_s": 0.225, "start_time_s": 0.2, "camera_pan_px_s": 60.0},
    "hud": {"health_bar_offset_px": [12, 5], "darken": 0.82},
}


def encode(frames_dir: Path, out: Path) -> None:
    if not shutil.which("ffmpeg"):
        print("error: ffmpeg not found", file=sys.stderr)
        sys.exit(2)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", str(frames_dir / "f%04d.png"),
                    "-c:v", "ffv1", str(out)], check=True)


def jump_clip(out: Path) -> None:
    rng = np.random.default_rng(1)
    w, h, n = 640, 400, 80
    bg = (rng.random((h, w, 3)) * 60 + 40).astype(np.uint8)
    sprite = (rng.random((24, 24, 3)) * 255).astype(np.uint8)
    j = TRUTH["jump"]
    v0, gr, gf, t0 = j["takeoff_speed"], j["g_rise"], j["g_fall"], j["takeoff_time_s"]
    apex, rise = v0 * v0 / (2 * gr), v0 / gr
    fall = (2 * apex / gf) ** 0.5

    def height(t: float) -> float:
        tt = t - t0
        if tt <= 0:
            return 0.0
        if tt <= rise:
            return v0 * tt - 0.5 * gr * tt * tt
        td = tt - rise
        return apex - 0.5 * gf * td * td if td <= fall else 0.0

    with tempfile.TemporaryDirectory() as tmp:
        for i in range(n):
            img = bg.copy()
            y = int(round(300 - height(i / FPS) * PPU))
            img[y - 12:y + 12, 288:312] = sprite
            Image.fromarray(img).save(Path(tmp) / f"f{i:04d}.png")
        encode(Path(tmp), out)


def run_clip(out: Path) -> None:
    rng = np.random.default_rng(2)
    w, h, n = 640, 360, 70
    world = (rng.random((h, 1400, 3)) * 80 + 30).astype(np.uint8)
    sprite = (rng.random((20, 20, 3)) * 255).astype(np.uint8)
    r = TRUTH["run"]
    V, T, t0, pan = r["steady_speed"], r["ramp_time_s"], r["start_time_s"], r["camera_pan_px_s"]

    def pos(t: float) -> float:
        tt = t - t0
        if tt <= 0:
            return 0.0
        return V * tt * tt / (2 * T) if tt < T else V * (tt - T / 2)

    with tempfile.TemporaryDirectory() as tmp:
        for i in range(n):
            t = i / FPS
            cam = int(round(pan * t))
            img = world[:, cam:cam + w].copy()
            x = int(round(100 + pos(t) * PPU)) - cam
            img[200:220, x - 10:x + 10] = sprite
            Image.fromarray(img).save(Path(tmp) / f"f{i:04d}.png")
        encode(Path(tmp), out)


def hud(out_dir: Path) -> None:
    def draw(offset=(0, 0), darken=1.0) -> Image.Image:
        img = Image.new("RGB", (1920, 1080), (40, 70, 110))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 700, 1920, 1080], fill=(60, 110, 60))  # ground
        ox, oy = offset
        d.rectangle([48 + ox, 980 + oy, 48 + 420 + ox, 980 + 36 + oy], fill=(20, 20, 20))
        d.rectangle([52 + ox, 984 + oy, 52 + 300 + ox, 984 + 28 + oy], fill=(200, 40, 50))
        d.rectangle([1700, 960, 1700 + 172, 960 + 72], fill=(30, 30, 30))
        d.rectangle([944, 524, 976, 556], outline=(255, 255, 255), width=3)
        if darken != 1.0:
            arr = np.asarray(img, dtype=np.float32) * darken
            img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        return img

    draw().save(out_dir / "demo_hud.png")
    draw(tuple(TRUTH["hud"]["health_bar_offset_px"]), TRUTH["hud"]["darken"]).save(out_dir / "demo_hud_rec.png")
    boxes = {
        "reference_resolution": [1920, 1080],
        "scale_rule": "height",
        "elements": [
            {"name": "HealthBar", "bbox": [48, 980, 420, 36], "anchor": "bottom-left"},
            {"name": "AmmoPanel", "bbox": [1700, 960, 172, 72]},
            {"name": "Crosshair", "bbox": [944, 524, 32, 32]},
        ],
    }
    (out_dir / "hud_boxes.json").write_text(json.dumps(boxes, indent=2) + "\n", encoding="utf-8")
    rec = json.loads(json.dumps(boxes))
    rec["elements"][0]["bbox"] = [60, 985, 420, 36]
    (out_dir / "hud_boxes_rec.json").write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    jump_clip(args.out / "demo_jump.mkv")
    run_clip(args.out / "demo_run.mkv")
    hud(args.out)
    (args.out / "ground_truth.json").write_text(json.dumps(TRUTH, indent=2) + "\n", encoding="utf-8")
    print(f"wrote demo footage and ground_truth.json to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
