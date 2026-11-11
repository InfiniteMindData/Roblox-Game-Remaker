"""Shared helpers for the roblox-game-remaker scripts.

Standard library plus numpy and Pillow only. No network access. Every function that touches
the filesystem takes explicit paths.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, NoReturn, Sequence

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


class ToolError(Exception):
    """Raised for invalid input or a failed external tool; carries an exit code."""

    def __init__(self, message: str, code: int = EXIT_USAGE):
        super().__init__(message)
        self.code = code


def fail(message: str, code: int = EXIT_USAGE) -> NoReturn:
    raise ToolError(message, code)


def run_main(main) -> None:
    """Run a CLI main() and convert ToolError into a clean message and exit code."""
    try:
        code = main()
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(exc.code)
    except KeyboardInterrupt:
        sys.exit(130)
    sys.exit(code or 0)


# ---------------------------------------------------------------- optional deps

def require_numpy():
    try:
        import numpy as np  # noqa: F401
    except ImportError:
        fail("numpy is required: pip install -r scripts/requirements.txt")
    import numpy as np

    return np


def require_pil():
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        fail("Pillow is required: pip install -r scripts/requirements.txt")
    from PIL import Image

    return Image


# ---------------------------------------------------------------- external tools

def which(tool: str) -> str | None:
    return shutil.which(tool)


def need_tool(tool: str) -> str:
    path = which(tool)
    if not path:
        fail(f"'{tool}' was not found on PATH. Install ffmpeg (which provides ffmpeg and ffprobe).")
    return path


def run(cmd: Sequence[str], *, input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(list(cmd), input=input_bytes, capture_output=True)
    except FileNotFoundError:
        fail(f"could not run '{cmd[0]}'")
    if check and proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        tail = "\n".join(stderr[-8:])
        fail(f"{Path(cmd[0]).name} failed (exit {proc.returncode}):\n{tail}", EXIT_FAIL)
    return proc


def parse_rate(text: str | None) -> float | None:
    if not text or text in ("0/0", "N/A"):
        return None
    try:
        value = float(Fraction(text))
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


def ffprobe_json(video: Path) -> dict:
    need_tool("ffprobe")
    proc = run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(video),
    ])
    return json.loads(proc.stdout.decode("utf-8", "replace") or "{}")


def video_stream(info: dict) -> dict:
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    fail("no video stream found")


def frame_timestamps(video: Path, max_frames: int | None = None) -> list[float]:
    """Presentation timestamps (seconds) of every video frame, in presentation order.

    Uses packet timestamps (fast, no decoding) and falls back to decoded frames when packets
    carry no pts.
    """
    need_tool("ffprobe")
    base = ["ffprobe", "-v", "error", "-select_streams", "v:0"]
    if max_frames:
        base += ["-read_intervals", f"%+#{int(max_frames)}"]
    proc = run(base + ["-show_entries", "packet=pts_time", "-of", "csv=p=0", str(video)])
    values = _parse_float_lines(proc.stdout)
    if not values:
        proc = run(base + ["-show_entries", "frame=best_effort_timestamp_time", "-of", "csv=p=0", str(video)])
        values = _parse_float_lines(proc.stdout)
    if not values:
        fail("could not read frame timestamps from the video")
    values.sort()
    if max_frames:
        values = values[: int(max_frames)]
    return values


def _parse_float_lines(raw: bytes) -> list[float]:
    out: list[float] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip().strip(",")
        if not line or line == "N/A":
            continue
        try:
            out.append(float(line.split(",")[0]))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- parsing

def parse_bbox(text: str, name: str = "bbox") -> tuple[int, int, int, int]:
    try:
        parts = [int(round(float(p))) for p in text.replace(" ", "").split(",")]
    except ValueError:
        fail(f"{name} must be x,y,w,h (got {text!r})")
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0 or parts[0] < 0 or parts[1] < 0:
        fail(f"{name} must be x,y,w,h with positive width and height (got {text!r})")
    return parts[0], parts[1], parts[2], parts[3]


def parse_aspect(text: str) -> float:
    text = text.strip()
    for sep in (":", "/", "x"):
        if sep in text:
            a, b = text.split(sep, 1)
            try:
                value = float(a) / float(b)
            except (ValueError, ZeroDivisionError):
                break
            if value > 0:
                return value
            break
    try:
        value = float(text)
    except ValueError:
        fail(f"aspect must look like 16:9 or 1.777 (got {text!r})")
    if value <= 0:
        fail("aspect must be positive")
    return value


def parse_float_list(text: str, name: str) -> list[float]:
    try:
        return [float(p) for p in text.replace(" ", "").split(",") if p]
    except ValueError:
        fail(f"{name} must be a comma-separated list of numbers (got {text!r})")


# ---------------------------------------------------------------- files

def ensure_out_dir(path: Path, *, allow_nonempty: bool = False) -> Path:
    if path.exists() and not path.is_dir():
        fail(f"output path exists and is not a directory: {path}")
    if path.exists() and any(path.iterdir()) and not allow_nonempty:
        fail(f"output directory is not empty: {path} (pass --overwrite to reuse it)")
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        fail(f"file not found: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")


def _json_default(obj: Any) -> Any:
    """Convert numpy scalars and arrays (and paths) for JSON output."""
    if hasattr(obj, "item") and callable(obj.item) and getattr(obj, "shape", None) == ():
        return obj.item()
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def write_json(path: Path, data: Any) -> None:
    ensure_parent(path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=False, default=_json_default)
        fh.write("\n")


def dump_json(data: Any) -> str:
    return json.dumps(data, indent=2, default=_json_default)


def load_manifest(path: Path) -> tuple[dict, list[dict], Path]:
    """Load an extract_frames manifest; return (manifest, frames, base_dir)."""
    if path.is_dir():
        path = path / "manifest.json"
    data = read_json(path)
    frames = data.get("frames") if isinstance(data, dict) else None
    if not isinstance(frames, list) or not frames:
        fail(f"{path} is not a frame manifest (expected a non-empty 'frames' list)")
    return data, frames, path.parent


def list_images(directory: Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp"}
    return sorted(p for p in directory.iterdir() if p.suffix.lower() in exts)


# ---------------------------------------------------------------- images

def load_rgb(path: Path):
    np = require_numpy()
    Image = require_pil()
    try:
        with Image.open(path) as img:
            arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    except FileNotFoundError:
        fail(f"image not found: {path}")
    except OSError as exc:
        fail(f"cannot read image {path}: {exc}")
    return arr


def load_gray(path: Path, downscale: int = 1):
    np = require_numpy()
    Image = require_pil()
    try:
        with Image.open(path) as img:
            g = img.convert("L")
            if downscale > 1:
                g = g.resize((max(1, g.width // downscale), max(1, g.height // downscale)), Image.BILINEAR)
            arr = np.asarray(g, dtype=np.float32)
    except FileNotFoundError:
        fail(f"image not found: {path}")
    except OSError as exc:
        fail(f"cannot read image {path}: {exc}")
    return arr


def to_uint8_image(arr):
    np = require_numpy()
    Image = require_pil()
    data = np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(data)


def rgb_to_hex(rgb: Iterable[float]) -> str:
    r, g, b = [int(round(max(0.0, min(1.0, c)) * 255)) for c in rgb]
    return f"#{r:02X}{g:02X}{b:02X}"


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------- plots

PLOT_COLORS = [(31, 119, 180), (230, 120, 20), (44, 160, 44), (200, 40, 40), (120, 80, 170), (90, 90, 90)]


def nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    """About n round-numbered ticks covering [lo, hi]."""
    import math

    if not math.isfinite(lo) or not math.isfinite(hi):
        return []
    if hi <= lo:
        hi = lo + 1.0
    raw = (hi - lo) / max(1, n)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.ceil(lo / step - 1e-9) * step
    ticks, v = [], start
    while v <= hi + 1e-9 * step:
        ticks.append(round(v, 10))
        v += step
    return ticks


def line_plot(path: Path, panels: list[dict], title: str = "", width: int = 960, panel_height: int = 260) -> Path:
    """Draw stacked line-chart panels with Pillow and save a PNG.

    Each panel: {"title": str, "ylabel": str, "xlabel": str,
                 "series": [{"label": str, "x": [...], "y": [...], "color": (r, g, b), "dots": bool}],
                 "vlines": [{"x": float, "label": str}]}
    """
    import math

    Image = require_pil()
    from PIL import ImageDraw, ImageFont

    font = ImageFont.load_default()
    top = 28 if title else 8
    img = Image.new("RGB", (width, top + panel_height * len(panels)), (255, 255, 255))
    d = ImageDraw.Draw(img)
    if title:
        d.text((10, 8), title, fill=(0, 0, 0), font=font)
    left, right, pad_t, pad_b = 70, 20, 22, 40
    for pi, panel in enumerate(panels):
        y0 = top + pi * panel_height
        px0, px1 = left, width - right
        py0, py1 = y0 + pad_t, y0 + panel_height - pad_b
        xs = [x for s in panel["series"] for x in s["x"] if x is not None and math.isfinite(x)]
        ys = [y for s in panel["series"] for y in s["y"] if y is not None and math.isfinite(y)]
        if not xs or not ys:
            d.text((px0, py0), f"{panel.get('title', '')}: no data", fill=(120, 0, 0), font=font)
            continue
        xlo, xhi = min(xs), max(xs)
        ylo, yhi = min(ys), max(ys)
        if yhi - ylo < 1e-12:
            ylo, yhi = ylo - 1, yhi + 1
        margin = 0.05 * (yhi - ylo)
        ylo, yhi = ylo - margin, yhi + margin
        if xhi - xlo < 1e-12:
            xhi = xlo + 1

        def sx(x):
            return px0 + (x - xlo) / (xhi - xlo) * (px1 - px0)

        def sy(y):
            return py1 - (y - ylo) / (yhi - ylo) * (py1 - py0)

        d.rectangle([px0, py0, px1, py1], outline=(0, 0, 0))
        for t in nice_ticks(xlo, xhi, 8):
            x = sx(t)
            d.line([x, py0, x, py1], fill=(232, 232, 232))
            d.text((x - 12, py1 + 4), f"{t:g}", fill=(60, 60, 60), font=font)
        for t in nice_ticks(ylo, yhi, 5):
            y = sy(t)
            d.line([px0, y, px1, y], fill=(232, 232, 232))
            d.text((4, y - 6), f"{t:g}", fill=(60, 60, 60), font=font)
        d.rectangle([px0, py0, px1, py1], outline=(0, 0, 0))
        for vi, v in enumerate(panel.get("vlines", [])):
            if xlo <= v["x"] <= xhi:
                x = sx(v["x"])
                d.line([x, py0, x, py1], fill=(150, 150, 150))
                d.text((x + 2, py0 + 24 + 12 * (vi % 4)), v.get("label", ""), fill=(100, 100, 100), font=font)
        lx = px0 + 8
        for si, s in enumerate(panel["series"]):
            color = tuple(s.get("color") or PLOT_COLORS[si % len(PLOT_COLORS)])
            pts = [(sx(x), sy(y)) for x, y in zip(s["x"], s["y"])
                   if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)]
            if len(pts) > 1 and not s.get("dots"):
                d.line(pts, fill=color, width=2)
            if s.get("dots") or len(pts) == 1:
                for x, y in pts:
                    d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=color)
            label = s.get("label", "")
            d.line([lx, py0 + 14, lx + 18, py0 + 14], fill=color, width=3)
            d.text((lx + 22, py0 + 8), label, fill=(0, 0, 0), font=font)
            lx += 30 + 7 * len(label)
        d.text((px0, y0 + 4), panel.get("title", ""), fill=(0, 0, 0), font=font)
        if panel.get("xlabel"):
            d.text((px1 - 7 * len(panel["xlabel"]), py1 + 18), panel["xlabel"], fill=(60, 60, 60), font=font)
        if panel.get("ylabel"):
            d.text((px0 + 4, py1 - 14), panel["ylabel"], fill=(60, 60, 60), font=font)
    ensure_parent(path)
    img.save(path)
    return path
