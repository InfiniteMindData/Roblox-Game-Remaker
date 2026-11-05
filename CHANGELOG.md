# Changelog

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
