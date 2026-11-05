---
name: roblox-game-remaker
description: >-
  Recreate an existing game in Roblox Studio as close to 1:1 as the engine allows. Researches the
  original, analyzes gameplay footage frame by frame, writes an evidence-backed game breakdown,
  then implements gameplay, physics, camera, controls, UI, characters, animation, graphics, audio
  and optional Meta Quest VR with Luau, Blender and Roblox Studio (MCP when connected), and
  verifies the build against reference frames with measured diffs. Use when the user wants to
  remake, recreate, port, or faithfully rebuild a game, or a game's movement, mechanics, UI,
  animations or visuals, in Roblox; or mentions matching reference footage or screenshots,
  frame-by-frame analysis, 1:1 accuracy, game feel, or comparing a Roblox build to the original.
license: MIT
compatibility: >-
  Any Agent Skills client. Scripts need Python 3.10+ with numpy and Pillow; video tools need
  ffmpeg and ffprobe. Optional: Roblox Studio (built-in MCP server), Rojo, Lune, StyLua, Selene,
  Blender 4.x. Web research needs network access.
metadata:
  version: "1.1.0"
  roblox-docs-snapshot: "Roblox/creator-docs 2026-11-03"
---

# Roblox Game Remaker

Turn a reference game into a Roblox experience that looks, moves, sounds and responds like the
original, and prove it with measurements. The method: **research → measure → document →
translate → build → compare → fix**, repeated per system until the measured gaps meet the
agreed tolerance or are reported as engine limits.

Paths below are relative to this skill's directory. Project files go in the user's project
under `remake/` (created by `scripts/breakdown_init.py`).

## Non-negotiables

1. **Evidence before code.** Every value in the build traces to an evidence ID (`EV-012`) and a
   status label (see [Evidence labels](#evidence-labels)). Never guess something that research or
   measurement can settle; find it or flag it as `ASSUMED` and tell the user.
2. **Never fake analysis.** Only describe frames and pages you actually opened. If a video,
   link or file is unreachable, unplayable, or you cannot view images, say so, record it with
   `"accessible": false` in the evidence ledger, and ask for captures or descriptions. You do
   not "watch" videos: you extract frames, open them, and measure them with the scripts.
3. **Measure, don't eyeball.** Timings come from frame counts; distances and speeds from
   tracking with a known scale; colors from pixel samples; layout from pixel boxes. Every
   measured value carries a method and an uncertainty.
4. **Respect rights.** Settle the rights mode in Phase 0 (own IP, licensed IP, or homage). Never
   rip, decompile or extract assets from game files, and never upload copyrighted art, audio,
   logos or names without permission. Mechanics, timing and feel can be recreated; protected
   expression needs original or licensed replacements. Read
   [references/rights-and-policy.md](references/rights-and-policy.md).
5. **Roblox-native and current.** Server-authoritative gameplay, documented APIs, no deprecated
   APIs (table below). When Roblox cannot do something 1:1, say so and pick the closest faithful
   approximation; do not hide the gap.
6. **Compare continuously.** After each system lands, capture the matched shot or run the
   measurement harness and compare against the reference before moving on.
7. **Report honestly.** Label every check as Executed, Executed by user, Statically checked,
   Prepared not run, or Unverified. Never turn "looks plausible" into "tested in Studio".

## Capability check (once per session)

Run `python scripts/doctor.py` (add `--json` for machine output). It reports Python packages,
ffmpeg/ffprobe, Blender, Rojo, Lune, StyLua, Selene, and whether `remake/` exists. Then check for
yourself:

| Capability | How to tell | If missing |
|---|---|---|
| You can view images | Open one extracted frame and describe a verifiable detail | Rely on numeric script output and user descriptions; say so in the report |
| Reference media | Files the user gave, or `remake/media/` | Ask for captures, using the capture guide in `references/research-protocol.md` |
| Web research | A search or fetch succeeds | Work from user-provided material; list unresearched questions |
| Studio MCP | Tools such as `list_roblox_studios`, `execute_luau`, `screen_capture` are available | Use the Rojo/manual path; give paste-ready code and exact Studio steps |
| Rojo project | `*.project.json` in the project | Offer `assets/rojo-template/`, or work in Studio directly |
| Blender | `doctor.py` finds `blender` | Give the user the Blender steps and the export script to run |

## Session start (every session)

Run `python scripts/remake_status.py remake --write`. It evaluates every phase gate, lists open
questions, assumptions and inaccessible sources, names the next action, and saves
`remake/STATUS.md` as a handoff. Follow its next action, and run it again after each phase.
For common tasks, [references/recipes.md](references/recipes.md) has exact command sequences.

## Workflow

Each phase ends with a gate. Do not start Phase 5 on a system whose breakdown entry is missing.

**Phase 0: Intake and rights.** Fill `remake/00-intake.md`. Ask only for what is missing: exact
game, version or patch, and platform; reference media the user can supply; rights mode; scope
(start with a vertical slice: one level or loop); target devices (PC, mobile, console, Quest 3);
multiplayer needs; fidelity tier. *Gate: rights mode and scope recorded.*

**Phase 1: Research.** Follow [references/research-protocol.md](references/research-protocol.md).
Record every source with `scripts/ledger.py add-evidence`, including the ones you could not
access (`--inaccessible`). Never hand-edit IDs. Pin the
game version, because values change between patches. *Gate: each core category has sources or a
listed gap.*

**Phase 2: Footage analysis.** Follow [references/footage-analysis.md](references/footage-analysis.md)
and [references/animation-analysis.md](references/animation-analysis.md). Probe the video first:
duplicate frames change your timing precision. Extract frames, build contact sheets, find the
subject with `find_mover.py`, confirm boxes with `frame_zoom.py --mark`, track with
`motion_track.py`, and import results with `ledger.py import-track`. *Gate: `remake/measurements.json` and
`remake/shots.json` exist, and each value has a method and an uncertainty.*

**Phase 3: Breakdown.** Write `remake/breakdown.md` using
[references/game-breakdown.md](references/game-breakdown.md): every mechanic, control, camera
behavior, physics constant, character, animation, UI screen, environment, VFX, sound and system,
each with evidence, values, a Roblox plan and an acceptance test. Run
`python scripts/breakdown_check.py remake --strict`. Show the user a summary, including open
questions and assumptions. *Gate: the checker passes, or the user accepts the listed gaps.*

**Phase 4: Translation plan.** Map each entry to Roblox using
[references/roblox-translation.md](references/roblox-translation.md): units, gravity, FOV
convention, tick rate, input, rendering limits. Convert numbers with `scripts/remake_calc.py`.
Write tolerances into each acceptance test, and generate `targets.json` with
`ledger.py targets remake --tier A`.

**Phase 5: Build.** Work in this order, verifying each step before the next: (1) greybox with
correct scale, physics, movement and camera; (2) controls on every target device; (3) characters
and animation; (4) environment, lighting and materials; (5) UI; (6) VFX and audio; (7) game
systems, progression and data; (8) VR; (9) performance and polish. Start from
`assets/rojo-template/`, which puts every measured constant in one evidence-tagged `Config`
module, and run `scripts/config_check.py remake` after every Config change.

**Phase 6: Verify and fix (loop).** Follow [references/verification-loop.md](references/verification-loop.md).
Capture matched shots and compare them with `scripts/visual_compare.py`. Log motion with the
in-game measurement harness and compare it with `scripts/measure_compare.py`. Fix the largest
measured gap first, re-measure, and record each iteration in `remake/diff-log.md`.

**Phase 7: Deliver.** Fill `remake/delivery-report.md`: what matches (with numbers), remaining
gaps and why, engine limits, unverified items, the asset provenance manifest, and next steps.

## Routing table

| Task | Read |
|---|---|
| A common task end to end (jump, movement, camera, HUD, lighting, animation, greybox, Quest 3) | [recipes](references/recipes.md) |
| Finding sources, pinning versions, the capture guide for users | [research-protocol](references/research-protocol.md) |
| Video probing, frame extraction, tracking, timing, UI and color sampling | [footage-analysis](references/footage-analysis.md) |
| Poses, cycles, transitions, blend times, Animation Editor, rigs | [animation-analysis](references/animation-analysis.md) |
| Breakdown format, IDs, status rules, coverage | [game-breakdown](references/game-breakdown.md) |
| Converting engine conventions and units to Roblox, fidelity limits | [roblox-translation](references/roblox-translation.md) |
| Project layout, Luau patterns, client/server, config, testing | [luau-architecture](references/luau-architecture.md) |
| Acceleration, jumps, coyote time, camera follow, shake, hit-stop | [movement-camera-feel](references/movement-camera-feel.md) |
| Lighting, color grading, materials, sky, fog, post effects | [graphics-lighting](references/graphics-lighting.md) |
| HUD and menu layout, fonts, safe areas, UI animation timing | [ui-recreation](references/ui-recreation.md) |
| Modeling, rigging, skinning, animation export from Blender | [blender-pipeline](references/blender-pipeline.md) |
| VR, Meta Quest 3 controllers, haptics, comfort | [vr-quest](references/vr-quest.md) |
| Driving Studio through MCP, or the Rojo and Studio CLI path without it | [studio-mcp](references/studio-mcp.md) |
| Shot matching, diff metrics, playtests, profiling, acceptance | [verification-loop](references/verification-loop.md) |
| IP, licensing, Roblox policy, asset provenance | [rights-and-policy](references/rights-and-policy.md) |
| Known traps and deprecated APIs | [sharp-edges](references/sharp-edges.md) |

## Script toolbox

All scripts are Python 3.10+ standard library plus numpy and Pillow (`pip install -r
scripts/requirements.txt`). Each has `--help`, writes only to the paths you give it, makes no
network calls, and exits non-zero on bad input. Video scripts call `ffmpeg`/`ffprobe`.

| Script | Use |
|---|---|
| `doctor.py` | Report available tools and the working mode |
| `remake_status.py remake --write` | Phase gates, open items, next action; writes `remake/STATUS.md` |
| `ledger.py add-evidence / add-measurement / import-track / targets` | Ledger entries with automatic IDs and checks; tracker output to measurements; targets |
| `config_check.py remake` | Config.luau values against their measurements; stale, unsourced and assumed values |
| `find_mover.py frames/manifest.json` | Detect moving subjects (camera motion cancelled); suggest `--bbox` and `--anchor-bbox` |
| `frame_zoom.py frame.png --region x,y,w,h --mark x,y,w,h` | Zoomed crop with pixel rulers to read and confirm exact coordinates |
| `pose_track.py frames/manifest.json --point hip=x,y ... --joint knee=hip,knee,foot --cycle foot.y` | Multi-point tracking: 2D joint angles, cycle period, keypose table draft |
| `overlay.py blend\|diff\|checker\|wipe REF REC` / `overlay.py onion manifest.json` | Single-image alignment views; onion skin of a sequence |
| `studio_snippets.py greybox\|shots\|apply-shot\|extract-log\|inputs` | Generate greybox and shot Luau for Studio/MCP; clean Output logs; binding tables from InputProbe |
| `preset.py list\|show\|apply NAME --config Config.luau` | Genre starting values, written as `ASSUMED` and never over measured keys |
| `breakdown_init.py PROJECT --game "Name"` | Create `remake/` from templates (never overwrites) |
| `probe_video.py clip.mp4 --dupes` | FPS, variable frame rate, duplicate frames, effective update rate |
| `extract_frames.py clip.mp4 --out frames/ --mode range --start 120 --end 180` | Exact frames with index and timestamp manifest (`all`, `every`, `range`, `times`, `scene`) |
| `contact_sheet.py frames/manifest.json --out sheet.png` | Labeled grid of frames to review a sequence in one image |
| `motion_track.py frames/manifest.json --bbox x,y,w,h --px-per-unit 31.5 --analyze jump` | Track a feature; fit jump apex, gravity and speed |
| `remake_calc.py jump --apex 7.2 --rise-time 0.38` | Unit, FOV, jump, acceleration, spring and frame-time conversions, with `--luau` output |
| `visual_compare.py pair ref.png rec.png --out diff/` | SSIM, ΔE2000, Lab shifts, edge IoU, heatmap, grading hints |
| `palette_extract.py frame.png --region x,y,w,h` | Dominant colors as hex and `Color3.fromRGB` |
| `ui_measure.py boxes.json --luau` | Pixel boxes to UDim2 scale, AnchorPoint and aspect ratio |
| `audio_onsets.py clip.mp4` | Sound onset times mapped to video frames |
| `breakdown_check.py remake --strict` | Validate breakdown coverage, evidence links and statuses |
| `measure_compare.py output.log --targets remake/targets.json` | Compare in-game measurements with reference targets |
| `blender_roblox_export.py` | Run inside Blender: check Roblox mesh and rig limits, then export FBX or glTF |

Rehearse the pipeline, or check an install, with synthetic footage that has known answers:
`bash examples/demo/run_demo.sh /tmp/remake-demo`. The walkthroughs in `examples/` show the
movement, HUD and Quest 3 workflows with real script output, and
`examples/04-sample-workspace/remake/` is a complete breakdown that passes the strict check.

## Evidence labels

| Label | Meaning | Required |
|---|---|---|
| `VERIFIED` | Stated by an authoritative source (official docs, the developer, the game's own UI) | Source evidence ID |
| `MEASURED` | Measured by you from accessible footage or captures | Evidence ID, method, value ± uncertainty |
| `OBSERVED` | Seen in footage but not quantified | Evidence ID with frame or timestamp |
| `INFERRED` | Reasoned from other evidence | The evidence IDs and the reasoning |
| `ASSUMED` | Placeholder with no evidence | Flagged to the user; replace when possible |
| `UNKNOWN` | Not determined yet | An open question in the breakdown |

## Roblox facts that drive 1:1 work

Checked against the Roblox creator-docs snapshot in the frontmatter. Recheck them when the docs
move on.

| Fact | Value |
|---|---|
| Length unit | 1 stud ≈ 28 cm (1 m ≈ 3.57 studs) |
| Default gravity | `Workspace.Gravity` = 196.2 studs/s² (≈ 54.9 m/s², about 5.6 g) |
| Character defaults | WalkSpeed 16 studs/s; JumpHeight 7.2 studs; JumpPower 50; `UseJumpPower` true; MaxSlopeAngle 89° |
| Camera | `FieldOfView` is **vertical**, 1–120°, default 70; `ProjectionType` supports orthographic |
| Physics | 240 Hz solver; adaptive timestepping uses 240, 120 or 60 Hz islands |
| Animation Editor | 30 fps by default; priorities Core < Idle < Movement < Action < Action2 < Action3 < Action4 |
| Meshes | ≤ 20,000 triangles per mesh, ≤ 4 bone influences per vertex, watertight, frozen transforms |
| Textures | Up to 4096×4096; normal maps must be OpenGL tangent space |
| Import | `.fbx`, `.gltf`/`.glb` and `.obj`; only one animation per FBX export |
| Lighting | `Lighting.LightingStyle` (Realistic or Soft) plus `PrioritizeLightingQuality` replace the deprecated `Lighting.Technology` |
| Haptics | `HapticEffect` instances replace the deprecated `HapticService` |
| VR detection | `VRService.VREnabled`; `UserInputService.VREnabled` is deprecated |

## Top sharp edges

The full list, with fixes, is in [references/sharp-edges.md](references/sharp-edges.md).

- **Wrong FOV convention.** Unreal and many shooters quote horizontal FOV, but Roblox uses
  vertical FOV. Convert with `remake_calc.py fov`.
- **60 fps containers holding 30 fps content.** Duplicate frames halve your timing precision.
  Run `probe_video.py --dupes` before you count frames.
- **Gravity units.** Real-world 9.81 m/s² is about 35 studs/s², not 196.2. Derive gravity
  from the measured apex height and airtime, not from intuition.
- **Frame-rate-dependent logic.** Roblox clients can run above 60 fps. Integrate with `dt`, or use
  `FixedStep` to reproduce a source game's fixed tick.
- **Humanoid defaults masking feel.** A default Humanoid reaches full ground speed almost at
  once (confirm with the harness). When the original has ramps, use the template's `MovementFeel`
  or ControllerManager's `GroundController.AccelerationTime` and `DecelerationTime`.
- **Trusting the client.** Movement feel can run on the client, but the server owns damage,
  currency, inventory and progression.
- **Deprecated APIs.** `wait()`, `KeyframeReached`, BodyMovers, the `PhysicsService` collision
  group methods, `Lighting.Technology` and `HapticService` all have current replacements.

## Related skills

When they are installed, these skills complement this one: `roblox-luau`, `roblox-networking`,
`roblox-characters`, `roblox-physics`, `roblox-ui` and `roblox-studio-workflow` from
awesome-gamedev-agent-skills, and the `roblox-game` skill. This skill owns fidelity: research,
measurement, breakdown, translation and comparison. Hand generic Roblox engineering questions to
those skills.
