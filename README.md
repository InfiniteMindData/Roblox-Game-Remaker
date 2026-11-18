# Roblox Game Remaker

An installable [Agent Skill](https://agentskills.io/specification) for evidence-linked game
reconstruction in Roblox Studio. Its difference is **measurement, uncertainty, provenance and
regression tracking**: record where a number came from, how uncertain it is, and whether the
next change made the match better or worse. Missing evidence stays unknown; accepted guesses
support a clearly provisional slice, not a claim of measured fidelity.

Published Studio checks cover a custom fighting-game simulation and a UI remake, not the full
Humanoid platformer loop. MovementFeel, CameraRig, AnimationDriver, MeasurementHarness,
InputProbe, ShotCamera and Bootstrap integration remain unverified in Studio. Synthetic Python
and pure Luau tests do not close that gap; see [the verification record](docs/VERIFICATION.md).
No matched with/without-skill trials have been run, so improved agent outcomes are not claimed.

```text
research → measure → document → translate → build → compare → fix
```

## What it gives the agent

- **A phased workflow with gates** (`SKILL.md`): intake and rights, research, footage analysis,
  breakdown, translation, build, a verify-and-fix loop, and delivery, plus honesty rules (it never
  claims to have analyzed footage it could not open).
- **Session continuity**: `remake_status.py` evaluates every gate, names the next action, and
  writes `remake/STATUS.md`; `fidelity_report.py` keeps a per-iteration scorecard and history and
  flags regressions, so work resumes correctly in a new session or after context resets.
- **17 focused references**, including **recipes** with exact command sequences for common tasks: footage analysis, animation analysis, systems analysis (enemies, spawns, drops, economy), the breakdown spec, engine-to-Roblox
  translation (units, FOV conventions, tick rates, rendering limits), movement and camera feel,
  graphics and lighting matching, UI recreation, the Blender pipeline, VR and Meta Quest 3, the
  Studio MCP and CLI, verification, rights and policy, and sharp edges, all checked against the
  Roblox creator docs.
- **29 tested scripts** (Python, numpy and Pillow, plus ffmpeg):

| Script | Does |
|---|---|
| `probe_video.py` | FPS, variable frame rate, duplicate frames, effective update rate |
| `extract_frames.py` | Exact frames with index and timestamp manifests (all, every, range, times, scene cuts) |
| `contact_sheet.py` | Labeled frame grids, including reference/recreation pairs |
| `motion_track.py` | Feature tracking with whole-frame camera compensation (shift, zoom, roll; anchor hand-off) and lost-subject checks; jump fits (rise and fall gravity) and acceleration fits |
| `camera_solve.py` | Vertical FOV, pitch and height with uncertainties from marked lines or a known object; letterbox viewport; ground-plane conversion of third-person tracks to studs |
| `remake_calc.py` | Units, horizontal/vertical FOV, frames, jump solving (metres or feet converted to studs), acceleration, spring parameters |
| `fit_curve.py` | Rank every template easing curve, a spring and an exponential approach against tracked samples; flags fits the frame rate cannot tell apart and curves no candidate matches |
| `visual_compare.py` | SSIM (global and worst local window), CIEDE2000, Lab shifts, edge IoU, heatmaps, lighting hints, batch shot lists |
| `palette_extract.py` | Dominant colors as `Color3.fromRGB` |
| `ui_measure.py` | Pixel boxes to `AnchorPoint`/`UDim2`, Luau layout output, layout diffing |
| `event_stats.py` | Event tables from footage: intervals with spread, exact binomial rate intervals, state machines, progression curves |
| `audio_onsets.py` | Sound onsets on the video timeline, mapped to frames by real timestamps (variable frame rate safe) |
| `audio_compare.py` | Duration, loudness envelope, dominant frequency and brightness of a sound; score a replacement against it with Roblox tuning hints |
| `breakdown_init.py` / `breakdown_check.py` | Create and validate the evidence-backed breakdown |
| `measure_compare.py` | Compare in-game motion logs and recorded elapsed input-response time with targets, per trial; missing targets fail |
| `clip_compare.py` | Compare a build recording or harness log with the reference clip over time: aligned position error along and off the path, event offsets, overlay plot |
| `blender_roblox_export.py` | Check Blender mesh/rig limits; select a single FBX action and frame range (Prepared, not run); or export glTF |
| `doctor.py` | Report which tools are available |
| `remake_status.py` | Initialize before status; blocked / provisional / verified gates and next action; writes `STATUS.md` |
| `fidelity_report.py` | Score every shot, metric and clip against tolerance each iteration; history, scorecard, diff-log entry; exit 1 on a regression |
| `ledger.py` | Evidence and measurements with automatic IDs; scoped gap acceptance (who/when/why); tracker import; targets |
| `config_check.py` | `Config.luau` values against their measurements (drift, missing sources, assumptions) |
| `find_mover.py` / `frame_zoom.py` | Detect moving subjects (also the player under a follow camera) and suggest tracking boxes; zoomed crops with pixel rulers |
| `pose_track.py` | Multi-point tracking: 2D joint angles, cycle period, keypose table |
| `overlay.py` | Blend, diff, checker, wipe and onion-skin views |
| `studio_snippets.py` | Greybox and projection/GUI-policy shot Luau for Studio/MCP, log cleanup, bindings |
| `preset.py` | Genre starting values, always labeled ASSUMED |

- **A Rojo-ready Luau template** (`assets/rojo-template/`): evidence-tagged `Config`, a
  closed-form `Spring`, a `FixedStep` tick emulator, jump and acceleration feel (coyote time,
  jump buffer, fall gravity, variable jump), a camera rig (follow, fixed, orthographic, shake), an
  animation driver with cadence matching, a reference-resolution UI scaler, `HapticEffect`
  haptics, VR support, a shot camera for matched captures, a measurement harness, and an input
  probe. It has 41 Lune unit tests and a Studio smoke test.
- **Examples**: synthetic demo footage with ground truth (side-on, third-person, and degraded
  the way real captures are) and a one-command pipeline run;
  walkthroughs for movement feel, HUD recreation and Quest 3; a complete sample workspace
  (breakdown plus measured `Config.luau`); and guardrail scenarios.
- **Evals** (`evals/` at the repository root): 19 test prompts, a **wording lint** (not outcome evidence), and a local-artifact
  grader against independent synthetic ground truth. With/without-skill trials remain unrun.

## Install

```bash
claude plugin marketplace add InfiniteMindData/Roblox-Game-Remaker
```

```bash
claude plugin install roblox-game-remaker@roblox-game-remaker
```

Or, for any agent:

```bash
npx skills add InfiniteMindData/Roblox-Game-Remaker
```

Then resolve the **installed** skill folder (the one containing `SKILL.md`) and your project
separately; do not run checkout-relative commands in a plugin cache. For example, a manual or
skills-CLI project install commonly uses `$PWD/.agents/skills/roblox-game-remaker`; a Claude
manual install uses `.claude/skills/roblox-game-remaker`. For a plugin, use the skill path exposed
by the client (its versioned cache path can change). In this repo use `$PWD/skills/roblox-game-remaker`.

```bash
export SKILL_ROOT="/absolute/path/to/installed/roblox-game-remaker"
export PROJECT_ROOT="/absolute/path/to/your/project"
cd "$PROJECT_ROOT"
python -m venv "$PROJECT_ROOT/.venv"
. "$PROJECT_ROOT/.venv/bin/activate"
python -m pip install -r "$SKILL_ROOT/scripts/requirements.txt"
python "$SKILL_ROOT/scripts/doctor.py" "$PROJECT_ROOT"
python "$SKILL_ROOT/scripts/remake_status.py" "$PROJECT_ROOT/remake" --init --game "My Game" --write
```

Install **ffmpeg/ffprobe** from your package manager for video analysis. Windows PowerShell:
use `$env:SKILL_ROOT` / `$env:PROJECT_ROOT` and activate `.venv/Scripts/Activate.ps1`. Full
layout-specific instructions: [installation](docs/INSTALLATION.md).

**Working in this repo?** No separate skill install is needed: `.claude/skills/roblox-game-remaker` links to the
skill, so Claude Code loads it in every session started here (on Windows, clone with
`git clone -c core.symlinks=true` so the link checks out as a link).

Manual copy, Claude.ai upload, optional tools (Rojo, Lune, StyLua, Selene, Blender) and Studio
MCP setup are covered in [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Use

Ask in plain language, for example:

- "Remake my Unity platformer in Roblox, 1:1. Here are captures in `remake/media/`."
- "Match this jump: the clip is `jump.mp4`, the character is 1.8 m tall."
- "Recreate this HUD from `hud.png` and make it scale like the original."
- "Add Meta Quest 3 support to the remake, with haptics."
- "Compare my Roblox screenshot with the reference frame and tell me what to fix."
- "This is third-person footage; how fast does the character run, and what FOV is the camera?"
- "We saw the rare drop 3 times in 20 kills. What rate do I use?"

Try the pipeline on synthetic footage with known answers:

```bash
bash "$SKILL_ROOT/examples/demo/run_demo.sh" "$PROJECT_ROOT/remake-demo"
```

## Rights

The skill recreates mechanics, timing, feel and layout faithfully. Names, characters, art,
audio, logos and level designs are reproduced only when you own the IP or have a license (for
example through Roblox's IP licensing program); otherwise it builds original replacements. It
never extracts assets from game files. See
[rights-and-policy.md](skills/roblox-game-remaker/references/rights-and-policy.md).

## Quality

CI runs the official Agent Skills validator, a repository validator, a Roblox API cross-check
of every Luau and Markdown file against the engine API reference, the Python test suite (which
checks measurements against synthetic ground truth, including compressed, blurred, low-rate,
variable-rate and HUD-covered footage), and StyLua, Selene, Lune and Rojo on the template. What was and was not verified is listed in [docs/VERIFICATION.md](docs/VERIFICATION.md).

```bash
pip install -r requirements-dev.txt
agentskills validate skills/roblox-game-remaker
python tools/validate_skill.py skills/roblox-game-remaker --strict --run-help
python -m unittest discover -s tests -v
```

## Repository layout

```text
skills/roblox-game-remaker/     the skill (copy this folder to install manually)
  SKILL.md                      workflow, rules, routing, toolbox
  references/                   17 references (incl. recipes), loaded on demand
  scripts/                      analysis and validation CLIs
  assets/templates/             remake/ workspace templates
  assets/rojo-template/         Luau template, Lune tests, Studio smoke test, offline lint config
  assets/presets/               genre starting points (ASSUMED values)
  examples/                     demo footage generator, walkthroughs, sample workspace
  agents/openai.yaml            Codex UI metadata
.claude-plugin/marketplace.json Claude Code plugin marketplace
evals/                          eval prompts and grader (maintainers; not shipped with the skill)
tools/                          repo validators (spec, Roblox API cross-check)
tests/                          end-to-end and unit tests
docs/                           installation, verification record
```

## Credits

Built on ideas from
[gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills)
and [brockmartin/roblox-game-skill](https://github.com/brockmartin/roblox-game-skill), the
[Agent Skills specification](https://agentskills.io/specification), and the
[Roblox creator docs](https://github.com/Roblox/creator-docs). MIT licensed.
