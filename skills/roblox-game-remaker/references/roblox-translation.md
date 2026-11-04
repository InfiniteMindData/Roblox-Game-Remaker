# Translating a game to Roblox

Read this in Phase 4. It covers the conventions that silently break 1:1 remakes, and the
closest Roblox equivalent for each source feature. Use `scripts/remake_calc.py` for every
conversion so the numbers are reproducible.

## 1. Choose the world scale once

All lengths go through one constant, `Config.World.StudsPerMeter`:

| Option | Value | Use when |
|---|---|---|
| Official | 1 stud ≈ 0.28 m, so **3.571 studs/m** | A custom character of the original's size; the world is built to real metrics |
| Character-relative | `avatar_height_studs / original_character_height_m` | Players keep their Roblox avatars, and the world must feel the same relative to them |

Rules:

- **Time never scales.** Durations, airtimes, frame counts, cooldowns and tween times stay
  identical.
- **Lengths scale linearly:** distances, heights, speeds, accelerations and gravity are all
  multiplied by the length factor.
- Record the choice and its reason in the intake, and never mix the two.

```bash
python scripts/remake_calc.py units --meters 1.8 --studs-per-meter 3.571     # height
python scripts/remake_calc.py units --mps 6.0 --studs-per-meter 3.571        # speed
python scripts/remake_calc.py units --mps2 9.81 --studs-per-meter 3.571      # gravity -> 35.03 studs/s^2
```

## 2. Axis, handedness and FOV conventions

| Engine | Length unit | Up | Handedness | Camera FOV property |
|---|---|---|---|---|
| **Roblox** | stud ≈ 0.28 m | +Y | right-handed, `LookVector` = −Z | **vertical** (`Camera.FieldOfView`, default 70°) |
| Unity | 1 m | +Y | left-handed | vertical by default |
| Unreal | 1 cm | +Z | left-handed | horizontal |
| Godot | 1 m | +Y | right-handed | vertical by default (`keep_aspect` = height) |
| Source-engine games | about 1 inch | +Z | — | horizontal, defined at 4:3 |

Engine conventions are defaults that a game may override. If the game shows a FOV slider,
find out what it measures: test at two aspect ratios, or check the developer's notes.

```bash
python scripts/remake_calc.py fov --horizontal 90 --aspect 16:9    # -> vertical 58.72
python scripts/remake_calc.py fov --vertical 70 --aspect 21:9      # -> horizontal
python scripts/remake_calc.py fov --horizontal 90 --aspect 4:3 --to-aspect 16:9   # Hor+ games
```

Roblox keeps vertical FOV constant across window sizes when `Camera.FieldOfViewMode` is
`Vertical`. If the original keeps horizontal FOV, which is common on ultrawide-locked games,
recompute `FieldOfView` from `ViewportSize` in a `ViewportSize` changed handler.

## 3. Time and tick rate

- Roblox physics runs at 240 Hz with adaptive timestepping (islands at 240, 120 or 60 Hz).
  Clients render at a variable frame rate that can exceed 60 fps.
- If the original's logic is frame-locked (fighting games, many platformers, retro games),
  run that logic in `FixedStep` (template) at the original tick rate, and interpolate visuals.
  Frame data like "12 frames startup" stays exact.
- Never put `+= constant` per `RenderStepped` in gameplay code. Multiply by `dt`, or use the
  fixed step.
- `task.wait(n)` resumes on the next scheduler step after `n`, so it is not frame-exact. Use
  `RunService` events or the fixed step for timing-critical sequences.

## 4. Character controller choice

| Original behavior | Roblox approach |
|---|---|
| Standard third-person action, instant-ish acceleration | Humanoid with tuned `WalkSpeed`, `JumpHeight` (`UseJumpPower = false`), `Workspace.Gravity` |
| Acceleration and deceleration ramps, friction feel | `ControllerManager` + `GroundController.AccelerationTime` / `DecelerationTime` / `Friction`, or the template `MovementFeel` ramp on Humanoid |
| Asymmetric jump (falls faster), variable jump height, coyote time, jump buffer | Template `MovementFeel`: extra downward force (`VectorForce`) during the fall, and when jump is released early |
| Air control limits | `AirController.MoveMaxForce` (ControllerManager), or clamp the air move vector in `MovementFeel` |
| Fully kinematic or retro (exact pixels per frame) | Custom controller: anchored or `AlignPosition`-driven root, fixed-step integration, own collision via shapecasts (`Workspace:Blockcast`/`Spherecast`) |
| Vehicles | Constraints (`HingeConstraint` motors, `SpringConstraint`, `CylindricalConstraint`), or a custom raycast vehicle |

The player's character is simulated on its owner's client, so movement feel belongs in client
code. The server validates gameplay consequences (see `luau-architecture.md`).

## 5. Input

- Use the **Input Action System**: an `InputContext` holding `InputAction`s, each with an
  `InputBinding` per device. Set `Workspace.PlayerScriptsUseInputActionSystem` to `Enabled` so the
  default scripts use it as well.
- Map the original's actions one to one: Bool for presses, Direction1D for triggers and pedals,
  Direction2D for sticks and WASD, ViewportPosition for cursors.
- Analog thresholds: `InputBinding.PressedThreshold` and `ReleasedThreshold` reproduce
  "half-pull" trigger behavior; `ResponseCurve` shapes stick aim.
- Hold and tap, double-tap, charge: implement them in the action handler with the measured
  windows from the breakdown.
- Some original bindings conflict with Roblox reserved keys (for example `Esc` for the menu, and
  the gamepad menu buttons). Record each conflict and the substitute in `CTRL` entries.
- Touch: provide on-screen buttons bound through `InputBinding.UIButton`.

## 6. Rendering feature map

Roblox has no user-authored shaders. Map each visual feature to the closest native tool and
record the gap.

| Source feature | Roblox approach | Fidelity note |
|---|---|---|
| PBR materials | `SurfaceAppearance` (Color, Normal, Metalness, Roughness, Emissive mask), `MaterialVariant` for tiling materials | Good. Normal maps must be OpenGL |
| Unlit or flat shading | `LightingStyle = Soft`, `SmoothPlastic`, high `Ambient`/`OutdoorAmbient`, or `SurfaceAppearance` with an emissive mask | Approximate |
| Toon outlines | Inverted-hull shell mesh (scaled copy with flipped normals), or `Highlight` (outline and fill; the client shows at most 255 at a time) | Shell meshes look closest; budget the triangles |
| Tonemapping | `ColorGradingEffect.TonemapperPreset` (`Default` or `Retro`) | Two presets only |
| Color grading | `ColorCorrectionEffect` (brightness, contrast, saturation, tint) | No LUTs |
| Bloom, DOF, sun rays, blur | `BloomEffect`, `DepthOfFieldEffect`, `SunRaysEffect`, `BlurEffect` | Parameters differ; tune against shots |
| Fog and atmosphere | `Lighting.FogStart`/`FogEnd`/`FogColor`, or `Atmosphere` (Density, Offset, Haze, Glare, Color, Decay) | Atmosphere overrides fog |
| Skybox | `Sky` (six faces, or skybox textures), `Clouds` with terrain | Use original or licensed art |
| Animated textures and UV scroll | `Texture.OffsetStudsU/V` tweened, `ParticleEmitter` flipbooks, `Beam` texture speed | Good for simple scrolling |
| Decals, blood, bullet holes | `Decal`, or pooled small parts with decals | No deferred decals |
| Screen overlays (CRT, vignette, damage flash) | Full-screen `ImageLabel`/`Frame` with transparency tweens | Not true post-process |
| Pixel art and 2D | UI rendering (`ImageLabel` with `ImageRectOffset`/`ImageRectSize` sprite sheets, `ResampleMode = Pixelated`), or `Camera.ProjectionType` orthographic with flat parts | Integer `UIScale` for crisp pixels |
| Isometric or orthographic games | `Camera.ProjectionType` orthographic, with `OrthographicMode` and `OrthographicSize` (in studs) | Matches true orthographic projection |
| Runtime textures and meshes | `EditableImage` and `EditableMesh` (memory budgets and permissions apply) | Use sparingly |
| Point lights beyond 120 studs | Not possible: light range is clamped to 120 studs | Fake it with emissive surfaces and fog |
| Motion blur, SSR, custom GI | Not available | Record as an engine limit |

## 7. Audio

- Prefer the audio API objects (`AudioPlayer` → `AudioEmitter`/`AudioDeviceOutput`, connected by
  `Wire`s, plus effects such as `AudioEqualizer`, `AudioReverb` and `AudioCompressor`) for mixing
  fidelity. `Sound` with `SoundGroup` remains valid for simple cases.
- Time cues to animation markers, not to `task.wait`.
- Use original, licensed, or Roblox-provided audio only (see `rights-and-policy.md`).

## 8. Multiplayer and authority

- Single-player originals still run on a Roblox server. Decide which state the server owns
  (progression, inventory, damage, currency) and keep feel on the client.
- Multiplayer originals: document the tick rate, lag compensation and authority model in `SYS`,
  then implement with RemoteEvents (reliable), UnreliableRemoteEvents (cosmetic streams) and
  server validation.

## 9. Fidelity tiers (defaults; adjust in intake)

| Aspect | Tier S (exacting) | Tier A (faithful) | Tier B (recognizable) |
|---|---|---|---|
| Timings | ±1 source frame | ±2 frames | ±10% |
| Speeds, heights, distances | ±3% | ±7% | ±15% |
| Camera FOV and offset | ±1°, ±3% | ±2°, ±7% | ±5°, ±15% |
| UI box positions and sizes | ±0.5% of screen | ±1% | ±3% |
| Color (mean ΔE2000 on matched regions) | ≤ 3 | ≤ 6 | ≤ 10 |
| Shot SSIM (only where the assets are equivalent) | ≥ 0.90 | ≥ 0.80 | ≥ 0.65 |

In homage mode, art is deliberately different, so judge visuals by layout, palette, lighting
and silhouette (edge IoU, ΔE on palette regions) rather than whole-frame SSIM.
