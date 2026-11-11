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

## Automated checks (all passing at release)

| Check | Tool | Result |
|---|---|---|
| Agent Skills spec | `agentskills validate skills/roblox-game-remaker` | Valid skill |
| Repo rules and links | `tools/validate_skill.py --strict --run-help` | 0 errors, 0 warnings |
| Roblox API names in all Luau and Markdown | `tools/check_roblox_api.py` against 629 classes and 520 enums | 0 errors, 0 warnings |
| Python scripts | `python -m unittest discover -s tests` (56 tests) | Pass |
| Measurement accuracy | Synthetic footage with ground truth | Jump apex 8.005 (8), rise 0.4015 s (0.400), fall 0.2835 s (0.2828), gravities 99.4/199.0 (100/200); run 19.996 studs/s (20), ramp 0.252 s (0.250) through a panning camera |
| Color science | CIEDE2000 against Sharma et al. (2005) test pairs | Exact to 4 decimals |
| Luau formatting and syntax | StyLua 2.6 | Clean |
| Luau lint | Selene 0.31 with the bundled offline std (`selene.offline.toml`; the full Roblox std could not be downloaded in the build environment) | 0 errors, 0 warnings; flags deprecated `wait`/`spawn` |
| Luau unit tests | Lune 0.11 (41 tests: Units, Spring, FixedStep, StateMachine, MovementMath, Easing, UIScaler) | Pass |
| Place build | Rojo 7.7, hierarchy inspected with Lune's Roblox library | Builds; 27 instances in the intended services |
| Subject detection | `find_mover.py` on the demo clips | Boxes overlap the true sprite boxes with IoU > 0.7 (static and panning camera); the suggested command reproduces the hand-picked measurements |
| Pose tracking | `pose_track.py` on a synthetic leg with known angles | Thigh angle within 0.3°, knee within 0.7°, cycle period 29.9 frames (true 30) |
| Generated Studio code | `studio_snippets.py greybox` output executed in Lune's Roblox DataModel | Correct sizes and positions in studs; re-running rebuilds instead of duplicating |
| Presets | Every preset applied to the template and loaded in Lune | Valid Luau; measured keys are never overwritten |
| Whole workflow | `tests/test_end_to_end.py`: init → evidence → probe/extract/find_mover/track → import → breakdown → targets → preset + measured Config → greybox → harness log → comparisons → delivery | Every phase gate advances as expected |

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

## Not measured yet

- The skill evals in `skills/roblox-game-remaker/evals/` have not been run with and without the
  skill. Run them before and after changing the instructions.

## Not verified (needs Roblox Studio or hardware)

These are written against the documented APIs but were not executed in Studio or on a device.
Treat them as "Prepared, not run" until you run them.

- The client modules (MovementFeel, CameraRig, AnimationDriver, Haptics, VRSupport, ShotCamera,
  MeasurementHarness, InputProbe) and the server Bootstrap in a live Studio session. The template
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
