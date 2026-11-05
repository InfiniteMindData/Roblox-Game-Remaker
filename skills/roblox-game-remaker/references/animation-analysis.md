# Animation analysis and recreation

Read this when documenting or rebuilding character, creature, prop or UI animation. Animation
fidelity comes from four things you can measure: **timing** (frames), **spacing** (how
the pose moves between keys), **poses** (joint angles at keys) and **blending** (how clips
transition).

## 1. Inventory every clip

For each character, list every distinct motion you see. One breakdown entry (`ANIM-###`) per
clip:

- locomotion: idle (and idle variants), walk, run, sprint, start, stop, turn-in-place, pivot,
  strafe, backpedal, crouch, slide, swim, climb;
- air: jump takeoff, rise, apex, fall loop, land (soft, hard), double jump, wall jump;
- actions: attacks (each combo step), abilities, interactions (open, pick up), emotes, hurt,
  death, spawn;
- secondary motion: hair, cloth, tails, weapon sway, breathing, blinking, facial expressions;
- props and world: doors, pickups bobbing, enemies, UI icons.

## 2. Measure timing

Use frames extracted at the effective frame rate (check `probe_video.py --dupes` first).

| Quantity | How |
|---|---|
| Cycle length | Frames between identical poses, for example left-foot contact to the next left-foot contact. Measure over 3 or more cycles and average |
| Clip duration | First frame that differs from the previous state to the first frame of the next state |
| Transition (blend) time | Frames from the first sign of the new clip to the first clean frame of it. This becomes the `fadeTime` in `AnimationTrack:Play(fadeTime)` |
| Event timing | Contact frames, hit (active) frames, VFX spawns. These become `KeyframeMarker` names |
| Speed coupling | Does the cycle speed up with movement speed? Measure cycle length at two speeds |

Write all of them as frames at a stated fps, and convert with `remake_calc.py frames`.

## 3. Extract poses

For each clip, mark **keyposes** with the classic breakdown:

- walk and run: contact, down, passing, up (per foot); stride length relative to leg length;
- attacks: anticipation, strike (first active frame), follow-through, recovery;
- jumps: crouch, takeoff, rise, apex, fall, landing compression.

Measure instead of estimating where the joints are visible: track hip, knee, foot (and any
other joints) with `pose_track.py`, which gives per-frame 2D joint angles, the cycle period, and
a keypose table draft:

```bash
python scripts/pose_track.py remake/frames/run01/manifest.json \
  --point hip=412,300 --point knee=420,350 --point foot=414,398 \
  --joint knee=hip,knee,foot --segment thigh=hip,knee --cycle foot.y \
  --table remake/anim/run-keys.md --out remake/tracks/run-pose.json
```

Pick the points with `frame_zoom.py --point`. Use `overlay.py onion` on the cycle's frames to see
the arcs and spacing at a glance.

For joints you cannot track, open the full-resolution frame and estimate the angles relative to
the rest pose. Torso lean, hip and knee flexion, arm swing and head angle carry most of the read. Record
them in a pose table in the breakdown entry:

```text
ANIM-004 run cycle — 20 frames @ 60 fps (MS-031), loop
key  frame  torso_pitch  L_hip  L_knee  R_hip  R_knee  L_shoulder  R_shoulder  root_bob
C-L    0       -12°       +35°    -10°   -25°   -40°      -30°        +35°       -0.15
P-L    5       -10°        0°     -15°   +10°   -95°       0°          0°         0.00
C-R   10       -12°       -25°    -40°   +35°   -10°      +35°        -30°       -0.15
P-R   15       -10°       +10°    -95°    0°    -15°       0°          0°         0.00
```

Angles from 2D footage are estimates. Label them `MEASURED` with ±10° unless the view is
orthogonal to the joint's plane of motion, and cross-check in the Animation Editor against the
reference frame (step 6).

## 4. Rebuild on Roblox

### Choose the rig

- **R15 player characters:** use the standard R15 hierarchy so the default Animate script,
  emotes and layered clothing keep working.
- **Custom characters (creatures, non-humanoids, stylized proportions):** model and rig them in
  Blender (see `blender-pipeline.md`), animate them with an `AnimationController` + `Animator`,
  or with a Humanoid if they need Humanoid physics.
- **Proportions:** match height and limb ratios from the breakdown. Animation read depends
  heavily on proportions, so fix the rig before polishing clips.

### Author the clips

Pick the path by fidelity need and available tools:

1. **Animation Editor (Studio).** Roblox represents the timeline as seconds:frames and runs at
   **30 fps by default**. For 60 fps sources, either key on 30 fps frames and accept ±1 source
   frame, or change the editor frame rate if your Studio version offers it, and record the choice.
   Use the Curve Editor for spacing (easing between keys).
2. **Blender.** Best for complex clips and custom rigs: put the reference footage on a camera
   background or an image-sequence plane, match the camera, and key over it (rotoscoping).
   Export **one animation per FBX** (Roblox imports a single track per file), then import it with
   Animation Editor ⟩ Import ⟩ From FBX Animation.
3. **Animation Capture, Body (beta).** Generates R15 keyframes from an `.mp4` or `.mov` of **one
   real person**, continuous and under 15 s, filmed from a stable camera. Gameplay footage of a game
   character is not a valid input. Use it for reference acting the user records, then clean the
   result against the reference frames.

### Naming and markers

- Name events with `KeyframeMarker`s (for example `FootL`, `FootR`, `Hit`, `VFX_Spawn`) and listen
  with `AnimationTrack:GetMarkerReachedSignal(name)`. `KeyframeReached` is deprecated.
- To replace default character animations, rename the final keyframe `End` (as the docs require for
  default-animation replacements), and swap the `Animate` script's IDs per
  `animation/using` in the Roblox docs.

### Priorities and blending

| Clip type | `AnimationPriority` |
|---|---|
| Idle | `Idle` |
| Locomotion (walk, run, swim, climb) | `Movement` |
| Actions overriding locomotion | `Action`, `Action2`, `Action3`, `Action4` (each overrides the one before) |
| Default/catalog layers | `Core` (lowest) |

- Use the measured transition times as `fadeTime` in `track:Play(fadeTime, weight, speed)` and
  `track:Stop(fadeTime)`.
- Match locomotion cadence to speed with `track:AdjustSpeed(currentSpeed / authoredSpeed)`, where
  `authoredSpeed` is the ground speed the clip was authored for. This prevents foot sliding when
  `WalkSpeed` changes. `assets/rojo-template/src/client/AnimationDriver.luau` implements this.
- Upper-body actions over locomotion: author those clips with only the upper-body joints keyed, so
  lower-priority locomotion keeps driving the legs.

### Root motion

Roblox character clips are effectively in-place: the Humanoid or ControllerManager moves the
root. If the original uses root motion (lunges, rolls, dodges), author the clip in place and
move the character from code with the **measured displacement curve**, synchronized by markers or
`TimePosition`.

## 5. Procedural layers

Many games layer procedural motion on top of clips. Recreate it only where you observe it:

- head and look-at: rotate the `Neck` Motor6D `Transform` after animation, or use IK controls;
- foot planting and slopes: `IKControl` (see `animation/inverse-kinematics` in the docs);
- lean into turns and acceleration tilt: rotate the root joint by a spring-smoothed value;
- breathing and bob: small sinusoidal offsets with measured period and amplitude.

Apply procedural offsets in `RunService.PreSimulation` or after the Animator updates, and keep them
client-side and cosmetic.

## 6. Verify each clip against reference

1. Build a test place, or use the template's `ShotCamera`, to frame the rig like the reference
   (the same side-on or three-quarter view).
2. Play the clip, then capture frames: in-Studio screen recording, or MCP `screen_capture` at
   fixed `TimePosition`s. Set `track:AdjustSpeed(0)` and `track.TimePosition = t` to freeze exact
   poses.
3. Make side-by-side contact sheets of the reference and the recreation at the same key times, and
   compare silhouettes with `visual_compare.py pair --edges-only` (edge IoU).
4. Check the timeline numbers: cycle length, transition frames and marker frames equal the
   breakdown within ±1 source frame.
5. Log the differences in `remake/diff-log.md`, fix the worst, and repeat.

## 7. Common failures

| Symptom | Likely cause | Fix |
|---|---|---|
| Feet slide | Clip cadence not matched to ground speed | `AdjustSpeed` by the speed ratio; re-measure stride |
| Clip plays but legs don't move | An Action-priority clip has the legs keyed, or a higher-priority clip overrides them | Remove leg keys from the action, or lower its priority |
| Snappy transitions | Default `fadeTime` (0.1 s) differs from the original | Use the measured blend times |
| Animation is fine in Studio, wrong in game | Default Animate script overrides it, or the asset is owned by the wrong creator | Set the correct creator (user or group) when publishing; replace through Animate |
| Pose looks right from the side, wrong from the front | Angles estimated from a single view | Get a second reference view; re-key the off-plane rotations |
| Timing off by about 2 frames everywhere | Counted at the 60 fps container on 30 fps content | Re-probe with `--dupes`; recount at the effective fps |
