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
  with --only degraded, the jump and run again as real captures go wrong (same ground truth):
    demo_jump_h264.mp4, demo_run_h264.mp4   heavy H.264 compression (CRF 32, 4:2:0)
    demo_run_h264_crf40.mp4                 compression that destroys the background (CRF 40)
    demo_jump_blur.mkv, demo_run_blur.mkv   motion blur (360-degree shutter)
    demo_jump_30in60.mkv                    30 fps content in a 60 fps container
    demo_jump_vfr.mkv                       variable frame rate (jitter and dropped frames)
    demo_run_hud.mkv                        a HUD panel and an opaque bar over part of the subject's path
  with --only extras, small inputs for the evals:
    demo_menu_track.json   a tracked menu slide-in (Back Out, 0.35 s), motion_track format
    demo_build_jump.log    a build's harness log of a jump (apex 7.5, rise 0.39 s, fall 0.28 s)
    demo_sfx_ref.wav, demo_sfx_new.wav   a reference sound and an original replacement to tune
  with --only camera, the camera and tracking cases of real gameplay footage (TRUTH["camera"]):
    cam_zoom.mp4       follow camera with a sprint FOV kick (zoom 1.00 to 1.12) and a HUD
    cam_follow.mp4     camera locked to the character (Roblox's default), 2.5 s, HUD
    cam_pan_zoom.mp4   pan, zoom 1.00 to 1.35 and roll 0 to 3 degrees
    cam_occluder.mp4   a flat grey pillar in front of the path
    cam_lookalike.mp4  an identical look-alike crossing the subject
    cam_small.mp4      a 10x20 px subject at 960x540, 30 fps, motion blur, CRF 32
    cam_vfr.mkv        partial follow camera with a variable frame rate
    the subject runs 16 studs/s from an instant start at 0.2 s (10 px per stud; 8 in cam_small)
  ground_truth.json the true values, so you can check what the tools measured

Scale: 20 pixels per stud at the subject's depth. The clean clips are lossless FFV1.
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
    "extras": {"menu": {"style": "Back Out", "duration_s": 0.35, "start_s": 0.1, "from_px": -400.0, "to_px": 120.0, "noise_px": 0.2},
               "build_jump": {"apex": 7.5, "rise_s": 0.39, "fall_s": 0.28, "jump_at_s": 0.5},
               "sfx_ref": {"hz": 660.0, "amp": 0.4, "duration_s": 0.2, "decay_s": 0.06, "start_s": 0.3},
               "sfx_new": {"hz": 691.21, "amp": 0.533, "duration_s": 0.23, "decay_s": 0.069, "start_s": 0.4,
                           "vs_ref": "+80 cents, +2.5 dB, 1.15x longer"}},
    "degraded": {"h264_crf": 32, "h264_crf_destroyed": 40, "blur": "360-degree shutter, 8 subframes", "content_fps_30in60": 30,
                 "vfr": "60 fps with +/-5 ms jitter and every 12th frame dropped", "hud_box_px": [250, 185, 420, 235], "hud_bar_px": [300, 203, 400, 215],
                 "files": {"demo_jump_h264.mp4": "jump", "demo_run_h264.mp4": "run", "demo_run_h264_crf40.mp4": "run",
                           "demo_jump_blur.mkv": "jump",
                           "demo_run_blur.mkv": "run", "demo_jump_30in60.mkv": "jump", "demo_jump_vfr.mkv": "jump",
                           "demo_run_hud.mkv": "run"}},
    "perspective": {"vfov_deg": 60.0, "pitch_deg": -35.0, "yaw_deg": 20.0, "height": 9.0, "image": [640, 360],
                    "rect_origin": [-2.0, 7.0], "rect_size": [12.0, 12.0],
                    "marker_start": [0.0, 9.0], "marker_heading_deg": 30.0, "sprite_size": [1.2, 2.0],
                    "steady_speed": 10.0, "ramp_time_s": 0.3, "t90_s": 0.27, "start_time_s": 0.2},
}


def encode(frames_dir: Path, out: Path, *, h264_crf: int | None = None, vfr_expr: str | None = None) -> None:
    """Encode f%04d.png: lossless FFV1, or H.264 at a given CRF; vfr_expr sets per-frame timestamps."""
    if not shutil.which("ffmpeg"):
        print("error: ffmpeg not found", file=sys.stderr)
        sys.exit(2)
    rate = "1000" if vfr_expr else str(FPS)  # a millisecond time base, so setpts keeps sub-frame times
    cmd = ["ffmpeg", "-v", "error", "-y", "-framerate", rate, "-i", str(frames_dir / "f%04d.png")]
    if vfr_expr:
        cmd += ["-vf", f"setpts='{vfr_expr}'", "-fps_mode", "passthrough"]
    if h264_crf is not None:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(h264_crf), "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "ffv1"]
    subprocess.run(cmd + [str(out)], check=True)


def write_clip(out: Path, render, times, *, blur_subframes: int = 1, shutter: float = 1 / FPS, **enc) -> None:
    """Render a frame at each time (averaging subframes across a centered shutter for motion blur) and encode."""
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            if blur_subframes > 1:
                acc = np.zeros_like(render(t), dtype=np.float64)
                for k in range(blur_subframes):
                    acc += render(t + ((k + 0.5) / blur_subframes - 0.5) * shutter)
                img = np.clip(acc / blur_subframes + 0.5, 0, 255).astype(np.uint8)
            else:
                img = render(t)
            Image.fromarray(img).save(Path(tmp) / f"f{i:04d}.png")
        encode(Path(tmp), out, **enc)


def jump_renderer():
    rng = np.random.default_rng(1)
    w, h = 640, 400
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

    def render(t: float):
        img = bg.copy()
        y = int(round(300 - height(t) * PPU))
        img[y - 12:y + 12, 288:312] = sprite
        return img

    return render


def run_renderer(hud: bool = False):
    rng = np.random.default_rng(2)
    w, h = 640, 360
    world = (rng.random((h, 1400, 3)) * 80 + 30).astype(np.uint8)
    sprite = (rng.random((20, 20, 3)) * 255).astype(np.uint8)
    r = TRUTH["run"]
    V, T, t0, pan = r["steady_speed"], r["ramp_time_s"], r["start_time_s"], r["camera_pan_px_s"]
    hx0, hy0, hx1, hy1 = TRUTH["degraded"]["hud_box_px"]

    def pos(t: float) -> float:
        tt = t - t0
        if tt <= 0:
            return 0.0
        return V * tt * tt / (2 * T) if tt < T else V * (tt - T / 2)

    def render(t: float):
        cam = int(round(pan * t))
        img = world[:, cam:cam + w].copy()
        x = int(round(100 + pos(t) * PPU)) - cam
        img[200:220, x - 10:x + 10] = sprite
        if hud:  # a semi-opaque screen-space HUD panel over the subject's path, with an opaque bar across it
            box = img[hy0:hy1, hx0:hx1].astype(np.float64)
            img[hy0:hy1, hx0:hx1] = (box * 0.35 + np.array([20, 20, 30]) * 0.65).astype(np.uint8)
            bx0, by0, bx1, by1 = TRUTH["degraded"]["hud_bar_px"]
            img[by0:by1, bx0:bx1] = (235, 200, 40)
        return img

    return render


def jump_clip(out: Path) -> None:
    write_clip(out, jump_renderer(), [i / FPS for i in range(80)])


def run_clip(out: Path) -> None:
    write_clip(out, run_renderer(), [i / FPS for i in range(70)])


def vfr_times(n: int) -> list[float]:
    """Container timestamps of the VFR clip: 60 fps with jitter and one dropped frame in 12."""
    import math

    return [math.floor((k + math.floor(k / 12) + 0.3 * math.sin(1.7 * k)) / FPS * 1000 + 1e-6) / 1000 for k in range(n)]


def degraded_clips(out_dir: Path) -> None:
    """Footage problems seen in real captures, each with the same ground truth as the clean clips."""
    jr, rr = jump_renderer(), run_renderer()
    jt, rt = [i / FPS for i in range(80)], [i / FPS for i in range(70)]
    crf = TRUTH["degraded"]["h264_crf"]
    write_clip(out_dir / "demo_jump_h264.mp4", jr, jt, h264_crf=crf)
    write_clip(out_dir / "demo_run_h264.mp4", rr, rt, h264_crf=crf)
    write_clip(out_dir / "demo_run_h264_crf40.mp4", rr, rt, h264_crf=TRUTH["degraded"]["h264_crf_destroyed"])
    write_clip(out_dir / "demo_jump_blur.mkv", jr, jt, blur_subframes=8)
    write_clip(out_dir / "demo_run_blur.mkv", rr, rt, blur_subframes=8)
    write_clip(out_dir / "demo_jump_30in60.mkv", jr, [2 * (i // 2) / FPS for i in range(80)])
    write_clip(out_dir / "demo_jump_vfr.mkv", jr, vfr_times(72), vfr_expr="(N+floor(N/12)+0.3*sin(1.7*N))/(60*TB)")
    write_clip(out_dir / "demo_run_hud.mkv", run_renderer(hud=True), rt)


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


def extras(out_dir: Path) -> None:
    """Small non-video inputs for the evals: a tracked UI tween, a build's harness log, two sounds."""
    import math
    import wave

    e = TRUTH["extras"]
    rng = np.random.default_rng(6)
    c1, c3 = 1.70158, 2.70158
    m = e["menu"]
    samples = []
    for i in range(60):
        t = i / FPS
        x = min(max((t - m["start_s"]) / m["duration_s"], 0.0), 1.0)
        back_out = 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2  # Easing.luau Back Out
        px = m["from_px"] + (m["to_px"] - m["from_px"]) * back_out + rng.normal(0, 0.2)
        samples.append({"sample": i, "index": i, "t": round(t, 6), "x_px": round(px, 3), "y_px": 540.0, "score": 1.0, "u": 0.0, "v": 0.0})
    (out_dir / "demo_menu_track.json").write_text(json.dumps({"tool": "motion_track", "schema": 1, "unit": "px", "bbox": [0, 520, 40, 40],
                                                              "samples": samples, "low_score_samples": 0}, indent=1) + "\n", encoding="utf-8")
    b = e["build_jump"]
    g_r, g_f, v0 = 2 * b["apex"] / b["rise_s"] ** 2, 2 * b["apex"] / b["fall_s"] ** 2, 2 * b["apex"] / b["rise_s"]
    y, vy, air, done, rows, lines = 3.0, 0.0, False, False, [], ['REMAKE_MEASURE {"k":"e","t":0,"n":"session"}']
    for i in range(120):
        t = i / FPS
        st = 1
        if t >= b["jump_at_s"] and not air and not done:
            air, vy = True, v0
            lines.append(f'REMAKE_MEASURE {{"k":"e","t":{t:.4f},"n":"jump"}}')
        if air:
            g = g_r if vy > 0 else g_f
            y += vy / FPS - 0.5 * g / FPS / FPS
            vy -= g / FPS
            st = 2 if vy > 0 else 3
            if y <= 3.0:
                y, vy, air, done, st = 3.0, 0.0, False, True, 1
                lines.append(f'REMAKE_MEASURE {{"k":"e","t":{t:.4f},"n":"land"}}')
        rows.append([round(t, 4), 0.0, round(y, 4), 0.0, 0.0, round(vy, 3), 0.0, st, 0.0])
        if len(rows) == 30:
            lines.append("REMAKE_MEASURE " + json.dumps({"k": "b", "s": rows}))
            rows = []
    (out_dir / "demo_build_jump.log").write_text("\n".join(f"12:00:00.000  {ln}  -  Client" for ln in lines) + "\n", encoding="utf-8")
    rate = 44100
    for name, spec in (("demo_sfx_ref.wav", e["sfx_ref"]), ("demo_sfx_new.wav", e["sfx_new"])):
        t = np.arange(int(1.0 * rate)) / rate
        x = rng.normal(0, 0.001, len(t))
        mask = (t >= spec["start_s"]) & (t < spec["start_s"] + spec["duration_s"])
        tt = t[mask] - spec["start_s"]
        env = np.exp(-tt / spec["decay_s"]) * np.minimum(1, tt / 0.004)
        x[mask] += spec["amp"] * env * np.sin(2 * math.pi * spec["hz"] * tt)
        with wave.open(str(out_dir / name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


# ----------------------------------------------------------------- camera group (hard cases)

CAM = {"w": 640, "h": 360, "px_per_unit": 10.0, "speed": 16.0, "start_s": 0.2, "sprite_px": [20, 40], "ground_y": 700.0}


def cam_world(seed: int = 5):
    """A textured world (smooth noise like terrain, bricks and foliage), 2400 x 1000 px at zoom 1."""
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 255, (1000 // 6 + 2, 2400 // 6 + 2, 3)).astype(np.uint8)
    im = Image.fromarray(small).resize((2400, 1000), Image.BICUBIC)
    return Image.fromarray((np.asarray(im).astype(np.float32) * 0.6 + 50).clip(0, 255).astype(np.uint8))


def cam_sprite(phase: float, size=(20, 40), color=(230, 60, 40)) -> Image.Image:
    """A blocky character whose legs swing with the run cycle (its appearance changes every frame)."""
    import math

    w, h = size
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([w * 0.25, 0, w * 0.75, h * 0.25], fill=(250, 210, 160, 255))
    d.rectangle([w * 0.2, h * 0.27, w * 0.8, h * 0.6], fill=color + (255,))
    s = math.sin(phase) * w * 0.18
    d.polygon([(w * 0.3, h * 0.6), (w * 0.48, h * 0.6), (w * 0.48 + s, h), (w * 0.3 + s, h)], fill=(40, 60, 200, 255))
    d.polygon([(w * 0.52, h * 0.6), (w * 0.7, h * 0.6), (w * 0.7 - s, h), (w * 0.52 - s, h)], fill=(40, 60, 200, 255))
    return im


def cam_render(world: Image.Image, cam, objs, w: int, h: int, hud: bool = False):
    """Render the world through a camera (cx, cy, zoom, roll_deg): screen = zoom * R(roll) (world - c) + centre.

    objs: (world x, world y, RGBA sprite at zoom 1) placed at sub-pixel positions. hud adds a textured
    screen-fixed panel and health bar in the top-left corner.
    """
    import math

    cx, cy, z, roll = cam
    c, s = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    a, b, d_, e = c / z, s / z, -s / z, c / z
    img = world.transform((w, h), Image.AFFINE, (a, b, cx - a * w / 2 - b * h / 2, d_, e, cy - d_ * w / 2 - e * h / 2),
                          resample=Image.BILINEAR)
    for wx, wy, spr in objs:
        sw, sh = max(1, round(spr.width * z)), max(1, round(spr.height * z))
        s2 = spr.resize((sw, sh), Image.BILINEAR) if (sw, sh) != spr.size else spr
        dx, dy = wx - cx, wy - cy
        u = z * (c * dx - s * dy) + w / 2 - sw / 2
        v = z * (s * dx + c * dy) + h / 2 - sh / 2
        iu, iv = math.floor(u), math.floor(v)
        pad = Image.new("RGBA", (sw + 2, sh + 2), (0, 0, 0, 0))
        pad.paste(s2, (1, 1))
        pad = pad.transform(pad.size, Image.AFFINE, (1, 0, -(u - iu), 0, 1, -(v - iv)), resample=Image.BILINEAR)
        img.paste(pad, (iu - 1, iv - 1), pad)
    out = np.asarray(img.convert("RGB")).copy()
    if hud:
        rng = np.random.default_rng(9)
        out[10:70, 10:170] = (rng.random((60, 160, 3)) * 120 + 60).astype(np.uint8)  # minimap-like panel
        out[78:90, 10:170] = (40, 40, 40)
        out[80:88, 12:130] = (60, 220, 80)  # health bar
    return out


def cam_clips(out_dir: Path) -> None:
    """Camera and tracking cases real gameplay footage has, each with exact ground truth (TRUTH["camera"])."""
    import math

    world = cam_world()
    W, H, P, V, t0, gy = CAM["w"], CAM["h"], CAM["px_per_unit"], CAM["speed"], CAM["start_s"], CAM["ground_y"]
    sp = {}

    def spr(phase, size=(20, 40), color=(230, 60, 40)):
        key = (round(phase % (2 * math.pi), 2), size, color)
        if key not in sp:
            sp[key] = cam_sprite(phase, size, color)
        return sp[key]

    def run_x(t):  # instant start (Roblox's default: full WalkSpeed on the first frame)
        return 600 + V * P * max(0.0, t - t0)

    truth = {**CAM, "clips": {}}

    def start_box(cam, wx, wy, size=(20, 40)):
        x, y, z, roll = cam
        u, v = (wx - x) * z + W / 2, (wy - y) * z + H / 2
        return [int(round(u - size[0] * z / 2)), int(round(v - size[1] * z / 2)), int(round(size[0] * z)), int(round(size[1] * z))]

    # 1. Sprint FOV kick: the camera follows at 60% and zooms 1.00 -> 1.12 over 0.5 s as the run starts.
    def zoom_cam(t):
        tt = max(0.0, t - t0)
        return (600 + 0.6 * (run_x(t) - 600) + 80, gy - 60, 1.0 + 0.12 * min(1.0, tt / 0.5), 0.0)

    write_clip(out_dir / "cam_zoom.mp4", lambda t: cam_render(world, zoom_cam(t), [(run_x(t), gy, spr(t * 18))], W, H, hud=True),
               [i / FPS for i in range(90)], h264_crf=20)
    truth["clips"]["cam_zoom.mp4"] = {"bbox": start_box(zoom_cam(0), 600, gy), "speed": V, "start_s": t0, "zoom": [1.0, 1.12],
                                      "what": "follow camera at 60% with a sprint FOV kick (zoom 1.00 to 1.12), HUD top-left"}

    # 2. Roblox's default camera: locked to the character, which stays put on screen. 2.5 s, so a
    #    background anchor on the left leaves the view.
    def follow_cam(t):
        return (run_x(t) + 60, gy - 60, 1.0, 0.0)

    write_clip(out_dir / "cam_follow.mp4", lambda t: cam_render(world, follow_cam(t), [(run_x(t), gy, spr(t * 18))], W, H, hud=True),
               [i / FPS for i in range(150)], h264_crf=20)
    truth["clips"]["cam_follow.mp4"] = {"bbox": start_box(follow_cam(0), 600, gy), "speed": V, "start_s": t0,
                                        "anchor_bbox": [300, 120, 40, 40], "anchor_leaves_view_s": round(t0 + 300 / (V * P), 3),
                                        "what": "camera locked to the character, HUD top-left"}

    # 3. Pan at 50% while zooming 1.00 -> 1.35 and rolling 0 -> 3 degrees.
    def pz_cam(t):
        return (600 + 0.5 * (run_x(t) - 600) + 80, gy - 60, 1.0 + 0.35 * t / 1.5, 3.0 * t / 1.5)

    write_clip(out_dir / "cam_pan_zoom.mp4", lambda t: cam_render(world, pz_cam(t), [(run_x(t), gy, spr(t * 18))], W, H),
               [i / FPS for i in range(90)], h264_crf=20)
    truth["clips"]["cam_pan_zoom.mp4"] = {"bbox": start_box(pz_cam(0), 600, gy), "speed": V, "start_s": t0, "zoom": [1.0, 1.35],
                                          "roll_deg": [0.0, 3.0], "what": "pan at 50%, zoom 1.00 to 1.35, roll 0 to 3 degrees"}

    # 4. A flat grey pillar in front of the path (flat surfaces scored up to 7.8 before 1.4).
    pillar = Image.new("RGBA", (30, 200), (90, 90, 90, 255))  # world x 675-705: hides the subject 0.61-0.92 s
    static = (750.0, gy - 40, 1.0, 0.0)
    write_clip(out_dir / "cam_occluder.mp4",
               lambda t: cam_render(world, static, [(run_x(t), gy, spr(t * 18)), (690.0, gy, pillar)], W, H),
               [i / FPS for i in range(80)], h264_crf=20)
    truth["clips"]["cam_occluder.mp4"] = {"bbox": start_box(static, 600, gy), "speed": V, "start_s": t0,
                                          "occluder_world_x": [675, 705], "what": "static camera, flat pillar in front of the path"}

    # 5. An identical look-alike crossing the subject (3 px higher, running the other way at the same speed).
    def la(t):
        return [(720.0 - 10 * P * t, gy - 3, spr(0.0)), (600 + 10 * P * t, gy, spr(0.0))]  # they cross at 0.6 s

    write_clip(out_dir / "cam_lookalike.mp4", lambda t: cam_render(world, static, la(t), W, H), [i / FPS for i in range(60)],
               h264_crf=20)
    truth["clips"]["cam_lookalike.mp4"] = {"bbox": start_box(static, 600, gy), "speed": 10.0, "start_s": 0.0,
                                           "end_x_px": round(600 + 10 * P * 59 / FPS - 750 + W / 2, 2),
                                           "what": "static camera, identical look-alike crossing"}

    # 6. A small subject (10 x 20 px in a 960 x 540 frame, 30 fps, motion blur, heavy compression).
    sw_, sh_, sfps = 960, 540, 30
    small_cam = (700.0, gy, 1.0, 0.0)

    def small(t):
        acc = np.zeros((sh_, sw_, 3))
        for k in range(4):
            tk = t + (k / 3 - 0.5) / sfps * 0.5
            acc += cam_render(world, small_cam, [(500 + V * 8 * max(0.0, tk - t0), gy, spr(tk * 18, (10, 20)))], sw_, sh_)
        return np.clip(acc / 4 + 0.5, 0, 255).astype(np.uint8)

    with tempfile.TemporaryDirectory() as tmp:
        for i in range(45):
            Image.fromarray(small(i / sfps)).save(Path(tmp) / f"f{i:04d}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(sfps), "-i", str(Path(tmp) / "f%04d.png"), "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "32", "-pix_fmt", "yuv420p", str(out_dir / "cam_small.mp4")], check=True)
    truth["clips"]["cam_small.mp4"] = {"bbox": [int(500 - 700 + sw_ / 2 - 5), int(sh_ / 2 - 10), 10, 20], "speed": V, "start_s": t0,
                                       "px_per_unit": 8.0, "fps": sfps,
                                       "what": "10x20 px subject at 960x540, 30 fps, motion blur, H.264 CRF 32"}

    # 7. Variable frame rate (jitter, one frame in 12 dropped) under a partial follow camera.
    def vfr_cam(t):
        return (600 + 0.6 * (run_x(t) - 600) + 80, gy - 60, 1.0, 0.0)

    write_clip(out_dir / "cam_vfr.mkv", lambda t: cam_render(world, vfr_cam(t), [(run_x(t), gy, spr(t * 18))], W, H),
               vfr_times(90), vfr_expr="(N+floor(N/12)+0.3*sin(1.7*N))/(60*TB)", h264_crf=20)
    truth["clips"]["cam_vfr.mkv"] = {"bbox": start_box(vfr_cam(0), 600, gy), "speed": V, "start_s": t0,
                                     "what": "follow camera at 60%, variable frame rate (jitter, drops)"}
    TRUTH["camera"] = truth


CLIPS = {
    "jump": lambda out: jump_clip(out / "demo_jump.mkv"),
    "run": lambda out: run_clip(out / "demo_run.mkv"),
    "perspective": lambda out: perspective_clip(out / "demo_perspective.mkv"),
    "hud": hud,
    "degraded": degraded_clips,
    "extras": extras,
    "camera": cam_clips,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", help=f"comma-separated subset of: {', '.join(CLIPS)} (default: all but degraded, extras and camera)")
    args = ap.parse_args()
    names = [n.strip() for n in args.only.split(",")] if args.only else [n for n in CLIPS if n not in ("degraded", "extras", "camera")]
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
