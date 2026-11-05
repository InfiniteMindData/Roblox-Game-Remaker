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
