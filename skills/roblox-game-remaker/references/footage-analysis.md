# Footage analysis, frame by frame

Read this in Phase 2. It turns footage into numbers with stated uncertainty. Run every command
from the skill directory or give scripts their full path. All scripts write only where `--out`
points.

## 0. Ground rules

- Analyze **frames you extracted and opened**, never a video "in general".
- If you cannot view images, say so. Use only numeric outputs (`probe_video`, `motion_track`,
  `visual_compare`, `palette_extract`, `audio_onsets`) and ask the user to confirm visual details.
- Every measurement is written to `remake/measurements.json` with an evidence ID, a method, a
  frame range, a value, a unit and an uncertainty.

## 1. Probe before counting

```bash
python scripts/probe_video.py remake/media/clip.mp4 --dupes --json > remake/probe-clip.json
```

Read from the output:

- `fps_nominal` (container rate) and `vfr`, whether frame deltas vary. If the clip is VFR, use
  per-frame timestamps (`pts_time` in manifests), not `index / fps`.
- `duplicate_ratio` and `effective_fps`. A 60 fps file with about 50% near-duplicate frames is
  30 fps content, so precision is one source frame (33.3 ms), not 16.7 ms. Games that animate
  some elements at lower rates (UI, distant characters) also produce partial duplicates; check
  regions with `--dupes-region`.
- Resolution and display aspect ratio, which you need for FOV and UI work.

**Timing uncertainty rule:** an event observed between frames *i* and *j* lasts
`(j - i) / effective_fps`, ± 1 / effective_fps. Write the ± into the measurement.

## 2. Extract exactly the frames you need

```bash
# every frame of a short window (frame indexes are 0-based source indexes)
python scripts/extract_frames.py clip.mp4 --out remake/frames/jump01 --mode range --start 240 --end 300
# every 10th frame of a long clip, for an overview
python scripts/extract_frames.py clip.mp4 --out remake/frames/overview --mode every --step 10
# scene cuts: UI screen changes, menu transitions, cutscenes
python scripts/extract_frames.py clip.mp4 --out remake/frames/cuts --mode scene --threshold 0.3
# specific timestamps in seconds
python scripts/extract_frames.py clip.mp4 --out remake/frames/hud --mode times --times 12.5,40.0
# crop to a HUD region to keep files small
python scripts/extract_frames.py clip.mp4 --out remake/frames/hp --mode range --start 0 --end 120 --crop 40,980,420,80
```

Each output folder gets `manifest.json` listing `index`, `pts_time` and `file` for every frame.
Files are named `f000240_t4.000000.png`, so frames stay traceable to the source.

## 3. Review sequences with contact sheets

```bash
python scripts/contact_sheet.py remake/frames/jump01/manifest.json --out remake/sheets/jump01.png --cols 8 --scale 0.25
```

Open the sheet and note keyposes and events by frame index: takeoff, apex, landing, contact,
UI start, UI end. Then open the individual full-resolution frames around each event to pin the
exact frame. Write the frame numbers down. Do not rely on memory.

## 4. Event timing

Record events as frame indexes and convert them:

```bash
python scripts/remake_calc.py frames --start 240 --end 263 --fps 60
# -> 23 frames = 0.3833 s ± 0.0167 s
```

Typical events: input to motion start (the latency the footage shows, so input must be visible),
attack startup, active and recovery, dash duration, UI tween duration, respawn time, combo
windows.

## 5. Motion: positions, speeds, jumps

Find and confirm the subject first instead of estimating coordinates from a full frame:

```bash
python scripts/find_mover.py remake/frames/jump01/manifest.json --preview remake/sheets/jump01-movers.png
# -> candidate bbox (first-frame pixels), camera motion, and an --anchor-bbox when the camera pans
python scripts/frame_zoom.py remake/frames/jump01/f000240_t4.000000.png --region 880,580,110,140 --mark 912,604,48,96 --out remake/sheets/check.png
```

Open the zoom and check that the box sits on the feature (rulers are in source-frame pixels).

`motion_track.py` follows a template patch across frames with normalized cross-correlation.

```bash
python scripts/motion_track.py remake/frames/jump01/manifest.json \
  --bbox 912,604,48,96 --search 80 \
  --anchor-bbox 100,900,64,64 \
  --px-per-unit 31.5 --unit studs \
  --analyze jump --out remake/tracks/jump01.json
```

- `--bbox` is the feature on the first frame: a character's head, feet, or a distinctive marking.
- `--anchor-bbox` is a static background feature. Its motion is subtracted to cancel camera pans,
  which only works for translation-like camera motion.
- `--px-per-unit` comes from a known size **at the same depth as the subject**: the
  character's height in pixels divided by its height in studs, or a doorway of known size.
  Without it, results stay in pixels.
- `--analyze jump` fits a parabola to the airborne segment and reports apex height, rise time,
  fall time, gravity estimates (rise and fall separately) and takeoff speed. Unequal rise and
  fall gravities mean the original uses fall-gravity scaling (see `movement-camera-feel.md`).
- `--analyze speed` fits steady-state ground speed and time to reach 90% of it.

**Perspective caution.** Pixel tracking measures image-plane motion. One `--px-per-unit` is only
metric when the motion is roughly parallel to the image plane at a constant camera distance.
Prefer side-on test clips. For third-person or angled footage, convert through the ground plane
instead (§5a). For motion along the view axis, track with `--scale-search`: the reported `scale`
column is the apparent size, and `motion_track` warns when it changes enough to make one
`--px-per-unit` wrong. Record the setup in the measurement method.

### 5a. Third-person footage: the ground plane

When the camera looks down at the ground at an angle, mark four corners of a ground rectangle
whose size you know (a floor tile grid, a road marking, a court, a platform measured elsewhere),
then convert the tracked feet to studs:

```bash
python scripts/motion_track.py remake/frames/run3d/manifest.json --bbox <whole body> --scale-search --out remake/tracks/run3d.json
python scripts/camera_solve.py ground --image 1920x1080 --corners "x,y;x,y;x,y;x,y" --rect 12x12 \
  --track remake/tracks/run3d.json --contact bottom --analyze speed --out remake/tracks/run3d-ground.json
python scripts/ledger.py import remake remake/tracks/run3d-ground.json --evidence EV-00N
```

- Corners go in order around the rectangle: the origin, along the width, the far corner, along
  the depth. Zoom with `frame_zoom.py` to place them; every corner pixel moves the result, and the
  reported uncertainty is the effect of moving each corner coordinate by 1 px.
- `--contact bottom` uses the bottom of the tracked box (scaled per frame by `--scale-search`) as
  the ground contact. Use `--contact center` only for a feature that lies on the ground, such as
  a shadow.
- The homography needs a static camera. With a follow camera, measure each stretch where the
  camera holds still, or re-mark the corners per shot.
- If the source track has low-score samples, `camera_solve` withholds the measurements. Fix the
  track (smaller box, `--scale-search`, a shorter range) instead of importing a wrong number.

**Cross-check.** Speed = stride length × cadence. If the walk cycle is 30 frames at 60 fps and
covers 2 strides of 1.4 m, then 2.8 m in 0.5 s = 5.6 m/s (20 studs/s). A large mismatch with the
tracked speed suggests foot sliding in the original, or a measurement error.

## 6. Camera analysis

- **FOV.** If the game states FOV, record its convention (horizontal or vertical, and the aspect
  it applies to), and convert with `remake_calc.py fov`. Otherwise solve it from the footage with
  `camera_solve.py`, which reports vertical FOV (Roblox's convention) with an uncertainty:
  - `vanishing`: mark two or more lines along each of two perpendicular ground directions (floor
    seams, wall bases, road edges; `--lines-x`, `--lines-z`), optionally vertical edges
    (`--lines-y`). It also gives pitch and roll, and camera height with `--known-height` (a vertical
    object of known height standing on the ground) or `--known-ground` (two ground points a known
    distance apart). Long lines that converge strongly give the tightest result.
  - `size`: an object of known size at a known depth: `--span x1,y1,x2,y2 --size 5 --distance 20`.
  The solver assumes square pixels and a centered principal point: use uncropped frames.
- **Follow distance and offset.** Solve the camera height and pitch first (above), then measure
  where the character sits on screen (as a fraction of width and height) while idle. With FOV,
  pitch and height known, the distance to the character's feet comes from the ground-plane ray
  (`camera_solve.py ground --points`).
- **Lag and damping.** From a sudden stop or start, track the character's screen position until
  it settles. The overshoot and settle time give spring parameters
  (`remake_calc.py spring --overshoot 0.08 --settle-time 0.35`).
- **Shake.** Track a static background feature during shakes: amplitude in pixels converts to
  degrees, and the frequency comes from zero crossings.

## 7. UI capture

- Use frames at native resolution. Note the reference resolution: all UI math is relative to it.
- Record element boxes in pixels in a JSON file and convert them with `ui_measure.py` (see
  `ui-recreation.md`).
- Sample colors with `palette_extract.py --region`. Sample flat areas, not anti-aliased edges.
- Time UI tweens by frame range. Identify the easing from the per-frame progress of position,
  scale or alpha with `fit_curve.py` (track the element first); do not name a curve by eye.

## 8. Colors and lighting reference

- Sample sky, fog, shadowed and lit surfaces, and skin tones with `palette_extract.py`.
- Note the time of day and sun direction from shadow direction and length (see
  `graphics-lighting.md`).
- Encodes are lossy: sample a 5×5 region or larger, and average across frames.

## 9. Audio timing

```bash
python scripts/audio_onsets.py clip.mp4 --fps 60 --out remake/audio/clip-onsets.json
```

This gives onset times and the nearest frame index. Use it to align footsteps with animation
contact frames, hit sounds with active frames, and UI sounds with tweens. Record cue durations
and loudness relationships (loud versus quiet) qualitatively unless you calibrate them.

## 10. Recording measurements

Import tracker results directly (IDs, uncertainty and frame range are filled in):

```bash
python scripts/ledger.py import remake remake/tracks/jump01.json --evidence EV-007
```

For other values use `ledger.py add-measurement`. The resulting entry looks like this:

```json
{
  "id": "MS-014",
  "what": "jump apex height (standing jump)",
  "evidence": ["EV-007"],
  "method": "motion_track jump fit, frames 240-300, feet bbox, side-on, px_per_unit from character height 5.0 studs",
  "value": 7.4,
  "uncertainty": 0.3,
  "unit": "studs",
  "frames": [240, 300]
}
```

Then cite `MS-014` in the breakdown entry that uses it.
