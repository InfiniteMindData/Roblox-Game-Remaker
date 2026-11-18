#!/usr/bin/env python3
"""Find moving objects in a frame sequence and suggest boxes for motion_track.

Method:
  1. Estimate the camera motion of every frame against the first (shift, zoom and roll, sub-pixel;
     the whole-frame model from motion_track.py) and warp every frame onto the first one. Frames
     are streamed, never all held in memory. Pass --static to skip.
  2. Pick the two aligned frames that differ most from the first frame and from each other
     (among frames that still overlap the first one by at least 60%).
  3. Pixels that differ from BOTH are where a mover sits in the first frame; connected
     regions of them become candidate boxes (in first-frame source pixels).
  4. When the camera moves, also suggest a textured static patch for --anchor-bbox. Regions that
     stay put on screen while the world moves are either an overlay (HUD) or the player under a
     camera that follows them: compact, upright ones near the middle of the screen are reported first as
     "probable player (camera follows)" (kind probable_player_camera_follows), the rest as
     screen_fixed_regions.

It finds rigid or roughly rigid movers well (characters, props, UI elements). Always confirm
the top candidate with frame_zoom.py --mark before tracking.

Examples:
  python find_mover.py frames/jump01/manifest.json
  python find_mover.py frames/run01/manifest.json --preview candidates.png --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import motion_track as mt  # noqa: E402
import remake_common as rc  # noqa: E402

TOOL = "find_mover"


def warp_to_first(img, S):
    """Resample img onto the first frame's pixel grid: out[p] = img[S(p)], bilinear; NaN outside."""
    np = rc.require_numpy()
    h, w = img.shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    u, v = mt.sim_apply(S, xs + 0.5, ys + 0.5)
    u, v = u - 0.5, v - 0.5
    inside = (u >= 0) & (v >= 0) & (u <= w - 1) & (v <= h - 1)
    u0 = np.clip(np.floor(u).astype(int), 0, w - 2)
    v0 = np.clip(np.floor(v).astype(int), 0, h - 2)
    fu, fv = np.clip(u - u0, 0, 1), np.clip(v - v0, 0, 1)
    out = (img[v0, u0] * (1 - fu) * (1 - fv) + img[v0, u0 + 1] * fu * (1 - fv)
           + img[v0 + 1, u0] * (1 - fu) * fv + img[v0 + 1, u0 + 1] * fu * fv)
    return np.where(inside, out, np.nan).astype(np.float32)


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


def merge_boxes(found, gap: int = 2):
    """Merge components whose boxes touch or nearly touch (a character's limbs and torso)."""
    boxes = [list(c) for c in found]
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if a[0] - gap <= b[0] + b[2] and b[0] - gap <= a[0] + a[2] and a[1] - gap <= b[1] + b[3] and b[1] - gap <= a[1] + a[3]:
                    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
                    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
                    boxes[i] = [x0, y0, x1 - x0, y1 - y0, a[4] + b[4]]
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    return sorted((tuple(b) for b in boxes), key=lambda c: c[4], reverse=True)


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
    H, W = full0.shape[0] // d, full0.shape[1] // d
    del full0

    def load(i):
        return rc.load_gray(base / frames[i]["file"], d)

    def changed(a, b):
        """Share of the overlapping pixels that clearly changed (resampling and compression noise excluded)."""
        df = np.abs(a - b)
        fin = np.isfinite(df)
        if not fin.any():
            return -1.0
        v = df[fin]
        return float((v > max(12.0, 6 * float(np.median(v)))).mean())

    # Pass 1 (streamed): camera motion of every frame, how much it differs from the first, how much overlaps.
    ref = load(0)
    cam = None if args.static else mt.CameraMotion(ref, out_scale=1.0, max_width=max(ref.shape[1], 64))
    S_all, energy, cover, cam_ok = [mt.IDENTITY], [-1.0], [1.0], [True]
    for i in range(1, len(frames)):
        img = load(i)
        if cam:
            info = cam.update(img)
            S, ok = info["S"], info["ok"] and info["chain_ok"]
        else:
            S, ok = mt.IDENTITY, True
        al = warp_to_first(img, S) if S != mt.IDENTITY else img
        fin = np.isfinite(al)
        S_all.append(S)
        cam_ok.append(ok)
        cover.append(float(fin.mean()))
        energy.append(changed(al, ref) if fin.any() and ok else -1.0)
    usable = [i for i in range(1, len(frames)) if cover[i] >= 0.6 and cam_ok[i]]
    if not usable:
        rc.fail("no frame overlaps the first one by 60% with a measured camera; use a shorter range of frames", rc.EXIT_FAIL)
    j = max(usable, key=lambda i: energy[i])
    img_j = load(j)
    al_j = warp_to_first(img_j, S_all[j])
    diff_j = np.abs(al_j - ref)
    noise = float(np.nanmedian(diff_j))
    thr = args.threshold if args.threshold is not None else max(12.0, 6 * noise)
    # Pass 2 (streamed): the frame most different from both, and every mover's trail (keeps the anchor off it).
    second = {}
    trail = np.zeros(ref.shape, bool)
    # Screen-fixed pixels (HUD) stay the same on the raw frames however far the camera has moved.
    stable, n_far = np.zeros(ref.shape, np.int32), 0
    stable_thr = max(4.0, 2 * noise)
    for i in usable:
        img = img_j if i == j else load(i)
        al = al_j if i == j else warp_to_first(img, S_all[i])
        df = np.abs(al - ref)
        trail |= np.nan_to_num(df) > thr
        sx, sy = mt.sim_apply(S_all[i], ref.shape[1] / 2.0, ref.shape[0] / 2.0)
        if math.hypot(sx - ref.shape[1] / 2.0, sy - ref.shape[0] / 2.0) > 8:
            stable += np.abs(img - ref) < stable_thr
            n_far += 1
        if i != j:
            second[i] = min(energy[i], changed(al, al_j))
    k = max(second, key=second.get) if second else j
    img_k = load(k)
    al_k = warp_to_first(img_k, S_all[k])
    diff_k = np.abs(al_k - ref)
    mask = (np.nan_to_num(diff_j) > thr) & (np.nan_to_num(diff_k) > thr)
    covered = np.isfinite(al_j) & np.isfinite(al_k)
    mask = dilate(mask, 1) & covered  # ignore borders uncovered by camera motion
    overlay = np.zeros_like(mask)

    def centre_shift(S):
        x, y = mt.sim_apply(S, W / 2.0, H / 2.0)
        return math.hypot(x - W / 2.0, y - H / 2.0)

    okS = [S for S, o in zip(S_all, cam_ok) if o]
    scales = [mt.sim_scale(S) for S in okS]
    zoom_span = max(scales) / min(scales)
    max_shift = max(centre_shift(S) for S in okS) * d
    moves = max_shift > 2 or zoom_span > 1.01
    if moves:
        # Screen-fixed pixels (HUD, watermarks, or the player under a follow camera) barely change on
        # screen while the world moves under them, so camera compensation makes them look like movers.
        raw = [np.abs(img_j - ref), np.abs(img_k - ref)]
        typical = max(1.0, float(np.median(raw[0])))
        overlay = (raw[0] < 0.5 * typical) & (raw[1] < 0.5 * typical) & mask
        overlay = dilate(overlay, 2)
        mask &= ~overlay
        # Their ghosts: where an aligned frame shows a screen-fixed region at a different place (a HUD
        # panel seen through the camera compensation) is not a mover either. Found on the raw frames, so
        # a HUD the camera has moved away from still counts; textured pixels only (flat sky is static too).
        screen_fixed = dilate(stable >= 0.9 * n_far, 2) if n_far >= 3 else np.zeros_like(mask)
        for S in (S_all[j], S_all[k]):
            ghost = warp_to_first(screen_fixed.astype(np.float32), S)
            mask &= ~(np.nan_to_num(ghost) > 0.25)
        overlay |= screen_fixed & ~covered
    cands = merge_boxes(components(mask, min_area=max(4, mask.size // 20000)))
    if cands:
        cands = [c for c in cands if c[4] >= 0.1 * cands[0][4]]

    def unpad(c, r):
        cx, cy, cw, ch = c[:4]
        if cw > 2 * r and ch > 2 * r:  # undo the dilation
            cx, cy, cw, ch = cx + r, cy + r, cw - 2 * r, ch - 2 * r
        return [cx, cy, cw, ch]

    results = [{"bbox": unpad(c, 1), "area": c[4], "kind": "mover"} for c in cands]
    # Screen-fixed regions are HUD, or the player under a camera that follows them (Roblox's default
    # camera): a compact, upright one near the middle of the screen is offered first, merged with any
    # mover fragments touching it (the parts of the character that do move on screen).
    hud, followed = [], None
    for c in merge_boxes(components(overlay, min_area=max(16, overlay.size // 5000)))[:6]:
        cx, cy, cw, ch = unpad(c, 2)
        mx, my = cx + cw / 2.0, cy + ch / 2.0
        central = abs(mx - W / 2.0) <= 0.15 * W and abs(my - H / 2.0) <= 0.25 * H  # where a follow camera keeps it
        upright = ch >= 0.8 * cw  # characters stand taller than wide; HUD bars and panels rarely do
        if followed is None and central and upright and cw * ch <= 0.15 * W * H:
            followed = {"bbox": [cx, cy, cw, ch], "area": c[4], "kind": "probable_player_camera_follows"}
        elif not any(x - 3 <= cx + cw and cx - 3 <= x + w and y - 3 <= cy + ch and cy - 3 <= y + h and c[4] < r["area"]
                     for r in results[:1] for x, y, w, h in [r["bbox"]]):
            # (a smaller still piece touching the main mover is part of it, e.g. a foot planted while running)
            hud.append([int(cx * d), int(cy * d), int(cw * d), int(ch * d)])
    if followed:
        fx, fy, fw, fh = followed["bbox"]
        rest = []
        for r in results:
            x, y, w, h = r["bbox"]
            if x - 3 <= fx + fw and fx - 3 <= x + w and y - 3 <= fy + fh and fy - 3 <= y + h:
                x0, y0 = min(x, fx), min(y, fy)
                fx, fy, fw, fh = x0, y0, max(x + w, fx + fw) - x0, max(y + h, fy + fh) - y0
                followed["area"] += r["area"]
            else:
                rest.append(r)
        followed["bbox"] = [fx, fy, fw, fh]
        results = [followed] + rest
    out_c = []
    for r in results[: args.max_candidates]:
        x, y, w, h = r["bbox"]
        out_c.append({"bbox": [int(x * d), int(y * d), int(min(W - x, w) * d), int(min(H - y, h) * d)],
                      "area_px": int(r["area"] * d * d), "kind": r["kind"]})
    results = out_c

    anchor = None
    if moves and results:
        gy, gx = np.gradient(ref)
        energy_map = np.hypot(gx, gy) * covered
        # Keep the anchor off everything that moves at any time (the movers' whole paths).
        busy = dilate(trail, 3) | dilate(overlay, 3)
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

    per_frame = []
    for f, S, o in zip(frames, S_all, cam_ok):
        sx, sy = mt.sim_apply(S, W / 2.0, H / 2.0)
        per_frame.append({"index": f.get("index"), "dx": round(-(sx - W / 2.0) * d, 2), "dy": round(-(sy - H / 2.0) * d, 2),
                          "scale": round(mt.sim_scale(S), 5), "roll_deg": round(mt.sim_roll_deg(S), 3), "measured": bool(o)})
    out = {"tool": TOOL, "manifest": str(args.manifest), "downscale": d, "threshold": round(thr, 2),
           "reference_frames": [frames[j].get("index"), frames[k].get("index")],
           "camera_moves": bool(moves), "max_camera_shift_px": int(max_shift),
           "camera_zoom_range": [round(min(scales), 4), round(max(scales), 4)],
           "camera_unmeasured_frames": int(sum(1 for o in cam_ok if not o)),
           "candidates": results, "anchor_bbox": anchor, "screen_fixed_regions": hud, "camera_shift": per_frame}
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
        z = out["camera_zoom_range"]
        print(f"camera {'moves' if out['camera_moves'] else 'is static'} (max shift {out['max_camera_shift_px']} px"
              f"{f', zoom {z[0]:.3f}-{z[1]:.3f}' if z[1] / z[0] > 1.01 else ''}); "
              f"compared frames {out['reference_frames']}; threshold {out['threshold']}")
        if not results:
            print("no moving object found; lower --threshold, or check that the subject moves in this range")
        for i, r in enumerate(results, 1):
            what = ("  probable player: it stays put on screen while the world moves (the camera follows it)"
                    if r["kind"] == "probable_player_camera_follows" else "")
            print(f"#{i} bbox {','.join(map(str, r['bbox']))}  area {r['area_px']} px{what}")
        if anchor:
            print(f"anchor (static, textured): {','.join(map(str, anchor))}")
        for r in out["screen_fixed_regions"]:
            print(f"screen-fixed overlay (HUD?) left out: {','.join(map(str, r))} (mask it in visual_compare; keep boxes off it)")
        if results:
            print("next: " + out["suggested_command"])
            print("confirm first: python scripts/frame_zoom.py <first frame> --region <around the box> --mark <bbox>")
    return 0 if results else rc.EXIT_FAIL


if __name__ == "__main__":
    rc.run_main(main)
