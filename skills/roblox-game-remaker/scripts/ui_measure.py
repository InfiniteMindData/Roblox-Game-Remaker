#!/usr/bin/env python3
"""Convert UI element pixel boxes from a reference screenshot into Roblox layout values.

Input JSON:
  {
    "reference_resolution": [1920, 1080],
    "scale_rule": "height",            # height | width | fit | none (how the original scales UI)
    "elements": [
      {"name": "HealthBar", "bbox": [48, 980, 420, 36], "anchor": "bottom-left"},
      {"name": "Crosshair", "bbox": [944, 524, 32, 32]}          # anchor auto-detected
    ]
  }

Anchors: top-left, top, top-right, left, center, right, bottom-left, bottom, bottom-right, auto.

For each element it outputs:
  offset strategy (recommended for 1:1): AnchorPoint, Position = UDim2.new(ax, offX, ay, offY),
    Size = UDim2.fromOffset(w, h), with a UIScale on the ScreenGui driven by the scale rule
  scale strategy: Position and Size in Scale, plus SizeConstraint/aspect ratio to mimic the rule

Modes:
  ui_measure.py boxes.json                 text table
  ui_measure.py boxes.json --json          machine-readable layout
  ui_measure.py boxes.json --luau          a Luau builder function for a ScreenGui
  ui_measure.py --compare ref.json rec.json [--tolerance 1.0] [--out remake/diff/ui-it3.json]
      per-element position and size error as % of the screen; exit 1 if any exceeds tolerance.
      An element may list dimensions to leave out, in either file: "ignore": ["w"] for a label whose
      words differ on purpose (an homage, a translation), "ignore": ["w", "h"] for a free-size panel.
      --out saves the JSON report where fidelity_report.py scores it (any path under remake/diff/).
  ui_measure.py --from-capture capture.png rects.json --ref ref.json --out rec.json
      measure a recreation capture the way the reference was measured, and write a boxes JSON for
      --compare. rects.json comes from `studio_snippets.py ui-rects` run in the playtest client:
      screen rectangles of the GUI objects named in ref.json (with the top-bar inset added), and
      where each label's text is drawn. Text elements get tight ink boxes (pixels that differ from
      the label's background by more than --ink-threshold); other elements keep their drawn
      rectangle. Boxes are mapped to the reference frame with the reference's scale rule and each
      element's anchor, so a capture of any size or aspect compares correctly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "ui_measure"
ANCHORS = {
    "top-left": (0.0, 0.0), "top": (0.5, 0.0), "top-right": (1.0, 0.0),
    "left": (0.0, 0.5), "center": (0.5, 0.5), "right": (1.0, 0.5),
    "bottom-left": (0.0, 1.0), "bottom": (0.5, 1.0), "bottom-right": (1.0, 1.0),
}
RULES = ("height", "width", "fit", "none")


def auto_anchor(x, y, w, h, W, H) -> str:
    cx, cy = (x + w / 2) / W, (y + h / 2) / H
    col = "left" if cx < 1 / 3 else ("right" if cx > 2 / 3 else "")
    row = "top" if cy < 1 / 3 else ("bottom" if cy > 2 / 3 else "")
    if row and col:
        return f"{row}-{col}"
    return row or col or "center"


def load_boxes(path: Path) -> tuple[int, int, str, list[dict]]:
    data = rc.read_json(path)
    try:
        W, H = (int(v) for v in data["reference_resolution"])
    except (KeyError, TypeError, ValueError):
        rc.fail(f"{path}: 'reference_resolution' must be [width, height]")
    rule = data.get("scale_rule", "height")
    if rule not in RULES:
        rc.fail(f"{path}: scale_rule must be one of {', '.join(RULES)}")
    elements = data.get("elements")
    if not isinstance(elements, list) or not elements:
        rc.fail(f"{path}: 'elements' must be a non-empty list")
    names = set()
    for el in elements:
        if "name" not in el or "bbox" not in el:
            rc.fail(f"{path}: every element needs 'name' and 'bbox'")
        if el["name"] in names:
            rc.fail(f"{path}: duplicate element name {el['name']!r}")
        names.add(el["name"])
        if len(el["bbox"]) != 4 or el["bbox"][2] <= 0 or el["bbox"][3] <= 0:
            rc.fail(f"{path}: {el['name']} bbox must be [x, y, w, h] with positive size")
    return W, H, rule, elements


def layout(W, H, rule, elements) -> list[dict]:
    out = []
    for el in elements:
        x, y, w, h = (float(v) for v in el["bbox"])
        anchor = el.get("anchor", "auto")
        if anchor == "auto":
            anchor = auto_anchor(x, y, w, h, W, H)
        if anchor not in ANCHORS:
            rc.fail(f"{el['name']}: unknown anchor {anchor!r}")
        ax, ay = ANCHORS[anchor]
        px, py = x + ax * w, y + ay * h
        off_x, off_y = px - ax * W, py - ay * H
        entry = {
            "name": el["name"],
            "anchor": anchor,
            "AnchorPoint": [ax, ay],
            "offset_strategy": {
                "Position": {"XScale": ax, "XOffset": round(off_x, 2), "YScale": ay, "YOffset": round(off_y, 2)},
                "Size": {"XOffset": round(w, 2), "YOffset": round(h, 2)},
            },
            "aspect_ratio": round(w / h, 5),
            "screen_fraction": {"x": round(x / W, 5), "y": round(y / H, 5), "w": round(w / W, 5), "h": round(h / H, 5)},
        }
        pos_scale = {"XScale": round(px / W, 5), "YScale": round(py / H, 5)}
        if rule == "height":
            size = {"XScale": round(w / H, 5), "YScale": round(h / H, 5), "SizeConstraint": "RelativeYY"}
        elif rule == "width":
            size = {"XScale": round(w / W, 5), "YScale": round(h / W, 5), "SizeConstraint": "RelativeXX"}
        else:
            size = {"XScale": round(w / W, 5), "YScale": round(h / H, 5), "SizeConstraint": "RelativeXY",
                    "UIAspectRatioConstraint": round(w / h, 5)}
        entry["scale_strategy"] = {"Position": pos_scale, "Size": size}
        if el.get("evidence"):
            entry["evidence"] = el["evidence"]
        out.append(entry)
    return out


def to_luau(W, H, rule, items) -> str:
    lines = [
        "--!strict",
        f"-- Generated by ui_measure.py from a {W}x{H} reference (scale rule: {rule}).",
        "-- Offset strategy: exact pixels at the reference resolution; UIScaler scales the ScreenGui.",
        "local UILayout = {}",
        "",
        f"UILayout.ReferenceResolution = Vector2.new({W}, {H})",
        f'UILayout.ScaleRule = "{rule}"',
        "",
        "UILayout.Elements = {",
    ]
    for it in items:
        o = it["offset_strategy"]
        p, s = o["Position"], o["Size"]
        ev = f" -- {it['evidence']}" if it.get("evidence") else ""
        lines.append(
            f'\t{it["name"]} = {{ AnchorPoint = Vector2.new({it["AnchorPoint"][0]}, {it["AnchorPoint"][1]}), '
            f'Position = UDim2.new({p["XScale"]}, {p["XOffset"]}, {p["YScale"]}, {p["YOffset"]}), '
            f'Size = UDim2.fromOffset({s["XOffset"]}, {s["YOffset"]}) }},{ev}'
        )
    lines += [
        "}",
        "",
        "-- Creates placeholder Frames for each element (replace with real widgets, keep the layout values).",
        "function UILayout.build(parent: Instance): { [string]: Frame }",
        "\tlocal created = {}",
        "\tfor name, spec in UILayout.Elements do",
        '\t\tlocal frame = Instance.new("Frame")',
        "\t\tframe.Name = name",
        "\t\tframe.AnchorPoint = spec.AnchorPoint",
        "\t\tframe.Position = spec.Position",
        "\t\tframe.Size = spec.Size",
        "\t\tframe.BackgroundTransparency = 0.5",
        "\t\tframe.Parent = parent",
        "\t\tcreated[name] = frame",
        "\tend",
        "\treturn created",
        "end",
        "",
        "return UILayout",
    ]
    return "\n".join(lines)


DIMS = {"x": "dx_pct", "y": "dy_pct", "w": "dw_pct", "h": "dh_pct"}


def ignored(*elements: dict) -> set[str]:
    out: set[str] = set()
    for el in elements:
        for d in el.get("ignore") or []:
            if d not in DIMS:
                rc.fail(f"{el.get('name')}: 'ignore' may list x, y, w, h (got {d!r})")
            out.add(d)
    return out


def compare(ref_path: Path, rec_path: Path, tolerance: float, as_json: bool, out: Path | None = None) -> int:
    W, H, _, ref = load_boxes(ref_path)
    W2, H2, _, rec = load_boxes(rec_path)
    rec_by = {e["name"]: e for e in rec}
    rows, worst, missing = [], 0.0, []
    for e in ref:
        other = rec_by.get(e["name"])
        if not other:
            missing.append(e["name"])
            continue
        x, y, w, h = e["bbox"]
        sx, sy = W / W2, H / H2  # normalize the recreation to reference pixels
        x2, y2, w2, h2 = other["bbox"][0] * sx, other["bbox"][1] * sy, other["bbox"][2] * sx, other["bbox"][3] * sy
        err = {
            "dx_pct": round(100 * (x2 - x) / W, 3), "dy_pct": round(100 * (y2 - y) / H, 3),
            "dw_pct": round(100 * (w2 - w) / W, 3), "dh_pct": round(100 * (h2 - h) / H, 3),
        }
        skip = ignored(e, other)
        judged = [abs(v) for d, v in ((d, err[DIMS[d]]) for d in DIMS) if d not in skip]
        m = max(judged) if judged else 0.0
        worst = max(worst, m)
        rows.append({"name": e["name"], **err, "ignored": sorted(skip), "max_pct": round(m, 3), "pass": m <= tolerance})
    result = {"tool": TOOL, "mode": "compare", "reference": str(ref_path), "recreation": str(rec_path),
              "tolerance_pct": tolerance, "elements": rows, "missing": missing,
              "worst_pct": round(worst, 3), "pass": worst <= tolerance and not missing}
    if out:
        rc.write_json(out, result)
    if as_json:
        print(rc.dump_json(result))
    else:
        for r in rows:
            def cell(d: str) -> str:
                v = r[DIMS[d]]
                return f"d{d} {'  (ign)' if d in r['ignored'] else f'{v:+.2f}%'}"
            print(f"{'ok  ' if r['pass'] else 'FAIL'} {r['name']:<24} " + " ".join(cell(d) for d in DIMS))
        for name in missing:
            print(f"MISSING {name} (not in the recreation boxes)")
        print(f"worst error {worst:.2f}% of screen (tolerance {tolerance}%) -> {'pass' if result['pass'] else 'FAIL'}")
        if out:
            print(f"wrote {out}")
    return rc.EXIT_OK if result["pass"] else rc.EXIT_FAIL


def screen_scale(rule: str, W: int, H: int, cw: int, ch: int) -> float:
    """UI scale factor of a cw x ch capture relative to the W x H reference, under the scale rule."""
    if rule == "height":
        return ch / H
    if rule == "width":
        return cw / W
    if rule == "fit":
        return min(cw / W, ch / H)
    return 1.0


def ink_box(img, rect: tuple[float, float, float, float], threshold: float):
    """Tight box of the pixels in rect that differ from the label's background.

    The background is sampled from the top rows of the drawn line box: a line's ascent space sits
    above the capitals, so those rows hold no glyphs. (The median of the whole box fails when a
    neighbor, such as a sub-menu strip, fills a large part of it.)
    """
    np = rc.require_numpy()
    h_img, w_img = img.shape[:2]
    x, y, w, h = rect
    xa, ya = max(0, int(round(x))), max(0, int(round(y)))
    xb, yb = min(w_img, int(x + w) + 1), min(h_img, int(y + h) + 1)
    if xb - xa < 2 or yb - ya < 2:
        return None
    block = img[ya:yb, xa:xb]
    top = block[: max(1, min(2, (yb - ya) // 4))].reshape(-1, 3)
    bg = np.median(top, axis=0)
    crop = block.reshape(-1, 3)
    ink = (np.linalg.norm(crop - bg, axis=1) > threshold).reshape(yb - ya, xb - xa)
    rows, cols = ink.sum(axis=1), ink.sum(axis=0)
    # text never fills a whole row or column: a solid band is a neighbor (a strip, a frame edge)
    ink[rows > 0.9 * (xb - xa), :] = False
    ink[:, cols > 0.9 * (yb - ya)] = False
    keep_r = np.nonzero(ink.sum(axis=1) >= 2)[0]
    keep_c = np.nonzero(ink.sum(axis=0) >= 2)[0]
    if len(keep_r) == 0 or len(keep_c) == 0:
        return None
    return (float(xa + keep_c.min()), float(ya + keep_r.min()),
            float(keep_c.max() - keep_c.min() + 1), float(keep_r.max() - keep_r.min() + 1))


def from_capture(capture: Path, rects_path: Path, ref_path: Path, out: Path, threshold: float) -> int:
    Image = rc.require_pil()
    np = rc.require_numpy()
    W, H, rule, ref = load_boxes(ref_path)
    data = rc.read_json(rects_path)
    items = data.get("elements") if isinstance(data, dict) else None
    if not isinstance(items, list):
        rc.fail(f"{rects_path}: expected the JSON printed by studio_snippets.py ui-rects")
    with Image.open(capture) as im:
        img = np.asarray(im.convert("RGB")).astype(float)
    ch, cw = img.shape[:2]
    vp = data.get("viewport")
    notes = []
    if vp and (abs(vp[0] - cw) > 1 or abs(vp[1] - ch) > 1):
        notes.append(f"capture is {cw}x{ch} but the viewport was {vp[0]}x{vp[1]}: rectangles rescaled")
        kx, ky = cw / vp[0], ch / vp[1]
    else:
        kx = ky = 1.0
    s = screen_scale(rule, W, H, cw, ch)
    by_gui = {r.get("name"): r for r in items}
    elements, missing = [], []
    for e in ref:
        r = by_gui.get(e.get("gui", e["name"]))
        if not r:
            missing.append(e["name"])
            continue
        ax, ay = r.get("anchor", [0, 0])
        rect = (r["x"] * kx, r["y"] * ky, r["w"] * kx, r["h"] * ky)
        method = "drawn rectangle"
        if r.get("kind") == "text" and r.get("text"):
            t_ = r["text"]
            box = ink_box(img, (t_["x"] * kx, t_["y"] * ky, t_["w"] * kx, t_["h"] * ky), threshold)
            if box:
                rect, method = box, "ink pixels in the drawn text"
            else:
                notes.append(f"{e['name']}: no ink found in its text rectangle; using the drawn rectangle")
        x, y, w, h = rect
        bbox = [round(ax * W + (x - ax * cw) / s, 1), round(ay * H + (y - ay * ch) / s, 1), round(w / s, 1), round(h / s, 1)]
        el = {"name": e["name"], "bbox": bbox, "method": method}
        if e.get("ignore"):
            el["ignore"] = e["ignore"]
        elements.append(el)
    if not elements:
        rc.fail("none of the reference elements were found in the rects JSON (match names, or set 'gui' in ref.json)")
    rc.write_json(out, {"tool": TOOL, "mode": "from-capture", "reference_resolution": [W, H], "scale_rule": rule,
                        "capture": str(capture), "capture_size": [cw, ch], "scale": round(s, 6),
                        "elements": elements, "missing": missing, "notes": notes})
    for el in elements:
        print(f"{el['name']:<24} {el['bbox']}  ({el['method']})")
    for name in missing:
        print(f"MISSING {name} (no GUI object with this name in {rects_path})")
    for n in notes:
        print(f"note: {n}")
    print(f"wrote {out} ({len(elements)} elements, scale {s:.4f} from the '{rule}' rule)")
    return rc.EXIT_OK if not missing else rc.EXIT_FAIL


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("boxes", type=Path, nargs="?", help="boxes JSON")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--luau", action="store_true")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("REF", "REC"))
    ap.add_argument("--tolerance", type=float, default=1.0, help="compare tolerance in %% of screen (default 1.0)")
    ap.add_argument("--from-capture", nargs=2, type=Path, metavar=("CAPTURE", "RECTS"),
                    help="measure a recreation capture with the rects JSON from studio_snippets.py ui-rects")
    ap.add_argument("--ref", type=Path, help="with --from-capture: the reference boxes JSON (names, scale rule)")
    ap.add_argument("--out", type=Path, help="--from-capture: boxes JSON to write; --compare: save the report")
    ap.add_argument("--ink-threshold", type=float, default=60.0,
                    help="--from-capture: color distance from the label background that counts as text (default 60)")
    args = ap.parse_args()
    if args.from_capture:
        if not (args.ref and args.out):
            rc.fail("--from-capture needs --ref REF.json and --out REC.json")
        for pth in args.from_capture:
            if not pth.is_file():
                rc.fail(f"not found: {pth}")
        return from_capture(args.from_capture[0], args.from_capture[1], args.ref, args.out, args.ink_threshold)
    if args.compare:
        return compare(args.compare[0], args.compare[1], args.tolerance, args.json, args.out)
    if not args.boxes:
        rc.fail("give a boxes JSON file, or --compare REF REC")
    W, H, rule, elements = load_boxes(args.boxes)
    items = layout(W, H, rule, elements)
    if args.luau:
        print(to_luau(W, H, rule, items))
    elif args.json:
        print(rc.dump_json({"tool": TOOL, "reference_resolution": [W, H], "scale_rule": rule, "elements": items}))
    else:
        print(f"reference {W}x{H}, scale rule {rule}; add UIScaler.attach(screenGui, {{reference = Vector2.new({W}, {H}), rule = \"{rule}\"}})")
        for it in items:
            p = it["offset_strategy"]["Position"]
            s = it["offset_strategy"]["Size"]
            print(f"{it['name']:<24} {it['anchor']:<13} AnchorPoint ({it['AnchorPoint'][0]}, {it['AnchorPoint'][1]})  "
                  f"Position UDim2.new({p['XScale']}, {p['XOffset']}, {p['YScale']}, {p['YOffset']})  "
                  f"Size UDim2.fromOffset({s['XOffset']}, {s['YOffset']})")
    return 0


if __name__ == "__main__":
    rc.run_main(main)
