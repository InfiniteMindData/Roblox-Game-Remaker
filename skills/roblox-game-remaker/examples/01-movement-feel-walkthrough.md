# Walkthrough: matching jump and run feel

Goal: make the remake's standing jump and run start match the reference within Tier A. The
reference here is the synthetic demo footage (fictional game "Lantern Hop", rights mode own IP),
so every number below can be reproduced with `bash examples/demo/run_demo.sh /tmp/remake-demo`.
The outputs shown are real outputs of the bundled scripts on that footage.

## 1. Probe before measuring

```bash
python scripts/probe_video.py remake/media/demo_jump.mkv --dupes
```

```text
fps nominal:      60.0  (r_frame_rate 60.0, avg 60.0)
variable rate:    no
duplicates:       39/79 pairs (49.4%), runs {'1': 1, '12': 1, '26': 1}
effective fps:    30.75  (timing precision ±32.52 ms)
WARNING: 49% near-duplicate frames: content updates at about 30.75 fps; count timings at that rate.
WARNING: Very little motion in the analyzed area: duplicate detection is unreliable; use --dupes-region on a moving element such as the character.
```

Read it critically. The run histogram shows two long runs (12 and 26 frames): the character
stands still before takeoff and after landing. These are real static frames, not a 30 fps
encode, so the clip is true 60 fps while the character moves. Confirm by probing only the
airborne window or the character region (`--dupes-region`), and record the conclusion in the
evidence entry.

## 2. Extract and review

```bash
python scripts/extract_frames.py remake/media/demo_jump.mkv --out remake/frames/jump01 --mode all
python scripts/contact_sheet.py remake/frames/jump01/manifest.json --out remake/sheets/jump01.png --cols 10 --scale 0.2 --every 2
```

Open the sheet, find the takeoff and landing, then open the full frames around them.

## 3. Track the jump

The scale comes from a known size at the subject's depth: here 20 px per stud.

```bash
python scripts/motion_track.py remake/frames/jump01/manifest.json --bbox 288,288,24,24 \
  --px-per-unit 20 --analyze jump --out remake/tracks/jump01.json
```

```text
  method: piecewise
  apex_height: 8.0049
  rise_time_s: 0.4015
  fall_time_s: 0.2835
  g_rise: 99.4067
  g_fall: 198.9872
  takeoff_speed: 39.9082
  gravity_single_fit: 134.5198
  fall_gravity_multiplier: 2.0017
  asymmetric: True
```

The ground truth is apex 8, rise 0.4 s, fall 0.283 s, and gravities of 100 and 200. Note
`gravity_single_fit` (134.5): one parabola through an asymmetric jump gives a gravity that
matches neither phase. That is why the tool fits rise and fall separately.

## 4. Track the run start (with a panning camera)

```bash
python scripts/motion_track.py remake/frames/run01/manifest.json --bbox 90,200,20,20 \
  --anchor-bbox 400,20,40,40 --search 40 --px-per-unit 20 --analyze speed
```

```text
  motion_start_s: 0.199
  steady_speed: 19.9956
  t90_s: 0.2269
  linear_ramp: {'start_s': 0.199, 'time_to_full_s': 0.2521, 'acceleration': 79.3213, 'rms': 0.00893}
  exponential: {'start_s': 0.2479, 'tau_s': 0.0781, 'rms': 0.04779}
  preferred_model: linear_ramp
```

`--anchor-bbox` tracks a static background patch and subtracts its motion, which cancels the
60 px/s camera pan. The linear model fits five times better than the exponential one, so the
original ramps speed linearly over about 0.25 s.

## 5. Record measurements and breakdown entries

Add `MS-001` to `MS-005` to `remake/measurements.json` and the `MOVE-001` and `MOVE-002`
entries to the breakdown. See `04-sample-workspace/remake/` for the exact entries.

## 6. Convert to Roblox settings

```bash
python scripts/remake_calc.py jump --apex 8.0 --rise-time 0.4 --fall-time 0.2828 --luau
python scripts/remake_calc.py accel --top-speed 20 --t90 0.225 --luau
```

```text
Roblox: Workspace.Gravity = 100; StarterPlayer.CharacterUseJumpPower = false; CharacterJumpHeight = 8 (equivalent JumpPower 40)
Asymmetric jump: use MovementFeel FallGravityMultiplier (extra downward VectorForce while falling).
Gravity = 100.000, -- rise gravity (studs/s^2)
JumpApex = 8.000,
FallGravityMultiplier = 2.0006,
AccelerationTime = 0.2500, -- linear ramp duration (s)
```

Put these values into `src/shared/Remake/Config.luau`, with the measurement IDs:

```lua
Config.World = { StudsPerMeter = 5.0 / 1.4, Gravity = 100 } -- MS-001/MS-002 via remake_calc jump
Config.Movement.WalkSpeed = 20 -- MS-004 (19.996 ± 0.1)
Config.Movement.AccelerationTime = 0.25 -- MS-005 (linear model)
Config.Movement.JumpApex = 8.0 -- MS-001
Config.Movement.FallGravityMultiplier = 2.0 -- MS-002/MS-003
```

## 7. Verify in Studio

1. `Workspace:SetAttribute("RemakeMeasure", true)` in the command bar, then Play.
2. Stand still, hold forward for 2 s, release, then jump once from standing.
3. Copy the Output to `remake/logs/run-01.log` (with MCP, use `get_console_output`).
4. Compare:

```bash
python scripts/measure_compare.py remake/logs/run-01.log --targets remake/targets.json
```

Each metric reports PASS or FAIL against its target and tolerance. Log the iteration in
`remake/diff-log.md`. If `jump_apex` is high and the rise is long, gravity is too low; if only
the fall is slow, raise `FallGravityMultiplier`.

## What this example does not show

The demo subject is a rigid square, so it has no animation to measure (see `ANIM-001` in the
sample breakdown, which is honestly marked `UNKNOWN`). Real footage needs the animation
workflow in `references/animation-analysis.md`.
