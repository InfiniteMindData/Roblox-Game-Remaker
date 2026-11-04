#!/usr/bin/env python3
"""Compare a reference frame with a Roblox recreation capture and report actionable metrics.

Metrics (computed on pixels not covered by --mask):
  ssim            structural similarity of luminance (0..1); sensitive to alignment
  psnr_db         peak signal-to-noise ratio of RGB
  delta_e_mean    mean CIEDE2000 color difference; delta_e_p95 its 95th percentile
  lab_shift       mean recreation-minus-reference dL (lightness), da (green->red), db (blue->yellow)
  chroma_ratio    recreation / reference mean chroma (saturation)
  contrast_ratio  recreation / reference lightness standard deviation
  edge_iou        overlap of edge maps (silhouette and layout, color-insensitive)
  worst_cells     grid cells with the largest mean delta E, in reference pixel coordinates
  hints           heuristic Roblox lighting and grading suggestions; always re-measure

Outputs in --out: report.json, side_by_side.png, heatmap.png, edges.png, blink.gif

Subcommands:
  pair REF REC --out DIR [--crop x,y,w,h] [--mask mask.png] [--grid 8x6] [--edges-only]
                 [--fail-under-ssim X] [--fail-over-delta-e Y] [--fail-under-edge-iou Z]
  batch SHOTS.json --out DIR [--root PATH] [--allow-missing]

Exit status: 0 = pass (or no thresholds), 1 = a threshold failed or a shot is missing,
2 = bad input.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "visual_compare"
SCHEMA = 1


# ----------------------------------------------------------------- color science

def srgb_to_lab(rgb):
    np = rc.require_numpy()
    c = np.clip(rgb, 0.0, 1.0)
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]], dtype=np.float64)
    xyz = lin.astype(np.float64) @ m.T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    eps = (6.0 / 29.0) ** 3
    f = np.where(xyz > eps, np.cbrt(xyz), xyz / (3 * (6.0 / 29.0) ** 2) + 4.0 / 29.0)
    L = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def ciede2000(lab1, lab2):
    """Vectorized CIEDE2000 (Sharma, Wu and Dalal 2005)."""
    np = rc.require_numpy()
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]
    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    Cbar7 = ((C1 + C2) / 2.0) ** 7
    G = 0.5 * (1 - np.sqrt(Cbar7 / (Cbar7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    zero = (C1p * C2p) == 0
    dLp = L2 - L1
    dCp = C2p - C1p
    dhp = h2p - h1p
    dhp = np.where(dhp > 180, dhp - 360, np.where(dhp < -180, dhp + 360, dhp))
    dhp = np.where(zero, 0.0, dhp)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp) / 2)
    Lbp = (L1 + L2) / 2
    Cbp = (C1p + C2p) / 2
    hsum = h1p + h2p
    hbp = np.where(np.abs(h1p - h2p) <= 180, hsum / 2,
                   np.where(hsum < 360, (hsum + 360) / 2, (hsum - 360) / 2))
    hbp = np.where(zero, hsum, hbp)
    T = (1 - 0.17 * np.cos(np.radians(hbp - 30)) + 0.24 * np.cos(np.radians(2 * hbp))
         + 0.32 * np.cos(np.radians(3 * hbp + 6)) - 0.20 * np.cos(np.radians(4 * hbp - 63)))
    dtheta = 30 * np.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cbp ** 7 / (Cbp ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / np.sqrt(20 + (Lbp - 50) ** 2)
    Sc = 1 + 0.045 * Cbp
    Sh = 1 + 0.015 * Cbp * T
    Rt = -np.sin(np.radians(2 * dtheta)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


# ----------------------------------------------------------------- image ops

def gaussian_blur(img, sigma: float = 1.5, radius: int = 5):
    np = rc.require_numpy()
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-(x ** 2) / (2 * sigma ** 2))
    k /= k.sum()
    out = img.astype(np.float64)
    for axis in (0, 1):
        pad = [(0, 0)] * out.ndim
        pad[axis] = (radius, radius)
        p = np.pad(out, pad, mode="reflect")
        acc = np.zeros_like(out)
        n = out.shape[axis]
        for i, w in enumerate(k):
            sl = [slice(None)] * out.ndim
            sl[axis] = slice(i, i + n)
            acc += w * p[tuple(sl)]
        out = acc
    return out


def luminance(rgb):
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def ssim_map(x, y):
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    mx, my = gaussian_blur(x), gaussian_blur(y)
    sxx = gaussian_blur(x * x) - mx * mx
    syy = gaussian_blur(y * y) - my * my
    sxy = gaussian_blur(x * y) - mx * my
    return ((2 * mx * my + c1) * (2 * sxy + c2)) / ((mx * mx + my * my + c1) * (sxx + syy + c2))


def edge_map(gray):
    np = rc.require_numpy()
    g = gaussian_blur(gray, sigma=1.0, radius=3)
    p = np.pad(g, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    mag = np.hypot(gx, gy)
    thr = max(float(np.quantile(mag, 0.88)), 0.08)
    edges = mag > thr
    d = np.pad(edges, 1)
    dil = np.zeros_like(edges)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            dil |= d[dy:dy + edges.shape[0], dx:dx + edges.shape[1]]
    return edges, dil


def resize_rgb(arr, size):
    np = rc.require_numpy()
    Image = rc.require_pil()
    img = rc.to_uint8_image(arr).resize(size, Image.LANCZOS)
    return np.asarray(img, dtype=np.float32) / 255.0


def colormap(t):
    np = rc.require_numpy()
    stops = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    cols = np.array([[0, 0, 0], [0.35, 0.0, 0.5], [0.85, 0.1, 0.1], [1.0, 0.8, 0.0], [1, 1, 1]])
    t = np.clip(t, 0, 1)
    return np.stack([np.interp(t, stops, cols[:, i]) for i in range(3)], axis=-1)


# ----------------------------------------------------------------- comparison

def parse_grid(text: str) -> tuple[int, int]:
    try:
        cols, rows = (int(v) for v in text.lower().split("x"))
    except ValueError:
        rc.fail(f"--grid must look like 8x6 (got {text!r})")
    if cols < 1 or rows < 1:
        rc.fail("--grid values must be >= 1")
    return cols, rows


def crop_arr(arr, crop):
    if not crop:
        return arr
    x, y, w, h = crop
    if y + h > arr.shape[0] or x + w > arr.shape[1]:
        rc.fail(f"crop {crop} lies outside the {arr.shape[1]}x{arr.shape[0]} image")
    return arr[y:y + h, x:x + w]


def build_hints(m: dict) -> list[str]:
    hints = []
    s = m["lab_shift"]
    if m.get("edge_iou") is not None and m["edge_iou"] < 0.35:
        hints.append("Structure differs (edge IoU < 0.35): align camera position, look-at and FOV before tuning color.")
    if s["dL"] < -2:
        hints.append(f"Recreation is darker (dL {s['dL']:+.1f}): raise Lighting.ExposureCompensation in ~0.25 steps, or Brightness.")
    elif s["dL"] > 2:
        hints.append(f"Recreation is brighter (dL {s['dL']:+.1f}): lower Lighting.ExposureCompensation in ~0.25 steps, or Brightness.")
    if s["db"] > 2:
        hints.append(f"Recreation is more yellow (db {s['db']:+.1f}): cool ColorCorrectionEffect.TintColor or the sun/ambient colors.")
    elif s["db"] < -2:
        hints.append(f"Recreation is more blue (db {s['db']:+.1f}): warm ColorCorrectionEffect.TintColor or the sun/ambient colors.")
    if s["da"] > 2:
        hints.append(f"Recreation is more red/magenta (da {s['da']:+.1f}): shift tint toward green.")
    elif s["da"] < -2:
        hints.append(f"Recreation is more green (da {s['da']:+.1f}): shift tint toward magenta.")
    cr = m.get("chroma_ratio")
    if cr is not None and cr < 0.9:
        hints.append(f"Recreation is less saturated (chroma ratio {cr:.2f}): raise ColorCorrectionEffect.Saturation.")
    elif cr is not None and cr > 1.1:
        hints.append(f"Recreation is more saturated (chroma ratio {cr:.2f}): lower ColorCorrectionEffect.Saturation.")
    ct = m.get("contrast_ratio")
    if ct is not None and ct < 0.9:
        hints.append(f"Recreation has less contrast ({ct:.2f}): raise ColorCorrectionEffect.Contrast or lower Ambient/OutdoorAmbient.")
    elif ct is not None and ct > 1.1:
        hints.append(f"Recreation has more contrast ({ct:.2f}): lower Contrast or raise Ambient/OutdoorAmbient.")
    return hints


def compare(ref_path: Path, rec_path: Path, out_dir: Path, *, crop=None, mask_path: Path | None = None,
            grid=(8, 6), edges_only=False, metric_width=1280, write_images=True) -> dict:
    np = rc.require_numpy()
    Image = rc.require_pil()
    ref_full = rc.load_rgb(ref_path)
    rec_full = rc.load_rgb(rec_path)
    notes = []
    ref = crop_arr(ref_full, crop)
    if crop and rec_full.shape[:2] != ref_full.shape[:2]:
        # Scale the crop to the recreation's resolution so both crops cover the same region.
        sy = rec_full.shape[0] / ref_full.shape[0]
        sx = rec_full.shape[1] / ref_full.shape[1]
        x, y, cw, ch = crop
        rec = crop_arr(rec_full, (int(round(x * sx)), int(round(y * sy)), max(1, int(round(cw * sx))), max(1, int(round(ch * sy)))))
        notes.append("recreation resolution differs from the reference; crop scaled proportionally")
    else:
        rec = crop_arr(rec_full, crop)
    ref_aspect = ref.shape[1] / ref.shape[0]
    rec_aspect = rec.shape[1] / rec.shape[0]
    if abs(ref_aspect - rec_aspect) / ref_aspect > 0.01:
        notes.append(f"aspect mismatch: reference {ref_aspect:.4f}, recreation {rec_aspect:.4f}; capture at the reference aspect ratio")
    h, w = ref.shape[:2]
    if metric_width and w > metric_width:
        scale = metric_width / w
        size = (metric_width, max(1, int(round(h * scale))))
        ref = resize_rgb(ref, size)
        notes.append(f"metrics computed at {size[0]}x{size[1]} (scale {scale:.3f}); cell boxes are in reference pixels")
    else:
        scale = 1.0
    if rec.shape[:2] != ref.shape[:2]:
        rec = resize_rgb(rec, (ref.shape[1], ref.shape[0]))
    valid = np.ones(ref.shape[:2], dtype=bool)
    if mask_path:
        try:
            with Image.open(mask_path) as mimg:
                mk = mimg.convert("L")
        except OSError as exc:
            rc.fail(f"cannot read mask {mask_path}: {exc}")
        full_size = (ref_full.shape[1], ref_full.shape[0])
        if mk.size != full_size:
            mk = mk.resize(full_size, Image.NEAREST)
        if crop:
            x, y, cw, ch = crop
            mk = mk.crop((x, y, x + cw, y + ch))
        mk = mk.resize((ref.shape[1], ref.shape[0]), Image.NEAREST)
        valid = np.asarray(mk) < 128
    if valid.sum() < 16:
        rc.fail("the mask leaves fewer than 16 pixels to compare")

    gref, grec = luminance(ref), luminance(rec)
    e_ref, d_ref = edge_map(gref)
    e_rec, d_rec = edge_map(grec)
    inter = ((e_ref & d_rec) | (e_rec & d_ref)) & valid
    union = (e_ref | e_rec) & valid
    edge_iou = float(inter.sum() / union.sum()) if union.sum() else 1.0

    metrics: dict = {"edge_iou": round(edge_iou, 4)}
    cols, rows = grid
    if not edges_only:
        smap = ssim_map(gref.astype(np.float64), grec.astype(np.float64))
        mse = float(((ref - rec) ** 2)[valid].mean())
        lab_ref, lab_rec = srgb_to_lab(ref), srgb_to_lab(rec)
        de = ciede2000(lab_ref, lab_rec)
        dv = de[valid]
        shift = (lab_rec[valid] - lab_ref[valid]).mean(axis=0)
        chroma_ref = np.hypot(lab_ref[..., 1], lab_ref[..., 2])[valid].mean()
        chroma_rec = np.hypot(lab_rec[..., 1], lab_rec[..., 2])[valid].mean()
        std_ref = lab_ref[..., 0][valid].std()
        std_rec = lab_rec[..., 0][valid].std()
        cells = []
        H, W = de.shape
        for r in range(rows):
            for c in range(cols):
                y0, y1 = r * H // rows, (r + 1) * H // rows
                x0, x1 = c * W // cols, (c + 1) * W // cols
                v = valid[y0:y1, x0:x1]
                if v.sum() == 0:
                    continue
                cells.append({
                    "cell": [c, r],
                    "box_ref_px": [int(x0 / scale), int(y0 / scale), int((x1 - x0) / scale), int((y1 - y0) / scale)],
                    "delta_e_mean": round(float(de[y0:y1, x0:x1][v].mean()), 3),
                    "dL": round(float((lab_rec[y0:y1, x0:x1, 0] - lab_ref[y0:y1, x0:x1, 0])[v].mean()), 3),
                })
        cells.sort(key=lambda c: c["delta_e_mean"], reverse=True)
        metrics.update({
            "ssim": round(float(smap[valid].mean()), 4),
            "psnr_db": round(10 * math.log10(1.0 / mse), 3) if mse > 0 else None,
            "delta_e_mean": round(float(dv.mean()), 3),
            "delta_e_p95": round(float(np.percentile(dv, 95)), 3),
            "lab_shift": {"dL": round(float(shift[0]), 3), "da": round(float(shift[1]), 3), "db": round(float(shift[2]), 3)},
            "chroma_ratio": round(float(chroma_rec / chroma_ref), 4) if chroma_ref > 1e-6 else None,
            "contrast_ratio": round(float(std_rec / std_ref), 4) if std_ref > 1e-6 else None,
            "worst_cells": cells[:5],
            "grid": [cols, rows],
        })
        metrics["hints"] = build_hints(metrics)

    report = {
        "tool": TOOL, "schema": SCHEMA,
        "reference": str(ref_path), "recreation": str(rec_path),
        "crop": list(crop) if crop else None, "mask": str(mask_path) if mask_path else None,
        "compared_pixels": int(valid.sum()),
        "metrics": metrics, "notes": notes,
    }

    if write_images:
        out_dir.mkdir(parents=True, exist_ok=True)
        ov = np.zeros(ref.shape, dtype=np.float32)
        ov[..., 1] = ov[..., 2] = e_ref  # reference edges: cyan
        ov[..., 0] = np.maximum(ov[..., 0], e_rec)  # recreation edges: magenta
        ov[..., 2] = np.maximum(ov[..., 2], e_rec)
        ov[e_ref & d_rec] = 1.0
        ov[~valid] *= 0.25
        rc.to_uint8_image(ov).save(out_dir / "edges.png")
        panels = [ref, rec]
        if not edges_only:
            heat = colormap(de / 20.0) * 0.8 + gref[..., None] * 0.2
            heat[~valid] = 0.1
            rc.to_uint8_image(heat).save(out_dir / "heatmap.png")
            panels.append(heat)
        else:
            panels.append(ov)
        side = np.concatenate(panels, axis=1)
        rc.to_uint8_image(side).save(out_dir / "side_by_side.png")
        a, b = rc.to_uint8_image(ref), rc.to_uint8_image(rec)
        a.save(out_dir / "blink.gif", save_all=True, append_images=[b], duration=500, loop=0)
        rc.write_json(out_dir / "report.json", report)
    return report


def evaluate(metrics: dict, thresholds: dict) -> list[str]:
    failures = []
    if thresholds.get("ssim") is not None and metrics.get("ssim") is not None and metrics["ssim"] < thresholds["ssim"]:
        failures.append(f"ssim {metrics['ssim']} < {thresholds['ssim']}")
    if thresholds.get("delta_e_mean") is not None and metrics.get("delta_e_mean") is not None and metrics["delta_e_mean"] > thresholds["delta_e_mean"]:
        failures.append(f"delta_e_mean {metrics['delta_e_mean']} > {thresholds['delta_e_mean']}")
    if thresholds.get("edge_iou") is not None and metrics["edge_iou"] < thresholds["edge_iou"]:
        failures.append(f"edge_iou {metrics['edge_iou']} < {thresholds['edge_iou']}")
    return failures


def print_report(rep: dict, failures: list[str]) -> None:
    m = rep["metrics"]
    print(f"reference:   {rep['reference']}")
    print(f"recreation:  {rep['recreation']}")
    if "ssim" in m:
        s = m["lab_shift"]
        print(f"ssim {m['ssim']}  psnr {m['psnr_db']} dB  dE2000 mean {m['delta_e_mean']} p95 {m['delta_e_p95']}  edge IoU {m['edge_iou']}")
        print(f"lab shift dL {s['dL']:+.2f} da {s['da']:+.2f} db {s['db']:+.2f}  chroma x{m['chroma_ratio']}  contrast x{m['contrast_ratio']}")
        for c in m["worst_cells"][:3]:
            print(f"worst cell {c['cell']} box {c['box_ref_px']} dE {c['delta_e_mean']} dL {c['dL']:+.2f}")
        for hnt in m["hints"]:
            print(f"hint: {hnt}")
    else:
        print(f"edge IoU {m['edge_iou']}")
    for n in rep["notes"]:
        print(f"note: {n}")
    print("result: " + ("FAIL - " + "; ".join(failures) if failures else "pass"))


def parse_crop(value):
    if value in (None, "", []):
        return None
    if isinstance(value, (list, tuple)):
        return rc.parse_bbox(",".join(str(v) for v in value), "crop")
    return rc.parse_bbox(str(value), "crop")


def cmd_pair(args) -> int:
    thresholds = {"ssim": args.fail_under_ssim, "delta_e_mean": args.fail_over_delta_e, "edge_iou": args.fail_under_edge_iou}
    rep = compare(args.reference, args.recreation, args.out, crop=parse_crop(args.crop), mask_path=args.mask,
                  grid=parse_grid(args.grid), edges_only=args.edges_only, metric_width=args.metric_width)
    failures = evaluate(rep["metrics"], thresholds)
    rep["thresholds"] = thresholds
    rep["failures"] = failures
    rc.write_json(args.out / "report.json", rep)
    if args.json:
        print(rc.dump_json(rep))
    else:
        print_report(rep, failures)
        print(f"wrote {args.out}/report.json, side_by_side.png, heatmap.png, edges.png, blink.gif")
    return rc.EXIT_FAIL if failures else rc.EXIT_OK


def cmd_batch(args) -> int:
    data = rc.read_json(args.shots)
    shots = data.get("shots") if isinstance(data, dict) else None
    if not isinstance(shots, list) or not shots:
        rc.fail(f"{args.shots} has no 'shots' list")
    root = args.root or Path.cwd()
    summary = []
    bad = 0
    for shot in shots:
        sid = shot.get("id") or "shot"
        ref = root / shot.get("reference", "")
        rec = root / shot.get("recreation", "")
        entry = {"id": sid, "reference": str(ref), "recreation": str(rec)}
        if not ref.is_file():
            entry["status"] = "missing-reference"
            bad += 1
        elif not rec.is_file():
            entry["status"] = "missing-capture"
            if not args.allow_missing:
                bad += 1
        else:
            mask = root / shot["mask"] if shot.get("mask") else None
            if mask is not None and not mask.is_file():
                rc.fail(f"{sid}: mask not found: {mask}")
            rep = compare(ref, rec, args.out / sid, crop=parse_crop(shot.get("crop")), mask_path=mask,
                          grid=parse_grid(shot.get("grid", "8x6")), metric_width=args.metric_width)
            fails = evaluate(rep["metrics"], shot.get("thresholds") or {})
            entry.update({"status": "fail" if fails else "pass", "failures": fails,
                          "metrics": {k: v for k, v in rep["metrics"].items() if k in ("ssim", "delta_e_mean", "edge_iou", "lab_shift")}})
            bad += 1 if fails else 0
        summary.append(entry)
        print(f"{sid}: {entry['status']}" + (" - " + "; ".join(entry.get("failures", [])) if entry.get("failures") else ""))
    rc.write_json(args.out / "summary.json", {"tool": TOOL, "schema": SCHEMA, "shots": summary})
    print(f"wrote {args.out}/summary.json ({len(summary)} shots, {bad} failing)")
    return rc.EXIT_FAIL if bad else rc.EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pair", help="compare one reference image with one recreation capture")
    p.add_argument("reference", type=Path)
    p.add_argument("recreation", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--crop", help="x,y,w,h in reference pixels (applied to both when they share a resolution)")
    p.add_argument("--mask", type=Path, help="PNG where white = ignore (HUD, particles, players)")
    p.add_argument("--grid", default="8x6", help="cells for worst-region analysis, COLSxROWS (default 8x6)")
    p.add_argument("--edges-only", action="store_true", help="only compare edge maps (silhouettes, poses, layout)")
    p.add_argument("--metric-width", type=int, default=1280, help="downscale wider images to this width for metrics (0 = never)")
    p.add_argument("--fail-under-ssim", type=float)
    p.add_argument("--fail-over-delta-e", type=float)
    p.add_argument("--fail-under-edge-iou", type=float)
    p.add_argument("--json", action="store_true")
    b = sub.add_parser("batch", help="compare every shot in a shots.json")
    b.add_argument("shots", type=Path)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--root", type=Path, help="base directory for the paths in shots.json (default: current directory)")
    b.add_argument("--allow-missing", action="store_true", help="do not fail for shots without a recreation capture")
    b.add_argument("--metric-width", type=int, default=1280)
    args = ap.parse_args()
    if args.cmd == "pair":
        for pth in (args.reference, args.recreation):
            if not pth.is_file():
                rc.fail(f"image not found: {pth}")
        return cmd_pair(args)
    return cmd_batch(args)


if __name__ == "__main__":
    rc.run_main(main)
