#!/usr/bin/env python3
"""Lay out frames as a labeled grid, so a sequence can be reviewed in one image.

SOURCE is an extract_frames manifest.json (or its directory), or any directory of images.
Each tile is labeled with the source frame index and timestamp. When there are more frames
than --max, several sheets are written: sheet-1.png, sheet-2.png, ...

Examples:
  python contact_sheet.py frames/jump01/manifest.json --out sheets/jump01.png --cols 8 --scale 0.25
  python contact_sheet.py frames/ui --out sheets/ui.png --tile-width 480 --label time
  python contact_sheet.py ref/manifest.json --pair rec/manifest.json --out sheets/ref_vs_rec.png
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402


def collect(source: Path) -> list[tuple[Path, str]]:
    manifest_path = source if source.is_file() else source / "manifest.json"
    if manifest_path.is_file() and manifest_path.suffix == ".json":
        _, frames, base = rc.load_manifest(manifest_path)
        items = []
        for fr in frames:
            label = f"#{fr.get('index')}  {float(fr.get('pts_time', 0)):.3f}s"
            items.append((base / fr["file"], label))
        return items
    if source.is_dir():
        return [(p, p.stem) for p in rc.list_images(source)]
    rc.fail(f"{source} is neither a manifest nor a directory of images")


def label_for(text: str, mode: str) -> str:
    if mode == "none":
        return ""
    if mode == "index":
        return text.split("  ")[0]
    if mode == "time":
        return text.split("  ")[-1]
    return text


def build_sheet(items, cols, tile_w, label_mode, title):
    Image = rc.require_pil()
    from PIL import ImageDraw, ImageFont

    font = ImageFont.load_default()
    first = Image.open(items[0][0])
    aspect = first.height / first.width
    tile_h = max(1, int(round(tile_w * aspect)))
    label_h = 14 if label_mode != "none" else 0
    title_h = 18 if title else 0
    rows = math.ceil(len(items) / cols)
    sheet = Image.new("RGB", (cols * tile_w, title_h + rows * (tile_h + label_h)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    if title:
        draw.text((4, 3), title, fill=(255, 255, 255), font=font)
    for i, (path, text) in enumerate(items):
        try:
            with Image.open(path) as img:
                tile = img.convert("RGB").resize((tile_w, tile_h), Image.LANCZOS)
        except OSError as exc:
            rc.fail(f"cannot read {path}: {exc}")
        x = (i % cols) * tile_w
        y = title_h + (i // cols) * (tile_h + label_h)
        sheet.paste(tile, (x, y))
        if label_mode != "none":
            draw.rectangle([x, y + tile_h, x + tile_w, y + tile_h + label_h], fill=(0, 0, 0))
            draw.text((x + 3, y + tile_h + 1), label_for(text, label_mode), fill=(255, 230, 120), font=font)
        draw.rectangle([x, y, x + tile_w - 1, y + tile_h - 1], outline=(70, 70, 70))
    return sheet


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="manifest.json, its directory, or a directory of images")
    ap.add_argument("--out", type=Path, required=True, help="output PNG path")
    ap.add_argument("--pair", type=Path, help="second source; tiles alternate source/pair for side-by-side review")
    ap.add_argument("--cols", type=int, default=6)
    size = ap.add_mutually_exclusive_group()
    size.add_argument("--scale", type=float, help="tile scale relative to the source width (for example 0.25)")
    size.add_argument("--tile-width", type=int, help="tile width in pixels (default 320)")
    ap.add_argument("--every", type=int, default=1, help="use every Nth frame")
    ap.add_argument("--max", type=int, default=48, help="tiles per sheet (default 48)")
    ap.add_argument("--label", choices=["both", "index", "time", "none"], default="both")
    ap.add_argument("--title", help="optional title text")
    args = ap.parse_args()

    if args.cols < 1 or args.every < 1 or args.max < 1:
        rc.fail("--cols, --every and --max must be >= 1")
    items = collect(args.source)[:: args.every]
    if args.pair:
        other = collect(args.pair)[:: args.every]
        if len(other) != len(items):
            rc.fail(f"--pair has {len(other)} frames but the source has {len(items)}")
        merged = []
        for (pa, la), (pb, lb) in zip(items, other):
            merged += [(pa, "REF " + la), (pb, "REC " + lb)]
        items = merged
        if args.cols % 2:
            args.cols += 1
    if not items:
        rc.fail("no frames found")

    Image = rc.require_pil()
    with Image.open(items[0][0]) as probe:
        src_w = probe.width
    tile_w = int(round(src_w * args.scale)) if args.scale else (args.tile_width or 320)
    tile_w = max(16, tile_w)

    pages = [items[i: i + args.max] for i in range(0, len(items), args.max)]
    written = []
    for n, page in enumerate(pages, 1):
        sheet = build_sheet(page, min(args.cols, len(page)), tile_w, args.label, args.title)
        out = args.out if len(pages) == 1 else args.out.with_name(f"{args.out.stem}-{n}{args.out.suffix or '.png'}")
        rc.ensure_parent(out)
        sheet.save(out)
        written.append(str(out))
    print("wrote " + ", ".join(written))
    return 0


if __name__ == "__main__":
    rc.run_main(main)
