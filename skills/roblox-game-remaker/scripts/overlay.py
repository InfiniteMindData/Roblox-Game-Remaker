#!/usr/bin/env python3
"""Overlay a reference and a recreation (or a frame sequence) in one image.

Modes:
  blend REF REC [--alpha 0.5]       semi-transparent overlay: misalignment shows as ghosting
  diff REF REC [--gain 4]           amplified absolute difference in false color
  checker REF REC [--tile 64]       alternating tiles: edges that do not continue across tiles are offsets
  wipe REF REC [--position 0.5]     reference left of the line, recreation right
  onion MANIFEST [--every N] [--max 8]  onion skin of a sequence: old frames blue, new frames red

REC is resized to REF's size. Everything writes one PNG to --out.

Examples:
  python overlay.py blend ref.png rec.png --out remake/diff/shot03-blend.png
  python overlay.py checker ref.png rec.png --tile 48 --out remake/diff/shot03-checker.png
  python overlay.py onion remake/frames/jump01/manifest.json --every 4 --out remake/sheets/jump01-onion.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402


def pair(args):
    np = rc.require_numpy()
    Image = rc.require_pil()
    ref = rc.load_rgb(args.reference)
    rec = rc.load_rgb(args.recreation)
    if rec.shape[:2] != ref.shape[:2]:
        img = rc.to_uint8_image(rec).resize((ref.shape[1], ref.shape[0]), Image.LANCZOS)
        rec = np.asarray(img, dtype=np.float32) / 255.0
    return ref, rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    for mode in ("blend", "diff", "checker", "wipe"):
        p = sub.add_parser(mode)
        p.add_argument("reference", type=Path)
        p.add_argument("recreation", type=Path)
        p.add_argument("--out", type=Path, required=True)
        if mode == "blend":
            p.add_argument("--alpha", type=float, default=0.5, help="recreation weight 0..1")
        if mode == "diff":
            p.add_argument("--gain", type=float, default=4.0)
        if mode == "checker":
            p.add_argument("--tile", type=int, default=64)
        if mode == "wipe":
            p.add_argument("--position", type=float, default=0.5)
            p.add_argument("--vertical", action="store_true", help="split top/bottom instead of left/right")
    p = sub.add_parser("onion")
    p.add_argument("manifest", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--every", type=int, default=1)
    p.add_argument("--max", type=int, default=8)
    args = ap.parse_args()

    np = rc.require_numpy()
    if args.mode == "onion":
        _, frames, base = rc.load_manifest(args.manifest)
        frames = frames[:: max(1, args.every)][: max(2, args.max)]
        if len(frames) < 2:
            rc.fail("onion needs at least 2 frames")
        imgs = [rc.load_rgb(base / f["file"]) for f in frames]
        bg = np.median(np.stack(imgs), axis=0)
        out = bg * 0.6
        for i, im in enumerate(imgs):
            w = i / (len(imgs) - 1)
            tint = np.array([0.25 + 0.75 * w, 0.35, 1.0 - 0.75 * w])
            fg = np.abs(im - bg).max(axis=2, keepdims=True) > 0.08
            out = np.where(fg, im * 0.4 + tint * 0.6, out)
        result = out
        note = f"{len(frames)} frames ({frames[0].get('index')}..{frames[-1].get('index')}), blue = oldest, red = newest"
    else:
        ref, rec = pair(args)
        if args.mode == "blend":
            if not 0 <= args.alpha <= 1:
                rc.fail("--alpha must be between 0 and 1")
            result = ref * (1 - args.alpha) + rec * args.alpha
        elif args.mode == "diff":
            d = np.clip(np.abs(ref - rec).mean(axis=2) * args.gain, 0, 1)
            result = np.stack([d, d ** 2, 0.15 * (1 - d)], axis=-1)
        elif args.mode == "checker":
            if args.tile < 2:
                rc.fail("--tile must be >= 2")
            yy, xx = np.mgrid[0:ref.shape[0], 0:ref.shape[1]]
            sel = ((yy // args.tile + xx // args.tile) % 2 == 0)[..., None]
            result = np.where(sel, ref, rec)
        else:
            if not 0 <= args.position <= 1:
                rc.fail("--position must be between 0 and 1")
            result = rec.copy()
            if args.vertical:
                cut = int(ref.shape[0] * args.position)
                result[:cut] = ref[:cut]
                result[max(0, cut - 1):cut + 1] = (1.0, 0.2, 0.8)
            else:
                cut = int(ref.shape[1] * args.position)
                result[:, :cut] = ref[:, :cut]
                result[:, max(0, cut - 1):cut + 1] = (1.0, 0.2, 0.8)
        note = f"{args.mode} of {args.reference.name} (reference) and {args.recreation.name} (recreation)"
    rc.ensure_parent(args.out)
    rc.to_uint8_image(result).save(args.out)
    print(f"wrote {args.out}: {note}")
    return 0


if __name__ == "__main__":
    rc.run_main(main)
