# Game breakdown: Lantern Hop (1.4.2) — sample

> Illustrative sample for a fictional game; measured values come from the synthetic demo
> footage (`examples/demo/`). Validate with
> `python scripts/breakdown_check.py examples/04-sample-workspace/remake --strict`.

## Coverage
- n/a: SYS (save system and settings are outside the vertical slice, agreed in intake)

## Controls

### CTRL-001: Core bindings
- status: VERIFIED
- priority: P0
- evidence: EV-002
- roblox: InputContext PlayContext (Priority 2000, Sink) with InputActions Move (Direction2D: WASD, Thumbstick1, touch thumbstick), Jump (Bool: Space, ButtonA, touch button), Look (Direction2D: mouse delta, Thumbstick2); Workspace.PlayerScriptsUseInputActionSystem = Enabled
- accept: Controller Emulator and keyboard each trigger Move, Jump and Look; InputProbe log saved as evidence
- notes: Gamepad A = jump, left stick = move, right stick = camera (design doc §2).

### CTRL-002: Coyote time and jump buffer
- status: VERIFIED
- priority: P0
- evidence: EV-002
- value: coyote_time = 0.100 ± 0.017 s
- value: jump_buffer = 0.067 ± 0.017 s
- roblox: Config.Movement.CoyoteTime = 0.1, JumpBuffer = 0.067 (MovementFeel + MovementMath.JumpAssist)
- accept: walking off a ledge and pressing jump after 5 frames jumps, after 7 frames does not; press 3 frames before landing jumps on landing
- depends: MOVE-002

## Movement and physics

### MOVE-001: Ground run
- status: MEASURED
- priority: P0
- evidence: EV-004, MS-004, MS-005
- value: run_speed = 19.996 ± 0.1 studs/s
- value: ramp_time = 0.252 ± 0.017 s
- roblox: Config.Movement.WalkSpeed = 20, AccelerationTime = 0.25 (linear model preferred: rms 0.009 vs 0.048)
- accept: measure_compare ground_speed within ±7% and accel_t90 within ±2 frames (0.033 s)

### MOVE-002: Standing jump
- status: MEASURED
- priority: P0
- evidence: EV-003, MS-001, MS-002, MS-003
- value: apex_height = 8.005 ± 0.05 studs
- value: rise_time = 0.4015 ± 0.017 s
- value: fall_time = 0.2835 ± 0.017 s
- roblox: Config.World.Gravity = 100 (rise gravity), Movement.JumpApex = 8.0, FallGravityMultiplier = 2.0 (remake_calc.py jump)
- accept: measure_compare jump_apex within ±0.3 studs; jump_rise_time and jump_fall_time within ±2 frames
- notes: Falls twice as hard as it rises; Workspace.Gravity stays at the rise value so props fall normally.

### MOVE-003: Deceleration when the stick is released
- status: UNKNOWN
- priority: P1
- roblox: DecelerationTime = 0 (instant) until measured
- accept: measure_compare decel_t10 within ±1 frame of the measured value
- open: No stopping clip exists. Ask the user for a side-on clip of releasing the stick at full speed.

## Camera

### CAM-001: Gameplay FOV
- status: VERIFIED
- priority: P0
- evidence: EV-002
- value: fov_vertical = 58.716 ± 0.01 deg
- roblox: Config.Camera.FieldOfView = 58.7155 (90° horizontal at 16:9 converted with remake_calc.py fov; the game is Hor+)
- accept: SHOT-HUD edge IoU ≥ 0.6 at the same camera position; FOV value matches the conversion

### CAM-002: Camera follow lag
- status: OBSERVED
- priority: P1
- evidence: EV-004
- roblox: CameraRig Follow mode; FollowFrequency 16.67 and FollowDamping 1.0 as starting values, then the output of remake_calc.py spring once measured
- accept: screen-space lag curve after a run start matches the reference within 10% overshoot and ±2 frames settle time
- notes: The camera pans behind the hero at the run start (frames 12-30); not yet quantified.

## Mechanics and rules

### MECH-001: Lantern pickups
- status: VERIFIED
- priority: P0
- evidence: EV-002
- value: pickup_radius = 1.5 ± 0.05 studs
- roblox: Server script: CollectionService tag Lantern; per-Heartbeat distance check to each character's root; +1 score in leaderstats; pickup VFX fired to the collecting client
- accept: pickup at 1.4 studs succeeds and at 1.6 studs does not (Server & Clients, 2 clients)

## Characters

### CHAR-001: Hero proportions
- status: VERIFIED
- priority: P0
- evidence: EV-001, EV-002
- value: hero_height = 5.0 ± 0.05 studs
- roblox: Custom R15 body from Blender (blender_roblox_export.py --r15); character-relative scale 5.0 studs = 1.4 m
- accept: imported rig bounding-box height 5.0 ± 0.05 studs; silhouette edge IoU ≥ 0.7 against the turnaround sheet

## Animations

### ANIM-001: Run cycle
- status: UNKNOWN
- priority: P0
- roblox: R15 run clip (AnimationDriver Run, AuthoredSpeed = 20) authored in Blender once timing is known
- accept: cycle length within ±1 frame; no foot sliding at 20 studs/s (AdjustSpeed ratio 1.0)
- open: The demo footage shows a rigid marker, so the cycle cannot be measured. Needs a side-on clip of the real hero running.

## UI

### UI-001: HUD health bar
- status: MEASURED
- priority: P0
- evidence: EV-005, MS-006, MS-007
- value: bar_width = 420 ± 1 px
- roblox: ScreenGui HUD with RemakeScaleUI attribute; HealthBar AnchorPoint (0, 1), Position UDim2.new(0, 48, 1, -64), Size UDim2.fromOffset(420, 36) from ui_measure.py; fill Color3.fromRGB(200, 40, 50)
- accept: ui_measure.py --compare within 0.5% of screen; delta E ≤ 3 on the bar region

## Environment

### ENV-001: Level 1-1 greybox
- status: INFERRED
- priority: P0
- evidence: EV-002, MS-001
- roblox: Level_Greybox folder of anchored Parts built by an execute_luau script from the design-doc metric map; widest gap sized from the measured jump
- accept: every gap clearable with the measured jump and none clearable without running; dimensions within ±2% of the map
- notes: Gap widths are inferred from the jump arc and the map's grid, not measured in footage.

## Visual effects

### VFX-001: Lantern pickup sparkle
- status: UNKNOWN
- priority: P2
- roblox: ParticleEmitter burst on the client when MECH-001 fires; parameters from footage once captured
- accept: lifetime and count within 10% of the reference frames
- open: No footage of a pickup yet. Ask for a close-up clip at 60 fps.

## Audio

### AUD-001: Jump sound
- status: UNKNOWN
- priority: P2
- roblox: AudioPlayer on the character, played on the Humanoid Jumping state; original sound asset (own IP files from the studio)
- accept: audio_onsets.py onset within 1 frame of takeoff in a recording of the remake
- open: Need the studio's source audio file and a reference clip with sound.

## AI

### AI-001: Moth enemy patrol
- status: UNKNOWN
- priority: P1
- roblox: Server-side StateMachine (Patrol, Chase, Return) with PathfindingService
- accept: patrol loop period and chase trigger range within 5% of the reference
- open: The only source found (EV-006, a speedrun video) was inaccessible, so nothing was analyzed. Ask the user for a clip of one full patrol loop.

## VR

### VR-001: Quest 3 controls
- status: UNKNOWN
- priority: P1
- roblox: Same InputActions as CTRL-001 with Touch controller bindings; HapticEffect GameplayCollision on landing
- accept: InputProbe log from a Quest 3 shows each binding firing; 72 fps or better in level 1-1
- open: Controller mapping must be verified on a headset with DevTools/InputProbe.

## Summary

Run `python scripts/breakdown_check.py examples/04-sample-workspace/remake --strict`; it reports
16 entries (VERIFIED 5, MEASURED 3, OBSERVED 1, INFERRED 1, UNKNOWN 6), 6 open questions and no
assumptions.
