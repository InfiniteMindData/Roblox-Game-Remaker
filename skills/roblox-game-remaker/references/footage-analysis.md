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

**Perspective caution.** Pixel tracking measures image-plane motion. It is only metric when the
motion is roughly parallel to the image plane and the camera distance is constant. Prefer
side-on test clips. For motion along the view axis, measure apparent size change, or use a
top-down or orthographic shot. Record the setup in the measurement method.

**Cross-check.** Speed = stride length × cadence. If the walk cycle is 30 frames at 60 fps and
covers 2 strides of 1.4 m, then 2.8 m in 0.5 s = 5.6 m/s (20 studs/s). A large mismatch with the
tracked speed suggests foot sliding in the original, or a measurement error.

## 6. Camera analysis

- **FOV.** If the game states FOV, record its convention (horizontal or vertical, and the aspect
  it applies to). Otherwise estimate it from geometry: an object of known width W at distance D
  spans p pixels of a frame P pixels wide, so `hfov = 2·atan((W/2)/D · P/p)`. Convert with
  `remake_calc.py fov`.
- **Follow distance and offset.** Measure where the character sits on screen (as a fraction of
  width and height) while idle, and its size in pixels. Together with the FOV, this gives the
  distance.
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
- Time UI tweens by frame range. Estimate easing from the per-frame progress of position or
  alpha: track the element and look at the progress curve shape (linear, quad-out, back-out,
  and so on).

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
python scripts/ledger.py import-track remake remake/tracks/jump01.json --evidence EV-007
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
