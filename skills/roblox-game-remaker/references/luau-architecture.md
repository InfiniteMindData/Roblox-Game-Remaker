# Luau architecture for remakes

Read this before writing code in Phase 5. The goal is a codebase where every
fidelity-relevant number lives in one place, traces to evidence, and can be tuned and
re-measured without hunting through scripts.

## 1. Project layout (Rojo template)

`assets/rojo-template/` is a working starting point. Copy it into the user's project (or merge it
into an existing Rojo tree), then build with `rojo build default.project.json -o remake.rbxlx`, or
serve it into Studio with `rojo serve`.

```text
src/shared/Remake/        -> ReplicatedStorage.Shared.Remake   (ModuleScripts)
  Config.luau             all measured constants, each tagged with evidence IDs
  Units.luau              studs/meters, FOV conventions, frames/seconds, jump solving (pure)
  Spring.luau             closed-form damped spring for camera, UI and procedural motion (pure)
  FixedStep.luau          fixed-tick accumulator that reproduces a source tick rate (pure)
  StateMachine.luau       small explicit state machine (pure)
  MovementMath.luau       acceleration ramps, coyote time and jump buffer logic (pure)
  Easing.luau             TweenService-equivalent curves plus cubic-bezier (pure)
  LightingPreset.luau     applies a measured lighting and post-processing preset
src/server/               -> ServerScriptService.Remake
  Bootstrap.server.luau   applies world, character and lighting config on the server
src/client/               -> StarterPlayer.StarterPlayerScripts.Remake
  Main.client.luau        wires the client systems
  MovementFeel.luau       acceleration and deceleration, jump shaping, coyote time, buffer, fall cap
  CameraRig.luau          follow, fixed or orthographic camera with spring lag and collision
  AnimationDriver.luau    locomotion state to clips, fades, cadence matching, markers
  UIScaler.luau           reference-resolution scaling, including integer pixel-art mode
  Haptics.luau            HapticEffect presets and custom waveforms
  VRSupport.luau          VR hands and head tracking, snap turn, comfort hooks
  ShotCamera.luau         exact camera shots for reference comparison
  DevTools/MeasurementHarness.luau   per-frame motion log for measure_compare.py (Studio only)
  DevTools/InputProbe.luau           logs every input, for verifying controller mappings
tests/lune/               pure-module unit tests (run with `lune run tests/lune/run.luau`)
tests/studio/             smoke test to run with MCP execute_luau or the Studio CLI
```

If the user already has a framework (Knit, a custom service layer, Flamework), keep it. Port
the modules as plain ModuleScripts and keep `Config` as the single source of constants.

## 2. Config is the contract

```lua
-- src/shared/Remake/Config.luau (excerpt)
Movement = {
	WalkSpeed = 20.0,        -- MS-012 (20.0 ± 0.6 studs/s)
	AccelerationTime = 0.18, -- MS-013 (time to 90% speed)
	JumpApex = 7.4,          -- MS-014
	RiseTime = 0.383,        -- MS-015
	FallTime = 0.300,        -- MS-016
},
```

- Comments carry the measurement ID and uncertainty, and `Config.Evidence` maps each key path to
  its IDs, so a reviewer can audit every number.
- When a measurement changes, update `Config` and `measurements.json` together, then re-run
  `measure_compare.py`.
- Keep presentation constants (colors, tween times) in `Config` too. They are measured, just like
  physics constants.

## 3. Client and server split

| Concern | Where | Why |
|---|---|---|
| Movement feel, camera, animation, UI, haptics, VR tracking | Client | The character is simulated on its owner's client; latency-sensitive |
| World physics constants (`Workspace.Gravity`), StarterPlayer defaults, `VRService.AvatarGestures` | Server (`Bootstrap`) | Replicated and authoritative; `AvatarGestures` must be set on the server |
| Damage, health, currency, inventory, progression, scoring, spawns | Server | Never trust the client |
| Cosmetic VFX triggered by gameplay | Server decides, clients render | `RemoteEvent` for one-shots, `UnreliableRemoteEvent` for streams |

Validate every `RemoteEvent` argument on the server for type, range, ownership, cooldown and
distance. Hand the details to the `roblox-networking` skill when it is installed.

## 4. Patterns that preserve fidelity

- **Frame-exact logic:** `FixedStep.new(60)` runs the original's tick. Visuals interpolate with
  `alpha`:

```lua
local stepper = FixedStep.new(60, 8)
RunService.PreSimulation:Connect(function(dt)
	local _, alpha = stepper:advance(dt, simulateTick)
	renderInterpolated(alpha)
end)
```

- **State machines over flags:** `StateMachine` keeps transitions explicit and logged, which
  makes timing comparisons with footage straightforward.
- **Springs for smoothing:** `Spring` is a closed-form damped oscillator, so it is stable at any
  frame rate. Its frequency and damping come from `remake_calc.py spring`, which derives them
  from measured overshoot and settle time.
- **Easing:** when the original's UI curve is not a `TweenService` style, drive it with
  `Easing.cubicBezier(x1, y1, x2, y2)` from a `RenderStepped` loop.
- **Character lifecycle:** bind on `CharacterAdded` (and for an existing character), keep every
  connection in a per-character list, and disconnect on `CharacterRemoving`. All client modules in
  the template follow this.
- **No hidden worlds:** build levels as real, inspectable Instances (Parts, Models, Packages), not
  runtime-only generation, unless the original is procedural.

## 5. Typing, linting and tests

- Start modules with `--!strict` where practical. The template's pure modules are strict.
- Lint with `selene src` (`std = "roblox"` in `selene.toml`), and format and syntax-check with
  `stylua --check src`. When Selene cannot download its Roblox library (offline or a restricted
  network), use `selene --config selene.offline.toml src`: a Luau base plus Roblox globals that
  still catches typos, unused variables and deprecated `wait`/`spawn`/`delay`.
- Unit-test pure modules with Lune: `lune run tests/lune/run.luau`. These cover Units, Spring,
  FixedStep, StateMachine, MovementMath and Easing, and run without Studio.
- Integration: `tests/studio/SmokeTest.luau` asserts that the config was applied. Run it with MCP
  `execute_luau` (`datamodel_type` Server during a playtest), or with the Studio CLI:
  `--task RunScript --runScriptFile SmokeTest.luau --outputFile out.log --quitAfterExecution`.
- Never report unit tests as "tested in Studio". Report each level separately (see
  `verification-loop.md`).

## 6. Performance budgets for faithful visuals

- Mesh triangles: at most 20,000 per mesh; budget per scene by the target device.
- Use `StreamingEnabled` for large worlds, and check that remake-critical objects are
  `Persistent` or handled with `Player:RequestStreamAroundAsync()` where needed.
- Pool VFX and projectiles; avoid creating Instances every frame.
- Profile with the MicroProfiler (Ctrl+Alt+F6, or ⌘⌥F6 on macOS), the Script Profiler, and the
  Developer Console memory tab. Quest targets at least 72 fps (see `vr-quest.md`).
