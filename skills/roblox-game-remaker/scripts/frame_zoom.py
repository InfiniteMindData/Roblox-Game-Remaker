#!/usr/bin/env python3
"""Zoom into a frame region with a labeled pixel grid, to read exact coordinates.

Use it before motion_track, ui_measure or palette_extract: instead of estimating a box from
a full frame, zoom into the area, read the coordinates off the rulers (always in source-frame
pixels), and draw the candidate box with --mark to confirm it before tracking.

Examples:
  python frame_zoom.py frame.png --region 260,260,80,80 --scale 8 --grid 8 --out zoom.png
  python frame_zoom.py frame.png --region 260,260,80,80 --mark 288,288,24,24 --out check.png
  python frame_zoom.py frame.png --region 0,940,520,140 --scale 3 --grid 20 --point 48,980 --out hud.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

COLORS = [(255, 60, 60), (60, 220, 255), (255, 210, 40), (120, 255, 120)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("--region", required=True, help="x,y,w,h in source pixels")
    ap.add_argument("--scale", type=int, help="integer zoom (default: fit about 960 px wide)")
    ap.add_argument("--grid", type=int, default=0, help="grid spacing in source pixels (default: automatic)")
    ap.add_argument("--mark", action="append", default=[], help="x,y,w,h box to draw (repeatable)")
    ap.add_argument("--point", action="append", default=[], help="x,y crosshair to draw (repeatable)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    Image = rc.require_pil()
    from PIL import ImageDraw, ImageFont

    try:
        img = Image.open(args.image).convert("RGB")
    except OSError as exc:
        rc.fail(f"cannot read {args.image}: {exc}")
    x, y, w, h = rc.parse_bbox(args.region, "--region")
    if x + w > img.width or y + h > img.height:
        rc.fail(f"--region lies outside the {img.width}x{img.height} image")
    scale = args.scale or max(1, min(32, 960 // w))
    grid = args.grid or next(g for g in (1, 2, 4, 5, 8, 10, 20, 25, 50, 100, 200) if g * scale >= 40)
    crop = img.crop((x, y, x + w, y + h)).resize((w * scale, h * scale), Image.NEAREST)
    margin_l, margin_t = 44, 18
    canvas = Image.new("RGB", (crop.width + margin_l, crop.height + margin_t), (20, 20, 20))
    canvas.paste(crop, (margin_l, margin_t))
    d = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    first_x = ((x + grid - 1) // grid) * grid
    for gx in range(first_x, x + w + 1, grid):
        px = margin_l + (gx - x) * scale
        d.line([(px, margin_t), (px, canvas.height)], fill=(255, 255, 255) if gx % (grid * 5) == 0 else (110, 110, 110))
        d.text((px + 2, 3), str(gx), fill=(255, 230, 120), font=font)
    first_y = ((y + grid - 1) // grid) * grid
    for gy in range(first_y, y + h + 1, grid):
        py = margin_t + (gy - y) * scale
        d.line([(margin_l, py), (canvas.width, py)], fill=(255, 255, 255) if gy % (grid * 5) == 0 else (110, 110, 110))
        d.text((2, py + 1), str(gy), fill=(255, 230, 120), font=font)
    for i, m in enumerate(args.mark):
        mx, my, mw, mh = rc.parse_bbox(m, "--mark")
        color = COLORS[i % len(COLORS)]
        d.rectangle([margin_l + (mx - x) * scale, margin_t + (my - y) * scale,
                     margin_l + (mx + mw - x) * scale - 1, margin_t + (my + mh - y) * scale - 1], outline=color, width=2)
        d.text((margin_l + (mx - x) * scale + 3, margin_t + (my - y) * scale + 2), m, fill=color, font=font)
    for p in args.point:
        try:
            ptx, pty = (int(v) for v in p.split(","))
        except ValueError:
            rc.fail(f"--point must be x,y (got {p!r})")
        cx, cy = margin_l + (ptx - x) * scale + scale // 2, margin_t + (pty - y) * scale + scale // 2
        d.line([(cx - 10, cy), (cx + 10, cy)], fill=(255, 0, 255), width=2)
        d.line([(cx, cy - 10), (cx, cy + 10)], fill=(255, 0, 255), width=2)
        r, g, b = img.getpixel((ptx, pty))
        d.text((cx + 6, cy + 6), f"{ptx},{pty} #{r:02X}{g:02X}{b:02X}", fill=(255, 0, 255), font=font)
    rc.ensure_parent(args.out)
    canvas.save(args.out)
    print(f"wrote {args.out}: region {x},{y},{w},{h} at {scale}x, grid every {grid} px (labels are source-frame pixels)")
    return 0


if __name__ == "__main__":
    rc.run_main(main)
