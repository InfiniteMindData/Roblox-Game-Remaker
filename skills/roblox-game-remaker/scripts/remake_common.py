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
