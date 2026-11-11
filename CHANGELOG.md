# Changelog

## 1.2.0 — unreleased

Measurement beyond side-on 2D footage.

- `camera_solve.py`: vertical FOV, pitch, roll and camera height from vanishing lines or a known
  object, and a ground-plane homography that converts third-person `motion_track` output to
  studs. Every result carries a ±1 px sensitivity uncertainty.
- `motion_track.py --scale-search`: follows subjects that move toward or away from the camera,
  and warns when one `--px-per-unit` cannot describe the clip. A lost match is no longer
  extrapolated off-screen (it used to crash with "search window is smaller than the template").
- `clip_compare.py`: aligns a recording of the build (a track or a harness log) with the reference
  clip on the first motion or a given frame, resamples both, and reports position rms and maximum
  error, bias, the frame-quantization floor and event offsets, with a position-versus-time plot.
  `targets.json` gains a `clips` block, written from the tier by `ledger.py targets`.
- `fit_curve.py`: fits all 31 curves of the template's `Easing.luau`, a critically or
  under-damped spring (as `Spring.luau` steps it) and an exponential approach to tracked samples,
  ranks them, gives duration or spring parameters with bootstrap uncertainties and `--luau`
  output, and says when the top fits cannot be distinguished at the footage's frame rate (with the
  frame rate that would separate them).
- `remake_common.line_plot`: Pillow line charts shared by the new tools.
- `ledger.py import`: imports any tool's `measurements` block (the new tools all write one);
  camera and other Config inputs never become harness targets.
- Demo footage: `demo_perspective.mkv`, a rendered third-person clip with known camera and speed;
  `make_demo_footage.py --only` renders a subset.

## 1.1.0 — 2026-11-05

Tools that make the agent's work more accurate and easier to resume.

- `remake_status.py`: phase gates, open questions, assumptions, inaccessible sources and the next
  action; writes `remake/STATUS.md` as a session handoff.
- `ledger.py`: evidence and measurements with automatic IDs; refuses measurements from
  inaccessible evidence; imports `motion_track` results; generates `targets.json` by tier.
- `config_check.py`: `Config.luau` against the ledgers (drift, missing IDs, assumptions, unused
  measurements).
- `find_mover.py` and `frame_zoom.py`: detect subjects (with camera-motion compensation and a safe
  anchor) and read exact coordinates instead of estimating them.
- `pose_track.py`: multi-point tracking, joint angles, cycle period and keypose tables.
- `overlay.py`: blend, diff, checker, wipe and onion-skin views.
- `studio_snippets.py`: greybox and shot Luau for Studio/MCP, Output log cleanup, InputProbe
  binding tables.
- `preset.py` and five genre presets, always labeled ASSUMED and never applied over measured keys.
- `references/recipes.md`: exact command sequences for twelve common tasks.
- Offline Selene config in the template; sample workspace gains a measured `Config.luau`.
- `evals/`: nine eval cases and a pattern grader.
- Tests: 56 in total, including an end-to-end workflow through every phase gate.

## 1.0.0 — 2026-11-04

First release.

- `roblox-game-remaker` skill: phased research → measure → document → translate → build →
  compare workflow with evidence labels, honesty rules and a rights gate.
- 15 references checked against the Roblox creator docs snapshot of 2026-11-03.
- 14 Python CLIs for footage probing, frame extraction, contact sheets, motion tracking, unit
  and feel calculations, visual comparison, palettes, UI layout, audio onsets, breakdown
  validation, in-game measurement comparison, Blender export checks and environment checks.
- Rojo-ready Luau template with 41 Lune unit tests and a Studio smoke test.
- Synthetic demo footage with ground truth, walkthroughs and a sample breakdown.
- Claude Code plugin marketplace manifest, `skills` CLI compatibility, CI.
