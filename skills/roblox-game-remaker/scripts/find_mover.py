#!/usr/bin/env python3
"""Find moving objects in a frame sequence and suggest boxes for motion_track.

Method:
  1. Estimate the camera's translation per frame against the first frame (FFT phase
     correlation) and align every frame to the first one. Pass --static to skip.
  2. Pick the two aligned frames that differ most from the first frame and from each other.
  3. Pixels that differ from BOTH are where a mover sits in the first frame; connected
     regions of them become candidate boxes (in first-frame source pixels).
  4. When the camera moves, also suggest a textured static patch for --anchor-bbox.

It finds rigid or roughly rigid movers well (characters, props, UI elements). Always confirm
the top candidate with frame_zoom.py --mark before tracking.

Examples:
  python find_mover.py frames/jump01/manifest.json
  python find_mover.py frames/run01/manifest.json --preview candidates.png --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "find_mover"


def phase_shift(a, b):
    """Integer (dy, dx) such that b shifted by (dy, dx) best matches a."""
    np = rc.require_numpy()
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    A = np.fft.fft2((a - a.mean()) * win)
    B = np.fft.fft2((b - b.mean()) * win)
    R = A * np.conj(B)
    R /= np.abs(R) + 1e-9
    r = np.fft.ifft2(R).real
    dy, dx = np.unravel_index(int(np.argmax(r)), r.shape)
    if dy > a.shape[0] // 2:
        dy -= a.shape[0]
    if dx > a.shape[1] // 2:
        dx -= a.shape[1]
    return int(dy), int(dx)


def shifted(img, dy, dx):
    """Shift img by (dy, dx); uncovered pixels become NaN."""
    np = rc.require_numpy()
    out = np.full(img.shape, np.nan, dtype=np.float32)
    h, w = img.shape
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    out[yd, xd] = img[ys, xs]
    return out


def components(mask, min_area: int):
    np = rc.require_numpy()
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    found = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        q = deque([(y0, x0)])
        seen[y0, x0] = True
        ys, xs = [], []
        while q:
            y, x = q.popleft()
            ys.append(y)
            xs.append(x)
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        if len(ys) >= min_area:
            found.append((min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1, len(ys)))
    return sorted(found, key=lambda c: c[4], reverse=True)


def dilate(mask, r: int):
    np = rc.require_numpy()
    out = mask.copy()
    for _ in range(r):
        p = np.pad(out, 1)
        out = p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--static", action="store_true", help="assume a fixed camera (skip alignment)")
    ap.add_argument("--threshold", type=float, help="difference threshold 0-255 (default: automatic)")
    ap.add_argument("--max-candidates", type=int, default=5)
    ap.add_argument("--preview", type=Path, help="write the first frame with candidate boxes drawn")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    np = rc.require_numpy()
    _, frames, base = rc.load_manifest(args.manifest)
    if len(frames) < 3:
        rc.fail("need at least 3 frames")
    full0 = rc.load_gray(base / frames[0]["file"])
    d = max(1, int(np.ceil(full0.shape[1] / 480)))
    imgs = [rc.load_gray(base / f["file"], d) for f in frames]
    ref = imgs[0]
    shifts = [(0, 0)] + [((0, 0) if args.static else phase_shift(ref, im)) for im in imgs[1:]]
    aligned = [ref] + [shifted(im, dy, dx) for im, (dy, dx) in zip(imgs[1:], shifts[1:])]
    diffs = [np.abs(a - ref) for a in aligned]
    energy = [float(np.nanmean(df)) if np.isfinite(df).any() else 0.0 for df in diffs]
    energy[0] = -1.0
    j = int(np.argmax(energy))
    second = [min(energy[i], float(np.nanmean(np.abs(aligned[i] - aligned[j])))) if i not in (0, j) else -1.0
              for i in range(len(aligned))]
    k = int(np.argmax(second))
    noise = float(np.nanmedian(diffs[j]))
    thr = args.threshold if args.threshold is not None else max(12.0, 6 * noise)
    mask = (np.nan_to_num(diffs[j]) > thr) & (np.nan_to_num(diffs[k]) > thr)
    covered = np.all([np.isfinite(a) for a in aligned], axis=0)
    mask = dilate(mask, 1) & covered  # ignore borders uncovered by camera motion
    cands = components(mask, min_area=max(4, mask.size // 20000))
    if cands:
        cands = [c for c in cands if c[4] >= 0.1 * cands[0][4]][: args.max_candidates]
    max_shift = max(abs(s[0]) + abs(s[1]) for s in shifts) * d
    results = []
    for (cx, cy, cw, ch, area) in cands:
        if cw > 2 and ch > 2:  # undo the one-pixel dilation
            cx, cy, cw, ch = cx + 1, cy + 1, cw - 2, ch - 2
        bx, by = cx * d, cy * d
        bw, bh = min(full0.shape[1] - bx, cw * d), min(full0.shape[0] - by, ch * d)
        results.append({"bbox": [int(bx), int(by), int(bw), int(bh)], "area_px": int(area * d * d)})

    anchor = None
    if max_shift > 2 and results:
        gy, gx = np.gradient(ref)
        energy_map = np.hypot(gx, gy) * covered
        # Keep the anchor off everything that moves at any time (the movers' whole paths).
        trail = np.zeros_like(covered)
        for df in diffs[1:]:
            trail |= np.nan_to_num(df) > thr
        busy = dilate(trail, 3)
        for r in results:
            x, y, w, h = (v // d for v in r["bbox"])
            busy[max(0, y - h):y + 2 * h, max(0, x - w):x + 2 * w] = True
        energy_map[busy] = 0
        size = max(8, 48 // d)
        best, best_xy = -1.0, None
        for yy in range(0, ref.shape[0] - size, max(1, size // 2)):
            for xx in range(0, ref.shape[1] - size, max(1, size // 2)):
                patch = energy_map[yy:yy + size, xx:xx + size]
                if (patch > 0).mean() < 0.95:
                    continue
                e = float(patch.mean())
                if e > best:
                    best, best_xy = e, (xx, yy)
        if best_xy:
            anchor = [best_xy[0] * d, best_xy[1] * d, size * d, size * d]

    per_frame = [{"index": f.get("index"), "dx": s[1] * d, "dy": s[0] * d} for f, s in zip(frames, shifts)]
    out = {"tool": TOOL, "manifest": str(args.manifest), "downscale": d, "threshold": round(thr, 2),
           "reference_frames": [frames[j].get("index"), frames[k].get("index")],
           "camera_moves": bool(max_shift > 2), "max_camera_shift_px": int(max_shift),
           "candidates": results, "anchor_bbox": anchor, "camera_shift": per_frame}
    if results:
        bb = ",".join(map(str, results[0]["bbox"]))
        cmd = f"python scripts/motion_track.py {args.manifest} --bbox {bb}"
        if anchor:
            cmd += " --anchor-bbox " + ",".join(map(str, anchor))
        out["suggested_command"] = cmd + " --px-per-unit <px per stud> --analyze jump|speed"
    if args.preview:
        Image = rc.require_pil()
        from PIL import ImageDraw

        im = Image.open(base / frames[0]["file"]).convert("RGB")
        dr = ImageDraw.Draw(im)
        for i, r in enumerate(results):
            x, y, w, h = r["bbox"]
            dr.rectangle([x, y, x + w - 1, y + h - 1], outline=(255, 60, 60) if i == 0 else (255, 210, 40), width=2)
            dr.text((x + 2, y - 12 if y > 12 else y + h + 2), f"#{i + 1} {x},{y},{w},{h}", fill=(255, 255, 255))
        if anchor:
            x, y, w, h = anchor
            dr.rectangle([x, y, x + w - 1, y + h - 1], outline=(60, 220, 255), width=2)
            dr.text((x + 2, y + 2), "anchor", fill=(60, 220, 255))
        rc.ensure_parent(args.preview)
        im.save(args.preview)
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"camera {'moves' if out['camera_moves'] else 'is static'} (max shift {out['max_camera_shift_px']} px); "
              f"compared frames {out['reference_frames']}; threshold {out['threshold']}")
        if not results:
            print("no moving object found; lower --threshold, or check that the subject moves in this range")
        for i, r in enumerate(results, 1):
            print(f"#{i} bbox {','.join(map(str, r['bbox']))}  area {r['area_px']} px")
        if anchor:
            print(f"anchor (static, textured): {','.join(map(str, anchor))}")
        if results:
            print("next: " + out["suggested_command"])
            print("confirm first: python scripts/frame_zoom.py <first frame> --region <around the box> --mark <bbox>")
    return 0 if results else rc.EXIT_FAIL


if __name__ == "__main__":
    rc.run_main(main)
