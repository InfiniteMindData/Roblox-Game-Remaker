# Roblox Game Remaker

An installable [Agent Skill](https://agentskills.io/specification) that helps AI coding agents
(Claude Code, Codex, Cursor, Gemini CLI, Copilot and others) recreate a game in Roblox Studio as
close to 1:1 as the engine allows, and **prove it with measurements**.

Most "make a game like X" prompts produce something that looks vaguely right and feels wrong.
This skill makes the agent work like a careful porting team: research the original, measure it
frame by frame, write every mechanic down with evidence before building, translate each number
into Roblox's conventions, then compare the build against the reference until the measured gaps
are within tolerance.

```text
research → measure → document → translate → build → compare → fix
```

## What it gives the agent

- **A phased workflow with gates** (`SKILL.md`): intake and rights, research, footage analysis,
  breakdown, translation, build, a verify-and-fix loop, and delivery, plus honesty rules (it never
  claims to have analyzed footage it could not open).
- **Session continuity**: `remake_status.py` evaluates every gate, names the next action, and
  writes `remake/STATUS.md`, so work resumes correctly in a new session or after context resets.
- **16 focused references**, including **recipes** with exact command sequences for common tasks: footage analysis, animation analysis, the breakdown spec, engine-to-Roblox
  translation (units, FOV conventions, tick rates, rendering limits), movement and camera feel,
  graphics and lighting matching, UI recreation, the Blender pipeline, VR and Meta Quest 3, the
  Studio MCP and CLI, verification, rights and policy, and sharp edges, all checked against the
  Roblox creator docs.
- **23 tested scripts** (Python, numpy and Pillow, plus ffmpeg):

| Script | Does |
|---|---|
| `probe_video.py` | FPS, variable frame rate, duplicate frames, effective update rate |
| `extract_frames.py` | Exact frames with index and timestamp manifests (all, every, range, times, scene cuts) |
| `contact_sheet.py` | Labeled frame grids, including reference/recreation pairs |
| `motion_track.py` | Feature tracking with camera-pan compensation; jump fits (rise and fall gravity) and acceleration fits |
| `remake_calc.py` | Units, horizontal/vertical FOV, frames, jump solving, acceleration, spring parameters |
| `visual_compare.py` | SSIM, CIEDE2000, Lab shifts, edge IoU, heatmaps, lighting hints, batch shot lists |
| `palette_extract.py` | Dominant colors as `Color3.fromRGB` |
| `ui_measure.py` | Pixel boxes to `AnchorPoint`/`UDim2`, Luau layout output, layout diffing |
| `audio_onsets.py` | Sound onsets mapped to video frames |
| `breakdown_init.py` / `breakdown_check.py` | Create and validate the evidence-backed breakdown |
| `measure_compare.py` | Compare in-game motion logs with reference targets |
| `blender_roblox_export.py` | Check Roblox mesh and rig limits in Blender, then export |
| `doctor.py` | Report which tools are available |
| `remake_status.py` | Phase gates, open items, next action; writes `STATUS.md` |
| `ledger.py` | Evidence and measurements with automatic IDs; tracker import; targets |
| `config_check.py` | `Config.luau` values against their measurements (drift, missing sources, assumptions) |
| `find_mover.py` / `frame_zoom.py` | Detect moving subjects and suggest tracking boxes; zoomed crops with pixel rulers |
| `pose_track.py` | Multi-point tracking: 2D joint angles, cycle period, keypose table |
| `overlay.py` | Blend, diff, checker, wipe and onion-skin views |
| `studio_snippets.py` | Greybox and shot Luau for Studio/MCP, Output log cleanup, binding tables |
| `preset.py` | Genre starting values, always labeled ASSUMED |

- **A Rojo-ready Luau template** (`assets/rojo-template/`): evidence-tagged `Config`, a
  closed-form `Spring`, a `FixedStep` tick emulator, jump and acceleration feel (coyote time,
  jump buffer, fall gravity, variable jump), a camera rig (follow, fixed, orthographic, shake), an
  animation driver with cadence matching, a reference-resolution UI scaler, `HapticEffect`
  haptics, VR support, a shot camera for matched captures, a measurement harness, and an input
  probe. It has 41 Lune unit tests and a Studio smoke test.
- **Examples**: synthetic demo footage with ground truth and a one-command pipeline run;
  walkthroughs for movement feel, HUD recreation and Quest 3; a complete sample workspace
  (breakdown plus measured `Config.luau`); and guardrail scenarios.
- **Evals** (`evals/`): test prompts with expected behavior and a pattern grader, for measuring the
  skill with and without it, as the Agent Skills evaluation guide recommends.

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

Then install the script dependencies (and ffmpeg):

```bash
pip install -r skills/roblox-game-remaker/scripts/requirements.txt
```

**Working in this repo?** Nothing to install: `.claude/skills/roblox-game-remaker` links to the
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

Try the pipeline on synthetic footage with known answers:

```bash
cd skills/roblox-game-remaker
bash examples/demo/run_demo.sh /tmp/remake-demo
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
checks measurements against synthetic ground truth), and StyLua, Selene, Lune and Rojo on the
template. What was and was not verified is listed in [docs/VERIFICATION.md](docs/VERIFICATION.md).

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
  references/                   16 references (incl. recipes), loaded on demand
  scripts/                      analysis and validation CLIs
  assets/templates/             remake/ workspace templates
  assets/rojo-template/         Luau template, Lune tests, Studio smoke test, offline lint config
  assets/presets/               genre starting points (ASSUMED values)
  examples/                     demo footage generator, walkthroughs, sample workspace
  evals/                        eval prompts and grader
  agents/openai.yaml            Codex UI metadata
.claude-plugin/marketplace.json Claude Code plugin marketplace
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
