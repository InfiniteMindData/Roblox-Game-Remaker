# Walkthrough: recreating a HUD 1:1

Uses the demo screenshot `demo_hud.png` (1920×1080) and a deliberately imperfect
"recreation" capture `demo_hud_rec.png` (health bar shifted by 12, 5 px and the image 18%
darker). Generate both with `examples/demo/make_demo_footage.py`.

## 1. Measure boxes

Record the element boxes in reference pixels (`hud_boxes.json`):

```json
{"reference_resolution": [1920, 1080], "scale_rule": "height",
 "elements": [
  {"name": "HealthBar", "bbox": [48, 980, 420, 36], "anchor": "bottom-left"},
  {"name": "AmmoPanel", "bbox": [1700, 960, 172, 72]},
  {"name": "Crosshair", "bbox": [944, 524, 32, 32]}]}
```

The scale rule (`height`) was established from a second screenshot at 21:9: the elements kept
their pixel size relative to screen height and stayed pinned to their corners.

## 2. Convert to Roblox layout

```bash
python scripts/ui_measure.py hud_boxes.json
```

```text
HealthBar   bottom-left   AnchorPoint (0.0, 1.0)  Position UDim2.new(0.0, 48.0, 1.0, -64.0)   Size UDim2.fromOffset(420.0, 36.0)
AmmoPanel   bottom-right  AnchorPoint (1.0, 1.0)  Position UDim2.new(1.0, -48.0, 1.0, -48.0)  Size UDim2.fromOffset(172.0, 72.0)
Crosshair   center        AnchorPoint (0.5, 0.5)  Position UDim2.new(0.5, 0.0, 0.5, 0.0)      Size UDim2.fromOffset(32.0, 32.0)
```

`--luau` prints a `UILayout` module with these values and a `build(parent)` helper.

## 3. Colors

```bash
python scripts/palette_extract.py demo_hud.png --region 52,984,300,28 --k 1
# 100.0%  #C82832  Color3.fromRGB(200, 40, 50)
```

## 4. Build in Studio

- Create `StarterGui/HUD` (a ScreenGui), set the attribute `RemakeScaleUI = true`, and set
  `Config.UI.ReferenceResolution = Vector2.new(1920, 1080)` and `ScaleRule = "height"`.
  `Main.client.luau` attaches `UIScaler` automatically.
- Create the frames with the generated `AnchorPoint`, `Position` and `Size`, and give the bar
  fill `Color3.fromRGB(200, 40, 50)`.
- Fonts: identify the original. If it is not licensed for use, pick the closest Roblox font and
  record the substitution in the `UI-###` entry.

## 5. Compare

Capture the Roblox HUD at 1920×1080 (Device Simulator custom device, or MCP `screen_capture`),
then compare it:

```bash
python scripts/visual_compare.py pair demo_hud.png demo_hud_rec.png --out diff_hud
```

```text
ssim 0.9708  psnr 24.479 dB  dE2000 mean 5.447 p95 6.816  edge IoU 0.732
lab shift dL -6.32 da +1.03 db +1.29  chroma x0.8532  contrast x0.8547
worst cell [0, 5] box [0, 900, 240, 180] dE 9.612 dL -7.32
hint: Recreation is darker (dL -6.3): raise Lighting.ExposureCompensation in ~0.25 steps, or Brightness.
```

The worst cell is the bottom-left corner, where the health bar sits. For UI, a dark overall
shift usually means the capture was taken with different lighting or post-processing behind the
UI, or with an overlay. Fix the cause, then compare the layout numerically:

```bash
python scripts/ui_measure.py --compare hud_boxes.json hud_boxes_rec.json --tolerance 0.5
```

```text
FAIL HealthBar                dx +0.62% dy +0.46% dw +0.00% dh +0.00%
ok   AmmoPanel                dx +0.00% dy +0.00% dw +0.00% dh +0.00%
worst error 0.62% of screen (tolerance 0.5%) -> FAIL
```

The health bar is 12 px right and 5 px down. The demo shifts it on purpose; in a real project
the usual causes are `ScreenInsets` (Roblox's core UI safe area) or a wrong `AnchorPoint`. Fix the
layout, re-capture, and record the iteration.

## 6. Check every state and aspect ratio

Repeat for hover, pressed, empty and full states, and at a second aspect ratio. The UI entry is
done only when every state passes.
