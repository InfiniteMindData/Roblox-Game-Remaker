#!/usr/bin/env python3
"""Extract dominant colors from a reference frame region, as hex and Color3.fromRGB.

Clusters pixels with k-means in CIELAB (perceptual) space using a fixed seed, so results are
repeatable. Use flat regions (sky, walls, UI panels); anti-aliased edges and compression noise
create spurious clusters. Sample several frames and compare when colors matter.

Examples:
  python palette_extract.py frame.png --region 40,980,420,36 --k 4
  python palette_extract.py frame.png --points 120,40;800,600 --radius 3
  python palette_extract.py frame.png --k 8 --json --swatch palette.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402
from visual_compare import srgb_to_lab  # noqa: E402

TOOL = "palette_extract"


def kmeans(data, k: int, iterations: int = 30, seed: int = 0):
    np = rc.require_numpy()
    rng = np.random.default_rng(seed)
    # k-means++ initialisation
    centers = [data[rng.integers(len(data))]]
    for _ in range(1, k):
        d2 = np.min(((data[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        total = d2.sum()
        if total <= 0:
            break
        centers.append(data[rng.choice(len(data), p=d2 / total)])
    centers = np.array(centers)
    labels = np.zeros(len(data), dtype=int)
    for _ in range(iterations):
        dist = ((data[:, None, :] - centers[None]) ** 2).sum(-1)
        new = dist.argmin(axis=1)
        if np.array_equal(new, labels) and _ > 0:
            break
        labels = new
        for i in range(len(centers)):
            members = data[labels == i]
            if len(members):
                centers[i] = members.mean(axis=0)
    return centers, labels


def color_entry(rgb, share=None, lab=None):
    r, g, b = [int(round(max(0.0, min(1.0, c)) * 255)) for c in rgb]
    entry = {"hex": f"#{r:02X}{g:02X}{b:02X}", "rgb": [r, g, b], "luau": f"Color3.fromRGB({r}, {g}, {b})"}
    if share is not None:
        entry["share"] = round(float(share), 4)
    if lab is not None:
        entry["lab"] = [round(float(v), 2) for v in lab]
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("--region", help="x,y,w,h region (default: whole image)")
    ap.add_argument("--points", help="semicolon-separated x,y points to sample instead of clustering")
    ap.add_argument("--radius", type=int, default=2, help="half-size of the averaging window for --points (default 2 = 5x5)")
    ap.add_argument("--k", type=int, default=6, help="number of clusters (default 6)")
    ap.add_argument("--samples", type=int, default=20000, help="max pixels sampled for clustering")
    ap.add_argument("--min-share", type=float, default=0.01, help="drop clusters smaller than this share")
    ap.add_argument("--swatch", type=Path, help="write a swatch PNG")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    np = rc.require_numpy()
    img = rc.load_rgb(args.image)
    H, W = img.shape[:2]
    result = {"tool": TOOL, "image": str(args.image)}

    if args.points:
        colors = []
        for part in args.points.split(";"):
            try:
                x, y = (int(v) for v in part.split(","))
            except ValueError:
                rc.fail(f"--points entries must be x,y (got {part!r})")
            if not (0 <= x < W and 0 <= y < H):
                rc.fail(f"point {x},{y} is outside the {W}x{H} image")
            r = args.radius
            patch = img[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].reshape(-1, 3)
            mean = patch.mean(axis=0)
            e = color_entry(mean, lab=srgb_to_lab(mean[None])[0])
            e["point"] = [x, y]
            e["std_rgb"] = [round(float(v) * 255, 2) for v in patch.std(axis=0)]
            colors.append(e)
        result["mode"] = "points"
        result["colors"] = colors
    else:
        if args.k < 1:
            rc.fail("--k must be >= 1")
        if args.region:
            x, y, w, h = rc.parse_bbox(args.region, "--region")
            if x + w > W or y + h > H:
                rc.fail(f"--region lies outside the {W}x{H} image")
            px = img[y:y + h, x:x + w].reshape(-1, 3)
            result["region"] = [x, y, w, h]
        else:
            px = img.reshape(-1, 3)
        rng = np.random.default_rng(0)
        if len(px) > args.samples:
            px = px[rng.choice(len(px), args.samples, replace=False)]
        lab = srgb_to_lab(px)
        centers, labels = kmeans(lab, min(args.k, len(px)))
        colors = []
        for i in range(len(centers)):
            members = labels == i
            share = members.mean()
            if share < args.min_share:
                continue
            colors.append(color_entry(px[members].mean(axis=0), share, centers[i]))
        colors.sort(key=lambda c: c["share"], reverse=True)
        result["mode"] = "kmeans"
        result["colors"] = colors

    if args.swatch:
        Image = rc.require_pil()
        from PIL import ImageDraw, ImageFont
        sw = Image.new("RGB", (160 * len(result["colors"]), 80), (0, 0, 0))
        d = ImageDraw.Draw(sw)
        font = ImageFont.load_default()
        for i, c in enumerate(result["colors"]):
            d.rectangle([i * 160, 0, i * 160 + 159, 60], fill=tuple(c["rgb"]))
            d.text((i * 160 + 4, 64), f"{c['hex']} {c.get('share', '')}", fill=(255, 255, 255), font=font)
        rc.ensure_parent(args.swatch)
        sw.save(args.swatch)

    if args.json:
        print(rc.dump_json(result))
    else:
        for c in result["colors"]:
            share = f"{c['share']:6.1%}" if "share" in c else "      "
            where = f" at {c['point']}" if "point" in c else ""
            print(f"{share}  {c['hex']}  {c['luau']}{where}")
    return 0


if __name__ == "__main__":
    rc.run_main(main)
