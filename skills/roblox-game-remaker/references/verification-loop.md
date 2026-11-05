# Verification loop

Read this in Phase 6, and after every system lands. Fidelity is a measured result: each
claim of "matches the original" points to a comparison artifact.

## 1. What to compare

| Aspect | Reference | Recreation | Tool | Metric |
|---|---|---|---|---|
| Movement, jumps, camera motion | `measurements.json` targets | Harness log | `measure_compare.py` | abs/% error vs tolerance |
| Shot look (environment, lighting) | Matched reference frame | `ShotCamera` capture | `visual_compare.py pair` | SSIM, ΔE2000, Lab shift, edge IoU |
| UI layout | Reference screenshot boxes | Capture boxes | `ui_measure.py --compare`, `visual_compare.py --grid` | % of screen error per element |
| Animation | Keypose frames | Frozen-pose captures | `contact_sheet.py` side by side, `visual_compare.py --edges-only` | Frame error, silhouette IoU |
| Timing (UI, abilities, VFX) | Frame ranges | Harness or markers | `remake_calc.py frames` | ± frames |
| Audio sync | `audio_onsets.py` on reference | Same on a recording of the recreation | Diff of onset times | ms |

## 2. Shot list (`remake/shots.json`)

```json
{
  "reference_resolution": [1920, 1080],
  "shots": [
    {
      "id": "SHOT-03",
      "evidence": "EV-007",
      "reference": "remake/frames/ref/f001820_t30.333333.png",
      "recreation": "remake/captures/SHOT-03.png",
      "camera": {"position": [12, 9, -30], "look_at": [0, 4, 0], "fov": 58.7},
      "clock_time": 14.5,
      "crop": null,
      "mask": "remake/masks/SHOT-03-hud.png",
      "thresholds": {"ssim": 0.80, "delta_e_mean": 6.0, "edge_iou": 0.55},
      "notes": "Level 1 courtyard, HUD masked out"
    }
  ]
}
```

- Establish camera numbers for each shot by matching the reference: place the camera, compare,
  and adjust until landmarks align (`visual_compare` edge IoU rises as alignment improves).
- `mask` is a black-and-white PNG where white marks pixels to **ignore** (HUD, particles, other
  players).
- Batch run: `python scripts/visual_compare.py batch remake/shots.json --out remake/diff/` writes
  a report per shot plus `summary.json`, and exits with status 1 if any shot fails its
  thresholds.

## 3. Reading `visual_compare` reports

- `ssim` (0–1): structural similarity of luminance. It falls sharply with misalignment, so fix
  the camera first.
- `delta_e_mean` and `delta_e_p95` (CIEDE2000): perceptual color difference. Under about 2 is
  barely visible; over 10 is a clearly different color.
- `lab_shift`: average `dL` (lightness), `da` (green to red), `db` (blue to yellow) of the
  recreation minus the reference. These are actionable for lighting.
- `chroma_ratio` and `contrast_ratio`: recreation over reference for saturation and lightness
  spread.
- `edge_iou`: overlap of edge maps; insensitive to color, good for silhouette and layout.
- `worst_cells`: the grid cells with the largest ΔE, so you know where to look.
- `hints`: heuristic suggestions (for example "raise ExposureCompensation"). Confirm them by
  re-measuring.
- `side_by_side.png`, `heatmap.png` and `blink.gif`: open these when you can view images. The blink
  GIF alternates reference and recreation, which makes misalignment obvious.
- For alignment work, `overlay.py` gives single images that are quicker to read: `blend` (ghosting
  shows offsets), `checker` (edges that break across tiles are misaligned), `wipe` (a split line),
  and `diff` (amplified difference).

## 4. Iteration discipline (`remake/diff-log.md`)

Per iteration, record:

```markdown
## Iteration 7 — 2026-11-04 — SHOT-03, MOVE-002
- change: ExposureCompensation 0.0 -> 0.35; Atmosphere.Density 0.30 -> 0.36
- before: ssim 0.71, dE 8.9 (dL -6.1, db +2.0); jump apex 7.9 (target 7.4 ± 0.3)
- after:  ssim 0.78, dE 5.2 (dL -1.2, db +1.8); jump apex 7.5
- status: SHOT-03 pass (Tier A), MOVE-002 pass
- evidence: remake/diff/shot03/it7/report.json, remake/logs/run-07.log
```

Rules:

- Change one subsystem per iteration, so the cause of each improvement is clear.
- Fix the largest measured gap first, and alignment before color, and color before detail.
- Never relax a threshold to make a check pass. Change the threshold only with the user's
  agreement, and record why.
- If a gap is an engine limit (for example no motion blur, or the light range cap), mark it
  `limit` and move on.

## 5. Gameplay and technical verification

The Roblox verification ladder. Use the levels the change needs, and never report a lower
level as a higher one.

1. **Static:** `stylua --check`, `selene`, `rojo build` succeed; Lune unit tests pass.
2. **Single session:** Studio Test or Play, no new Output errors, happy path works.
3. **Lifecycle:** respawn, reset, rejoin, character replacement.
4. **Server & Clients:** two or more clients for anything replicated or networked.
5. **Devices:** Device Simulator profiles, Controller Emulator, touch, a real Quest 3 for VR.
6. **Stress:** spam inputs, rapid state changes, many entities, low-end performance.

Performance checks: MicroProfiler (Ctrl+Alt+F6) frame times, the Script Profiler for hot
scripts, and Developer Console memory. Record results against device budgets.

## 6. Evidence labels in reports

| Label | Meaning |
|---|---|
| **Executed** | Ran in Studio or on a device, with Output, a capture or a log saved |
| **Executed by user** | The user ran it and supplied the output |
| **Statically checked** | Lint, format, build or unit tests only |
| **Prepared, not run** | A harness or steps exist, but nobody has run them |
| **Unverified** | No adequate check was possible |

## 7. Acceptance

A breakdown entry is **done** when its `accept:` test passes at the agreed tier with saved
evidence, or when the user accepts a documented gap. The delivery report lists every entry with
status: pass, gap (with the measured delta), limit, or not started.
