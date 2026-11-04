# Movement and camera feel

Read this for `MOVE` and `CAM` entries. "Feel" is a set of measurable curves: speed over
time, height over time, camera position over time. Measure them from footage, derive the
parameters with `remake_calc.py`, implement them with the template modules, then compare with
the measurement harness.

## 1. Ground movement

### Measure

From a standing-start clip (side-on, fixed camera), `motion_track.py --analyze speed` reports:

- `steady_speed` (units/s), which becomes `WalkSpeed` or `RunSpeed`;
- `t90`, the time to reach 90% of steady speed;
- the fit of both the **linear** model (constant acceleration) and the **exponential** model
  (`v = V·(1 − e^(−t/τ))`), with residuals. The smaller residual tells you which model the
  original uses.

Repeat for stopping (deceleration), turning around (reversal), and walk-to-run transitions.

### Derive

```bash
python scripts/remake_calc.py accel --top-speed 20 --t90 0.18
# linear ramp: full speed after 0.2 s, acceleration 100 units/s^2
# exponential: tau 0.0782 s (t95 0.2342 s, t99 0.36 s)
```

### Implement

| Need | Implementation |
|---|---|
| Instant start and stop | Humanoid `WalkSpeed` only |
| Ramps on a Humanoid | Template `MovementFeel`: smooths the raw move vector with `MovementMath.approachVector` and calls `Humanoid:Move()` after the default control script each frame (a move-vector magnitude below 1 walks slower than `WalkSpeed`) |
| Ramps with physical friction | `ControllerManager` with `GroundController.AccelerationTime`, `DecelerationTime` and `Friction`; tune `AccelerationTime` until the harness `t90` matches, because the property is documented as an estimate |
| Slow turning | `Humanoid.AutoRotate = false`, then rotate the root toward the move direction at the measured turn rate (degrees per second), or use `ControllerManager.BaseTurnSpeed` |
| Slopes | `Humanoid.MaxSlopeAngle` (0–89°, default 89); measure the steepest walkable slope in the original |
| Step-ups | `Humanoid.HipHeight` and collision geometry; measure step height in studs |

## 2. Jumps

### Measure

`motion_track.py --analyze jump` gives `apex_height`, `rise_time`, `fall_time`, `g_rise`,
`g_fall` and `takeoff_speed`. Also measure:

- a tap jump (shortest possible) to get `min_apex`, which reveals variable jump height;
- the running jump distance, to check air speed;
- terminal fall speed from a long drop (the slope of y(t) once it is linear).

### Derive

For apex height *h*, rise time *t_r* and fall time *t_f*:

- takeoff speed `v0 = 2h / t_r`
- rise gravity `g_r = 2h / t_r²`
- fall gravity `g_f = 2h / t_f²`, so the fall multiplier is `(t_r / t_f)²`
- for a tap jump of height `h_min` with release after `t0` seconds: the release gravity
  multiplier is `m = v1² / (2·g_r·(h_min − h1))`, where `v1 = v0 − g_r·t0` and
  `h1 = v0·t0 − ½·g_r·t0²`

```bash
python scripts/remake_calc.py jump --apex 7.4 --rise-time 0.383 --fall-time 0.300 --min-apex 3.0 --release-time 0.05 --luau
```

### Implement

- Set `Workspace.Gravity = g_r` (server, from `Config.World.Gravity`), `UseJumpPower = false` and
  `JumpHeight = h`. With JumpHeight, Roblox solves the takeoff speed for the current gravity, so
  apex and rise time both match.
- Fall multiplier, release multiplier and fall-speed cap: `MovementFeel` adds a world-space
  `VectorForce` of `mass · g_r · (multiplier − 1)` downward while falling (or rising after an
  early release), and clamps vertical speed at `MaxFallSpeed`.
- **Global gravity also affects every unanchored part.** If the original's props fall at a
  different rate than its character, keep `Workspace.Gravity` physical, and give the character the
  difference with `VectorForce`.

### Assists

| Assist | How to measure | Template field |
|---|---|---|
| Coyote time | Walk off a ledge and press jump at increasing delays; the latest delay that still jumps | `Movement.CoyoteTime` (s) |
| Jump buffer | Press jump just before landing at increasing leads; the earliest lead that still triggers a jump on landing | `Movement.JumpBuffer` (s) |
| Air control | Change direction mid-air; measure lateral acceleration in the air compared with on the ground | `Movement.AirControl` (0–1 multiplier on the ramp rate) |
| Double jump and air jumps | Count and measure the second apex | `Movement.AirJumps`, `Movement.AirJumpApex` |

These need an on-screen input display in the footage. Without one, mark them `ASSUMED` and ask
the user to record a test.

## 3. Camera

### Measure

- FOV and its convention (`footage-analysis.md` §6); convert with `remake_calc.py fov`.
- Rest framing: the character's screen position (fraction of width and height) and height in
  pixels, giving distance and offset.
- Pitch and yaw limits, zoom levels, and zoom speed.
- Lag: from a sudden start or stop, the screen-space error curve, giving overshoot and settle time:

```bash
python scripts/remake_calc.py spring --overshoot 0 --settle-time 0.35
# critically damped: damping ratio 1, angular frequency 16.6657 rad/s (2.6524 Hz)
```

- Collision behavior: does the camera snap in and ease out? Measure both speeds.
- Look-ahead, dead zones, and auto-recenter delay and speed.
- Shake: amplitude (degrees), frequency (Hz) and decay time per event type.

### Implement

`CameraRig` modes:

| Mode | Use |
|---|---|
| `Default` | Keep Roblox cameras (best for VR comfort and maintenance). Only FOV, zoom limits and `Humanoid.CameraOffset` change |
| `Follow` | Third-person orbit: offset, distance, pitch limits, spring-smoothed target, `Spherecast` collision |
| `Fixed` | Authored static shots, like fixed-camera survival horror or menu scenes |
| `Orthographic` | `Camera.ProjectionType` orthographic at a fixed angle and `OrthographicSize`, for isometric and 2D-style games |

Bind custom cameras with `RunService:BindToRenderStep(name, Enum.RenderPriority.Camera.Value + 1, fn)`
and set `CameraType = Scriptable`. When the player is in VR, leave the default VR camera running
unless the original was itself a VR game and the user accepts the comfort trade-offs.

## 4. Impact feel

| Effect | Measure | Implement (client, cosmetic) |
|---|---|---|
| Hit-stop | Frozen frames on hit | Pause tracks with `AdjustSpeed(0)` for N frames, then restore. Never pause server logic |
| Screen shake | Amplitude, frequency, decay | `CameraRig:Shake(amplitudeDeg, frequencyHz, decaySeconds)` |
| FOV kick | ΔFOV and the tween time (sprint, dash, boost) | Tween `FieldOfView` with `Easing` |
| Rumble | Pair with shake events | `Haptics.play("Hit")` |
| Squash and stretch | Scale over frames | Animate `Motor6D.Transform` or the mesh scale, cosmetically |

## 5. Verify

1. Enable the harness in Studio (`Workspace:SetAttribute("RemakeMeasure", true)` before playing,
   or set `Config.DevTools.Measure = true`).
2. Reproduce the reference test: a standing start, one jump, a tap jump, a stop.
3. Copy the Output (or use MCP `get_console_output`) to `remake/logs/run-01.log`.
4. Run `python scripts/measure_compare.py remake/logs/run-01.log --targets remake/targets.json`.
5. Adjust `Config`, re-run, and log each iteration in `remake/diff-log.md`.
