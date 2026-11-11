# Sources and verification record

What this skill's facts and code were checked against, how, and what remains unverified.
Recheck when the sources move on.

## Sources researched

| Source | How it was used |
|---|---|
| Agent Skills specification (`agentskills/agentskills` repo, `docs/specification.mdx`) | Frontmatter rules, directory layout, progressive disclosure limits. The skill passes the reference validator (`agentskills validate`, PyPI `skills-ref` 0.1.1) |
| `gamedev-skills/awesome-gamedev-agent-skills` | Skill-authoring conventions (router-free single skill, references one level deep, script CLI shape with exit codes 0/1/2, `agents/openai.yaml`, marketplace manifest), and its Roblox skills' Studio MCP and verification-ladder guidance |
| `brockmartin/roblox-game-skill` | Router-plus-references architecture and MCP mode detection. This skill keeps detection but uses the current built-in MCP tool names |
| Roblox creator docs (`Roblox/creator-docs`, snapshot of 2026-11-03), Markdown guides and the engine API reference YAML | Every Roblox fact in `SKILL.md` and `references/`, and every API used in the Luau template |
| `Roblox/studio-rust-mcp-server` README | Archived on 2026-04-03; Roblox recommends the built-in Studio MCP server instead |

`create.roblox.com` and `agentskills.io` were not reachable from the build environment, so
their content was read from the official GitHub sources above, which publish the same pages.

## Facts confirmed in the Roblox docs snapshot

- 1 stud ≈ 28 cm (`physics/units.md`); `Workspace.Gravity` defaults to 196.2 studs/s².
- `StarterPlayer` defaults: WalkSpeed 16, JumpHeight 7.2, JumpPower 50, UseJumpPower true,
  MaxSlopeAngle 89°.
- `Camera.FieldOfView` is vertical, 1–120°, default 70; `Camera.ProjectionType` supports
  Orthographic, with `OrthographicMode` and `OrthographicSize`.
- Physics at 240 Hz; adaptive timestepping uses 240, 120 and 60 Hz islands.
- Animation Editor runs at 30 fps by default; the AnimationPriority order; `KeyframeReached` is
  deprecated in favor of `GetMarkerReachedSignal`.
- Meshes: at most 20,000 triangles each, at most 4 influences per vertex, no root influences,
  frozen bone transforms; one animation per FBX; textures up to 4096×4096; OpenGL normal maps.
- Blender FBX export: Path Mode Copy + Embed Textures, Apply Scalings = FBX Unit Scale, Add Leaf
  Bones off, Bake Animation only for animated exports; Forward Z / Up Y in the Blender guide.
- Importer formats: `.fbx`, `.gltf`/`.glb`, `.obj`.
- Studio MCP: enable path, Quick connect clients, stdio commands, and the built-in tool list.
- Studio CLI: `--task RunScript` with `--runScriptFile`, `--outputFile`, `--quitAfterExecution`.
- VR: OpenXR backend; Quest Auto Quality Mode targets at least 72 fps; comfort settings; the
  `VRService` API; `AvatarGestures` must be set on the server.
- Deprecated: `UserInputService.VREnabled` (use `VRService.VREnabled`).
- Haptics: `HapticService` is deprecated, superseded by `HapticEffect` (types UIHover, UIClick,
  UINotification, GameplayExplosion, GameplayCollision, Custom; waveform keys in milliseconds);
  supported devices include the Quest Touch controller.
- `Lighting.Technology` is deprecated, superseded by `LightingStyle` and
  `PrioritizeLightingQuality`; light range is clamped to 120 studs; at most 255 `Highlight`s are
  shown at once.
- `PhysicsService` collision-group methods are deprecated in favor of the `WorldRoot`
  (`Workspace`) methods; BodyMovers are deprecated in favor of constraints.
- IP licensing: Roblox's license catalog and the Terms of Use statement on using others' IP.
- Animation Capture (Body): a single person, a continuous shot under 15 s, a stable camera.

## Facts added in 1.2.0

Checked in the engine API reference YAML of the creator-docs snapshot of 2026-11-10 (commit
`7cbffff`). The Markdown guides behind the facts above were not re-read for this release.

- `Enum.EasingStyle` items Linear, Sine, Back, Quad, Quart, Quint, Bounce, Elastic, Exponential,
  Circular, Cubic (the names `Easing.luau` and `fit_curve.py` use); `Enum.EasingDirection` In,
  Out, InOut; `TweenInfo.new(time, easingStyle, easingDirection, repeatCount, reverses,
  delayTime)` with defaults 1, Quad, Out. Discrepancy left as found: `TweenService:GetValue`
  mentions `EasingStyle.Bezier` and `EasingStyle.Spring`, which the enum page does not list; the
  skill does not use them.
- `Random.new(seed)`, `Random:NextNumber`, `Random:NextInteger`.
- Audio: `Sound.PlaybackSpeed` raises pitch and speed together; `Sound.Pitch` is deprecated;
  `Sound.Volume` is 0 to 10, default 0.5, with no stated scale (the skill says to re-measure
  after changing it); `AudioPlayer.Volume` is a multiplier on the output stream, 0 to 10;
  `AudioPlayer.PlaybackSpeed` 0 to 20; `AudioPitchShifter.Pitch` multiplies pitch, 0.5 to 2.
- Input timing: `RunService.PreRender` fires every frame before the frame is rendered;
  `UserInputService.InputBegan`, `Humanoid:GetState` and `Humanoid.StateChanged` are current.

## Automated checks (all passing at release)

The table records the 1.2.0 release; later runs are in the 1.2.1–1.2.2 section below.

| Check | Tool | Result |
|---|---|---|
| Agent Skills spec | `agentskills validate skills/roblox-game-remaker` | Valid skill |
| Repo rules and links | `tools/validate_skill.py --strict --run-help` | 0 errors, 0 warnings |
| Roblox API names in all Luau and Markdown | `tools/check_roblox_api.py` against 629 classes and 521 enums (snapshot 2026-11-10) | 0 errors, 0 warnings (64 files) |
| Python scripts | `python -m unittest discover -s tests` (110 tests; 6 skip without Lune, StyLua, Selene or Rojo, and 2 without the API docs path, which passed when it was set) | Pass |
| Measurement accuracy | Synthetic footage with ground truth | Jump apex 8.006 (8), rise 0.402 s (0.400), fall 0.284 s (0.283), gravities 99.2/198.9 (100/200); run 19.996 studs/s (20), t90 0.227 s (0.225) through a panning camera |
| Color science | CIEDE2000 against Sharma et al. (2005) test pairs | Exact to 4 decimals |
| Luau formatting and syntax | StyLua 2.6 | Clean (1.2.0: in CI) |
| Luau lint | Selene 0.31 with the bundled offline std (`selene.offline.toml`; the full Roblox std could not be downloaded in the build environment) | 0 errors, 0 warnings; flags deprecated `wait`/`spawn` (1.2.0: in CI with the full Roblox std) |
| Luau unit tests | Lune 0.11 (41 tests: Units, Spring, FixedStep, StateMachine, MovementMath, Easing, UIScaler) | Pass (1.2.0: in CI) |
| Place build | Rojo 7.7, hierarchy inspected with Lune's Roblox library | Builds; 27 instances inspected at 1.1.0 (1.2.0: builds in CI) |
| Subject detection | `find_mover.py` on the demo clips | Boxes overlap the true sprite boxes with IoU > 0.7 (static and panning camera); the suggested command reproduces the hand-picked measurements |
| Pose tracking | `pose_track.py` on a synthetic leg with known angles | Thigh angle within 0.3°, knee within 0.7°, cycle period 29.9 frames (true 30) |
| Generated Studio code | `studio_snippets.py greybox` output executed in Lune's Roblox DataModel | Correct sizes and positions in studs; re-running rebuilds instead of duplicating |
| Presets | Every preset applied to the template and loaded in Lune | Valid Luau; measured keys are never overwritten |
| Whole workflow | `tests/test_end_to_end.py`: init → evidence → probe/extract/find_mover/track → import → breakdown → targets → preset + measured Config → greybox → harness log → comparisons → `fidelity_report` → delivery | Every phase gate advances as expected |

The 1.2.0 build environment could not run StyLua, Selene, Lune or Rojo locally (running
downloaded release binaries was not permitted there), so for 1.2.0 they ran in CI: GitHub Actions
run 19 on commit `7145197` passed StyLua, Selene (full Roblox std), the Lune unit tests and the
Rojo build, plus the Python suite on 3.10 and 3.12. That commit also fixed the two CI jobs that
had been failing before this release (a Selene warning in `InputProbe.luau`, and the 3.10 job,
which could not install `skills-ref` and so had never run the tests).

## New tools in 1.2.0: accuracy on synthetic input

| Tool | Test input | Result (truth) |
|---|---|---|
| `camera_solve.py vanishing` | Projected lines from a known camera (exact marks) | vFOV 70.000° (70), pitch −20.000° (−20), roll −3.000°, height 10.000 (10) |
| `camera_solve.py vanishing` | Whole-pixel marks, two cameras | vFOV and pitch within 2× the reported ±1 px uncertainty |
| `camera_solve.py` on the rendered third-person clip | Floor-square edges marked to whole pixels | vFOV 59.81 ± 1.67° (60), pitch −35.01 ± 0.80° (−35), height 9.03 ± 0.20 (9) |
| `camera_solve.py ground` | Projected track of a diagonal run | 12.0005 ± 0.11 studs/s (12), t90 0.270 s (0.270), ground point (10.000, 10.000) |
| `motion_track --scale-search` + `camera_solve ground` | Rendered third-person clip | 9.993 ± 0.215 studs/s (10), t90 0.275 s (0.270) |
| `camera_solve.py size` | 300 px span, 5 studs at 20 | focal 1200.000 px (exact) |
| `clip_compare.py` | 60 fps reference vs 30 fps recreation, analytic curves | Motion start 0.2013 / 0.7002 s (0.2 / 0.7); rms 0.978 (analytic 0.960, floor 0.333); speed_90 offset 0.050 ± 0.037 s (0.045) |
| `fit_curve.py` | 60 fps tweens, 0.15 px noise | Quad Out, Back Out, Sine InOut, Elastic Out, Bounce Out, Cubic In, Linear identified; durations within 0.0002 s of 0.400; spring ω 12.019 (12), ζ 0.600 (0.6) |
| `fit_curve.py` | Sine Out at 10 fps, 2 px noise | Flagged not distinguishable from Quad Out; truth always the best fit or listed as equal |
| `event_stats.py` | Clopper-Pearson, Student t, Wilson | 3 of 20: 0.03207094–0.37892683 (R `binom.test`); t(0.975; 2, 9, 30) to 6 decimals |
| `event_stats.py` | Synthetic event table | Fixed 2.5 s spawn timer exact; 6 of 40 drops interval exact; state dwell 0.400 / 0.200 s exact; XP ratio 1.15 within 0.001 |
| `audio_compare.py` | Tone bursts and a chirp | Duration 0.2493 s (0.25), 439.89 Hz (440), centroid 440.0 / 660.0 Hz; replacement +3.02 dB (3), ×1.201 (1.2), +101 cents (100); chirp tracked within 1% |
| `fidelity_report.py` | Two scripted iterations | Regressions in a shot and a clip detected; exit 1; diff-log entry and scorecard written |
| `measure_compare` input latency, `event_stats --latency` | Synthetic harness log and overlay table | Means exact; timeouts counted, not averaged |

## Degraded footage (1.2.0)

`make_demo_footage.py --only degraded` renders the demo jump and run again the way real captures
go wrong, with the same ground truth; `tests/test_degraded_footage.py` asserts that each result
is inside its bound, or warns with an uncertainty that covers the truth, or stops with an error.
Results with the clean-footage boxes (truth: apex 8, rise 0.400 s, fall 0.283 s, g 100/200;
run 20 studs/s, t90 0.225 s):

| Variant | Result | Behavior |
|---|---|---|
| H.264 CRF 32 (jump) | apex 7.999, rise 0.401, fall 0.283, g 99.6/199.5 | Accurate; 8 low-score samples warned |
| H.264 CRF 32 (run) | 19.45 ± 0.61 studs/s, t90 0.198 ± 0.044 s | Anchor drifts: split-half check widens the uncertainty to cover the truth |
| H.264 CRF 40 (run) | none | Stops: "the template has no texture" (the background is destroyed) |
| Motion blur, 360° shutter (jump) | apex 8.011, rise 0.398, fall 0.287, g 101.0/194.1 ± 5.8 | Accurate; low-score warning |
| Motion blur (run) | 20.04 ± 0.15 studs/s, t90 0.233 s | Accurate; low-score warning |
| 30 fps content in 60 fps (jump) | apex 8.022, rise 0.402, fall 0.287 ± 0.035 s | Repeated frames dropped; `content_fps` 28.6; precision one content frame |
| Variable frame rate, dropped frames (jump) | apex 8.002, rise 0.402, fall 0.281, g 99.0/202.6 | Accurate from per-frame timestamps |
| HUD bar over the subject (run) | 20.005 studs/s, t90 0.227 s | 12–13 lost samples excluded and reported |
| Third-person, fixed template (`camera_solve`) | none | Withheld: the track is unreliable |

Found and fixed while building this suite (each was a confident wrong number or a misleading
failure before 1.2.0):

- `motion_track` jump fits included a grounded sample on each side of the flight. Unless
  takeoff fell exactly on a frame, that biased the rise gravity: 88.9 (truth 100) and rise time
  0.427 s (truth 0.400) on the VFR clip. The fits now use airborne samples only.
- `probe_video --dupes` counted frames where nothing moves as duplicates: the clean 60 fps jump
  read as 30.75 fps content and the 30-in-60 clip as 16.5 fps. It now estimates the update rate
  only where something moves (clean 58.5, 30-in-60 30.7).
- `motion_track` claimed one container frame (16.7 ms) of timing precision on 30 fps content; the
  30-in-60 fall time missed the truth by more than its uncertainty. Repeated frames are now
  detected and dropped.
- `motion_track` ignored the anchor's match score: under H.264 the anchor drifted and the run
  read 19.04 studs/s with a ±0.15 uncertainty. Lost-anchor samples are now excluded, and the
  split-half check widens the uncertainty when drift remains.
- A lost match was extrapolated off-screen and crashed with "search window is smaller than the
  template". Predictions are now clamped to the frame and stop after weak matches.
- `find_mover` offered a screen-fixed HUD panel as the moving subject on a panning shot (IoU 0
  with the real subject). Screen-fixed regions are now detected and left out.
- A fixed-size template drifted onto the background as a third-person subject shrank (7.7 studs/s
  for a true 10). `--scale-search` tracks it (9.99 ± 0.22), and `camera_solve` withholds numbers
  from an unreliable track.

Not exercised on degraded footage: `pose_track` (it shares the tracker but not the exclusion
logic), `audio_onsets`, and `camera_solve` with compressed third-person footage.

## Checked in 1.2.1–1.2.2 (Windows, and live in Roblox Studio)

**Windows 11, Python 3.12** (Windows was not covered before 1.2.1):

| Check | Result |
|---|---|
| `python -m unittest discover -s tests` | 122 tests pass, 4 skipped (StyLua and Selene not installed). Before the 1.2.1 fixes: 110 tests, 3 failures and 1 error, all from Windows code pages and symlink checkout |
| `tools/validate_skill.py --strict --run-help`, `agentskills validate` | 0 errors, 0 warnings; valid skill |
| Lune unit tests | 47 pass (adds `SimRecorder.spec`) |
| Rojo build of the template | Builds |
| `examples/demo/run_demo.sh` | Completes; it failed on its first line before 1.2.1 (`python3` is the Microsoft Store placeholder on Windows) |
| `doctor.py` | Finds and starts a Blender installed as a `.cmd` launcher (it reported "version check failed" before) |

StyLua and Selene did not run locally for 1.2.1–1.2.2; CI runs them. The CI runs for both commits
were still queued on GitHub when this was written.

**Live Roblox Studio through the built-in MCP server**, on a published fighting game with a
deterministic 60 Hz simulation and no Humanoid. `SimRecorder` was called from the game's
simulation step through a small adapter; the targets come from the game's own config and move
data:

| Measured | Result | Design value |
|---|---|---|
| Walk forward / backward (`ground_speed[walkF]`, `[walkB]`) | 9.0 / 7.0 studs/s | 9 / 7 |
| Jump apex | 6.600 studs | 6.6 |
| Jab startup / active / recovery, whiffed (`--interval`) | 7 / 2 / 11 frames, total 20, on every jab | first active frame 7, active 7–8, total 20 |
| Jab that connected | contact on frame 7; total 25 (5 frames of hitstop pause the move's counter) | hitstop is real behavior, not a measurement error |
| The game's own regression suite after the hooks were added | 106 checks, 0 failures | — |

The same session confirmed the MCP behavior the references now describe: `screen_capture` returns
a JPEG at the viewport size (1581x615 here), `user_keyboard_input` reaches the game's own input
code, and `get_console_output` keeps only recent output (a few seconds of a 60 Hz log). It also
found the 1.2.2 `measure_compare` bugs: `attack..hit` paired whiffed jabs with a later hit, and a
back-walk distorted `accel_t90` (138 frames instead of 0).

## Checked in 1.3.0 (UI workflow, live in Roblox Studio)

The full workflow ran on a menu remake from two screenshots (an homage: original names and art):
intake, evidence (the YouTube video recorded as not downloaded), 11 measurements from `frame_zoom`
and `palette_extract`, a breakdown passing `breakdown_check --strict` (one ASSUMED effect), a
layout module from `ui_measure --luau`, the build in Studio, and two iterations:

| Iteration | Result |
|---|---|
| 1 (guessed font ratios) | text cap height up to 0.9% of the screen short; everything else within 0.5% |
| 2 (ratios calibrated from iteration 1's capture) | all 17 elements within 0.41% of the screen (tolerance 1.0%) |
| 1.3.0 tools on the same capture (`ui-rects`, `--from-capture`, `--compare --out`) | same boxes as the hand-written extractor; worst 0.77% (the description line over the 3D scene is noisier); `fidelity_report` scores it `ui:ref-boxes` pass, r 0.769 |

Behavior from the menu's own `REMAKE_MENU` log (Executed): title to menu on Return; W/S and the
arrows move and wrap; the sub-row opens only on its option, shifting the options below by its
height; A/D and the arrows move inside it; Return/J confirm; mouse hover and click work.

## Not measured yet

- The skill evals in `evals/` (19 cases) have not been run with and
  without the skill. Run them before and after changing the instructions. `tests/test_evals.py`
  only checks that the cases, their inputs and their pattern checks are consistent.

## Not verified (needs Roblox Studio or hardware)

These are written against the documented APIs but were not executed in Studio or on a device.
Treat them as "Prepared, not run" until you run them. (`SimRecorder` has run live; see above.
The game it ran in has no Humanoid, so `MeasurementHarness` itself is still unverified.)

- The client modules (MovementFeel, CameraRig, AnimationDriver, Haptics, VRSupport, ShotCamera,
  MeasurementHarness, InputProbe) and the server Bootstrap in a live Studio session.
- The MeasurementHarness input-latency mode added in 1.2.0 (`DevTools.MeasureLatency`). It passes
  the creator-docs cross-check (`RunService.PreRender`, `UserInputService.InputBegan`,
  `Humanoid:GetState`), StyLua, Selene and the Rojo build in CI, and `measure_compare` parses its
  log lines in tests, but it has not run in Studio, and its frame counts have not been compared
  with a known latency. The template
  includes `tests/studio/SmokeTest.luau` for this.
- MovementFeel's override order relative to the default ControlModule (it binds right after
  `Enum.RenderPriority.Input`). Projects using the Input Action System rollout or a custom
  PlayerModule should verify it with the harness.
- The Quest 3 Touch-controller `KeyCode` mapping and the `HapticEffect.Position` to left/right
  hand mapping (not documented as tables; verify with InputProbe on a headset).
- `blender_roblox_export.py` inside Blender (its pure checks are unit tested; the `bpy` export
  path was not run, because Blender was not available).
- Whether `GroundController.AccelerationTime` matches a measured t90 exactly (the docs call it an
  estimate; the skill says to tune it with the harness).
