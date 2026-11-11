# UI recreation

Read this for `UI` entries. UI is the easiest place to reach measurable 1:1, because
screenshots give exact pixel boxes. The work is in reproducing the original's **scaling rule**
and **states**, not only one static frame.

## 1. Capture the reference

- Screenshots at native resolution of every screen and state: default, hover or focus,
  pressed, disabled, empty, full, error, and each tab.
- The same screens at a **second aspect ratio** (for example 16:9 and 21:9, or 16:9 and 4:3).
  Elements that keep their distance to an edge are anchored to that edge; elements that grow
  are scale-sized. This is the only reliable way to recover the anchoring rule.
- The open and close transitions as frames (`extract_frames.py --mode range`) to time the tweens.

## 2. Measure boxes

Write a boxes file in reference pixels, either by reading coordinates from an image editor or,
when you can view images, by estimating and then verifying with crops:

```json
{
  "reference_resolution": [1920, 1080],
  "scale_rule": "height",
  "elements": [
    {"name": "HealthBar", "bbox": [48, 980, 420, 36], "anchor": "bottom-left", "evidence": "EV-021"},
    {"name": "AmmoCounter", "bbox": [1700, 960, 172, 72], "anchor": "bottom-right"},
    {"name": "Crosshair", "bbox": [944, 524, 32, 32], "anchor": "center"}
  ]
}
```

`scale_rule` describes how the original scales its UI with screen size:

- `height`: UI scales with screen height (the most common in games);
- `width`: UI scales with screen width;
- `fit`: scales by the smaller ratio, so the full layout always fits;
- `none`: fixed pixel size.

Convert the boxes:

```bash
python scripts/ui_measure.py remake/ui/hud-boxes.json --luau > remake/ui/hud-layout.luau
python scripts/ui_measure.py remake/ui/hud-boxes.json --json > remake/ui/hud-layout.json
```

For each element the output gives `AnchorPoint`, a `Position` that is scale for the anchor plus
offset pixels, a `Size` in offset pixels at the reference resolution, the aspect ratio, and an
equivalent pure-scale `Size` if you prefer to avoid `UIScale`.

## 3. Build it on Roblox

**Recommended for 1:1:** offset pixels at the reference resolution, plus `UIScale`:

1. One `ScreenGui` per layer (HUD, menus, popups, overlays), with `ResetOnSpawn` set
   deliberately and `ZIndexBehavior = Sibling`.
2. Elements use the generated `AnchorPoint` and `Position` (`UDim2.new(anchorX, offX, anchorY, offY)`)
   and offset `Size` values copied from the reference pixels.
3. `UIScaler.attach(screenGui, { reference = Vector2.new(1920, 1080), rule = "height" })` from the
   template adds a `UIScale` and keeps it in sync with `Camera.ViewportSize`. Use
   `integer = true` for pixel art.

This reproduces the original exactly at the reference resolution and scales the same way the
original does elsewhere.

### Safe areas and Roblox core UI

- `ScreenGui.ScreenInsets` defaults to `CoreUISafeInsets`, which keeps content clear of the Roblox
  top bar and menu. If the original places HUD elements in the top-left or top-right, they will
  shift. Options: keep the insets and accept the offset (record it in the breakdown), or set
  `ScreenInsets` to `DeviceSafeInsets` and move only the conflicting element. Never cover Roblox's
  menu button.
- `GuiService.TopbarInset` and `GuiService:GetGuiInset()` give the exact reserved area for
  calculations.
- Test notched phones in the Device Simulator; `ScreenGui.ClipToDeviceSafeArea` controls clipping.

### Visual primitives

| Original element | Roblox |
|---|---|
| Panels with rounded corners | `Frame` + `UICorner` (measure the radius in pixels) |
| Borders and outlines | `UIStroke` (`Thickness`, `ApplyStrokeMode` Border or Contextual) |
| Gradients | `UIGradient` (`Color` and `Transparency` sequences, `Rotation`) |
| Scalable bordered art | `ImageLabel` with `ScaleType = Slice`, `SliceCenter`, `SliceScale` (9-slice) |
| Sprite-sheet icons | `ImageRectOffset` and `ImageRectSize` on one uploaded sheet |
| Pixel art | `ResampleMode = Pixelated` with integer scaling |
| Bars (health, stamina) | A clipped frame (`ClipsDescendants`) with a scaled fill, or `UIGradient` transparency |
| 3D model in UI | `ViewportFrame` with its own camera |
| World-space UI | `BillboardGui` or `SurfaceGui` (VR menus in particular) |
| Lists and grids | `UIListLayout`, `UIGridLayout`, `UIFlexItem`, `UIPadding` |

### Text and fonts

- Identify the font family. If it is a licensed commercial font you do not have rights to, pick
  the closest available Roblox font by x-height, width and stroke contrast, and record the
  substitution in the `UI` entry.
- Set `FontFace` (`Font.new(familyAsset, weight, style)`), the measured text size in pixels at the
  reference resolution, `LineHeight`, and strokes or shadows (`UIStroke` on text, or a duplicated
  offset label for drop shadows).
- Avoid `TextScaled` when matching exact sizes. Use fixed `TextSize` under `UIScale`.
- Reference boxes are tight around the glyphs, but `TextSize` sets the line, not the capitals.
  Place text with two per-font ratios, cap height and the gap from the label's top to the capitals,
  both as fractions of `TextSize`, and calibrate them from one capture (§6). Measured in Studio:
  Oswald 0.575 and 0.235, Garamond 0.543 and 0.222. A guessed ratio (0.70 for Oswald) left the
  capitals 18% short.
- Run all user-generated text through filtering (TextService); hand this to the `roblox-ui` and
  `roblox-networking` skills when relevant.

## 4. Animate UI to the measured timing

- For each state change, record the duration in frames and the property curves (position,
  scale, transparency, rotation) from the extracted frames.
- Fit the curve instead of judging it by eye: track the element (`motion_track.py` on its edge,
  or `--field scale` for a pop-in), then
  `python scripts/fit_curve.py --track remake/tracks/menu-open.json --field x_px --luau`. It ranks
  every template `Easing` curve, a spring and an exponential approach, gives the duration with an
  uncertainty, and says when the top fits cannot be told apart at the footage's frame rate (record
  the alternatives then, and pick by intent).
- When the best fit is an `EasingStyle`/`EasingDirection`, use
  `TweenInfo.new(duration, style, direction)`. The fitter uses the template's textbook formulas;
  where exact `TweenService` equivalence matters, compare a few values with
  `TweenService:GetValue()` in Studio. When no curve fits (rms residual above about 5% of the
  change), the motion may be keyframed or several tweens: fit narrower windows, or use
  `Easing.cubicBezier` with a `RenderStepped` driver.
- Stagger: measure the per-item delay in list animations.
- Sounds: align UI sounds to the first frame of the visual change (`audio_onsets.py`).

## 5. Navigation and devices

- Gamepad: set `NextSelection*` where automatic selection differs from the original's focus order,
  `GuiService.SelectedObject` for initial focus, and selection images matching the original's
  focus style.
- Touch: enlarge hit areas (invisible parent buttons) without changing visuals when the original
  is a console or PC game.
- VR: the default ScreenGui renders on a panel in VR. For diegetic or world UI, use `SurfaceGui`
  on parts placed at the measured position relative to the head or hands (see `vr-quest.md`).

## 6. Verify

Layout first, measured the same way as the reference, at whatever size the Studio viewport has:

1. `python scripts/studio_snippets.py ui-rects remake/ui/ref-boxes.json --gui MainMenu --out ui-rects.luau`,
   then run it with `execute_luau` (Client, during play) and save the returned JSON as
   `remake/ui/rects-NN.json`. It lists the screen rectangle of every GUI object named in the
   reference boxes (an element's `"gui"` field maps a reference name to a different Instance
   name), with the top-bar inset added back, each element's anchor, and where its text is drawn.
2. `screen_capture` straight away, without changing the UI, and save it as `remake/captures/ui-NN.png`.
3. `python scripts/ui_measure.py --from-capture remake/captures/ui-NN.png remake/ui/rects-NN.json --ref remake/ui/ref-boxes.json --out remake/ui/rec-NN.json`.
   Text gets tight ink boxes; panels keep their drawn rectangles; both are mapped to the
   reference frame by the scale rule and each element's anchor, so the capture's aspect does not
   need to match. Over a busy background (text on the 3D scene), raise `--ink-threshold`.
4. `python scripts/ui_measure.py --compare remake/ui/ref-boxes.json remake/ui/rec-NN.json --out remake/diff/ui-NN.json`.
   When the words differ by design (an homage with original names, a translation), add
   `"ignore": ["w"]` to those elements in the reference boxes: width cannot match, while x, y and
   cap height still can.
5. `python scripts/fidelity_report.py remake --diff-log --label "..."` scores the saved layout
   report (`ui:<reference file>`, r = worst error / tolerance) with the shots, metrics and clips.
6. Colors and grading: `visual_compare.py pair` on a capture at the reference aspect ratio (see
   `studio-mcp.md`: captures are viewport-sized JPEGs).
7. Check every state and transition, not only the default frame: log state changes from the UI
   code and drive it with `user_keyboard_input`.
