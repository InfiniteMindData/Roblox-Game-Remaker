#!/usr/bin/env python3
"""Generate synthetic "reference footage" with known ground truth, to rehearse the pipeline.

Writes into --out (created if missing):
  demo_jump.mkv    side-on standing jump, 60 fps: apex 8 studs, rise 0.4 s, falls twice as hard
  demo_run.mkv     standing start on a panning camera: 20 studs/s after a 0.25 s linear ramp
  demo_perspective.mkv  third-person view of a textured ground (vFOV 60, pitch -35, 9 studs up):
                   an upright 1.2x2 stud sprite runs at 10 studs/s after a 0.3 s ramp, diagonally
                   away across a painted 12x12 stud rectangle (for camera_solve.py ground)
  demo_hud.png     a 1920x1080 "reference" HUD screenshot
  demo_hud_rec.png the same HUD as a slightly-off "recreation" (darker, shifted health bar)
  hud_boxes.json   reference UI boxes for ui_measure.py
  ground_truth.json the true values, so you can check what the tools measured

Scale: 20 pixels per stud at the subject's depth. Lossless FFV1 video (no compression noise).
This footage is synthetic and original; it is not from any game.

Examples:
  python examples/demo/make_demo_footage.py --out /tmp/remake-demo
  python examples/demo/make_demo_footage.py --out /tmp/remake-demo --only jump,perspective
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
    "perspective": {"vfov_deg": 60.0, "pitch_deg": -35.0, "yaw_deg": 20.0, "height": 9.0, "image": [640, 360],
                    "rect_origin": [-2.0, 7.0], "rect_size": [12.0, 12.0],
                    "marker_start": [0.0, 9.0], "marker_heading_deg": 30.0, "sprite_size": [1.2, 2.0],
                    "steady_speed": 10.0, "ramp_time_s": 0.3, "t90_s": 0.27, "start_time_s": 0.2},
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


class PerspectiveCamera:
    """Pinhole camera over the ground plane y = 0 (world y up); camera space x right, y down, z forward."""

    def __init__(self, vfov: float, pitch: float, yaw: float, height: float, w: int, h: int):
        self.w, self.h = w, h
        self.f = (h / 2) / np.tan(np.radians(vfov) / 2)
        p, y = np.radians(pitch), np.radians(yaw)
        fwd = np.array([np.sin(y) * np.cos(p), np.sin(p), np.cos(y) * np.cos(p)])
        right = np.cross([0.0, 1.0, 0.0], fwd)
        right /= np.linalg.norm(right)
        self.r = np.stack([right, np.cross(right, fwd), fwd])  # rows: camera axes in world space
        self.c = np.array([0.0, height, 0.0])

    def project(self, x: float, z: float) -> list[float]:
        d = self.r @ (np.array([x, 0.0, z]) - self.c)
        return [self.w / 2 + self.f * d[0] / d[2], self.h / 2 + self.f * d[1] / d[2]]

    def ground(self, ss: int = 2):
        """World x, z (and a validity mask) for every pixel, ss x ss supersampled."""
        ys, xs = np.mgrid[0:self.h * ss, 0:self.w * ss].astype(np.float64)
        rays = np.stack([(xs + 0.5) / ss - self.w / 2, (ys + 0.5) / ss - self.h / 2, np.full_like(xs, self.f)], axis=-1)
        world = rays @ self.r
        ok = world[..., 1] < -1e-6
        t = np.where(ok, -self.c[1] / np.where(ok, world[..., 1], -1.0), 0.0)
        return self.c[0] + t * world[..., 0], self.c[2] + t * world[..., 2], ok


def perspective_clip(out: Path) -> None:
    rng = np.random.default_rng(4)
    p = TRUTH["perspective"]
    w, h = p["image"]
    n = 90
    cam = PerspectiveCamera(p["vfov_deg"], p["pitch_deg"], p["yaw_deg"], p["height"], w, h)
    gx, gz, ok = cam.ground()
    tex = rng.random((512, 512)) * 0.35 + 0.25  # 0.25-stud cells
    sprite_tex = rng.random((6, 4, 3))  # an upright, character-like sprite: 4x6 colored cells
    base = tex[(np.floor(gz * 4).astype(int)) % 512, (np.floor(gx * 4).astype(int)) % 512]
    base = np.stack([base * 0.8, base, base * 0.7], axis=-1)
    (ox, oz), (rw, rl) = p["rect_origin"], p["rect_size"]
    lw = 0.12
    on_x = (np.abs(gx - ox) < lw) | (np.abs(gx - (ox + rw)) < lw)
    on_z = (np.abs(gz - oz) < lw) | (np.abs(gz - (oz + rl)) < lw)
    inside = (gx > ox - lw) & (gx < ox + rw + lw) & (gz > oz - lw) & (gz < oz + rl + lw)
    base[inside & (on_x | on_z)] = 0.95
    base[~ok] = (0.55, 0.7, 0.9)
    V, T, t0 = p["steady_speed"], p["ramp_time_s"], p["start_time_s"]
    hd = np.radians(p["marker_heading_deg"])
    sw, sh = p["sprite_size"]

    def dist(t: float) -> float:
        tt = t - t0
        if tt <= 0:
            return 0.0
        return V * tt * tt / (2 * T) if tt < T else V * (tt - T / 2)

    def sprite_box(mx: float, mz: float) -> tuple[float, float, float, float]:
        """Screen box (x0, y0, x1, y1) of a camera-facing sprite whose bottom center stands at (mx, 0, mz)."""
        bx, by = cam.project(mx, mz)
        depth = float((cam.r @ (np.array([mx, 0.0, mz]) - cam.c))[2])
        pw, ph = cam.f * sw / depth, cam.f * sh / depth
        return bx - pw / 2, by - ph, bx + pw / 2, by

    small_base = base.reshape(h, 2, w, 2, 3).mean(axis=(1, 3))
    boxes = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(n):
            s = dist(i / FPS)
            mx, mz = p["marker_start"][0] + s * np.cos(hd), p["marker_start"][1] + s * np.sin(hd)
            bx0, by0, bx1, by1 = sprite_box(mx, mz)
            boxes.append((bx0, by0, bx1, by1))
            # Re-render only the pixels around the sprite (supersampled), on top of the static ground.
            x0, x1 = max(0, int(bx0) - 2), min(w, int(bx1) + 3)
            y0, y1 = max(0, int(by0) - 2), min(h, int(by1) + 3)
            ys, xs = np.mgrid[2 * y0:2 * y1, 2 * x0:2 * x1].astype(np.float64)
            u = ((xs + 0.5) / 2 - bx0) / (bx1 - bx0)
            v = ((ys + 0.5) / 2 - by0) / (by1 - by0)
            on = (u >= 0) & (u < 1) & (v >= 0) & (v < 1)
            win = base[2 * y0:2 * y1, 2 * x0:2 * x1].copy()
            win[on] = sprite_tex[np.clip((v[on] * 6).astype(int), 0, 5), np.clip((u[on] * 4).astype(int), 0, 3)]
            img = small_base.copy()
            img[y0:y1, x0:x1] = win.reshape(y1 - y0, 2, x1 - x0, 2, 3).mean(axis=(1, 3))
            Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)).save(Path(tmp) / f"f{i:04d}.png")
        encode(Path(tmp), out)
    corners = [cam.project(x, z) for x, z in ((ox, oz), (ox + rw, oz), (ox + rw, oz + rl), (ox, oz + rl))]
    p["rect_corners_px"] = [[round(float(c), 2) for c in xy] for xy in corners]
    bx0, by0, bx1, by1 = boxes[0]
    p["sprite_bbox_px"] = [int(round(bx0)), int(round(by0)), int(round(bx1 - bx0)), int(round(by1 - by0))]
    p["sprite_scale_last"] = round((boxes[-1][3] - boxes[-1][1]) / (by1 - by0), 4)
    p["focal_px"] = round(float(cam.f), 4)


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


CLIPS = {
    "jump": lambda out: jump_clip(out / "demo_jump.mkv"),
    "run": lambda out: run_clip(out / "demo_run.mkv"),
    "perspective": lambda out: perspective_clip(out / "demo_perspective.mkv"),
    "hud": hud,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", help=f"comma-separated subset of: {', '.join(CLIPS)} (default: all)")
    args = ap.parse_args()
    names = [n.strip() for n in args.only.split(",")] if args.only else list(CLIPS)
    unknown = [n for n in names if n not in CLIPS]
    if unknown:
        print(f"error: unknown clip(s) {', '.join(unknown)}; choose from {', '.join(CLIPS)}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    for name in names:
        CLIPS[name](args.out)
    (args.out / "ground_truth.json").write_text(json.dumps(TRUTH, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {', '.join(names)} and ground_truth.json to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
