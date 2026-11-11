# Recipes: exact command sequences

Load this instead of several references when the task matches a recipe. Paths are relative
to the skill directory; `remake/` is the user's workspace and `clip.mp4` stands for their
footage. Each recipe ends with a "done when" check. When a step needs judgment, the recipe names
the reference to read.

## 1. Start a remake (first session)

```bash
python scripts/doctor.py
python scripts/breakdown_init.py . --game "Game Name" --version 1.0 --platform "PC, gamepad"
python scripts/remake_status.py remake --write
```

Then fill `remake/00-intake.md` with the user (rights mode, slice, devices, tier), record the
first sources, and optionally seed `Config.luau` with a genre preset:

```bash
python scripts/ledger.py add-evidence remake --type video --title "Level 1 run" --source remake/media/clip.mp4
python scripts/preset.py list
python scripts/preset.py apply platformer --config src/shared/Remake/Config.luau --in-place
```

Done when `remake_status.py` shows phase 0 as pass.

## 2. Resume (every later session)

```bash
python scripts/remake_status.py remake --write
```

Read `remake/STATUS.md`, do its next action, and run it again afterwards.

## 3. Match a jump

```bash
python scripts/probe_video.py clip.mp4 --dupes
python scripts/extract_frames.py clip.mp4 --out remake/frames/jump01 --mode range --start 240 --end 320
python scripts/find_mover.py remake/frames/jump01/manifest.json --preview remake/sheets/jump01-movers.png
python scripts/frame_zoom.py remake/frames/jump01/<first frame>.png --region <around the box> --mark <bbox> --out remake/sheets/jump01-check.png
python scripts/motion_track.py remake/frames/jump01/manifest.json --bbox <bbox> --px-per-unit <px per stud> --analyze jump --out remake/tracks/jump01.json
python scripts/ledger.py import remake remake/tracks/jump01.json --evidence EV-00N
python scripts/remake_calc.py jump --apex <apex> --rise-time <rise> --fall-time <fall> --luau
```

Get `--px-per-unit` from `remake_calc.py scale --pixels <character height px> --size <height in studs>`.
Put the values in Config (`Gravity`, `JumpApex`, `FallGravityMultiplier`) with `Config.Evidence`
entries, then:

```bash
python scripts/config_check.py remake
python scripts/ledger.py targets remake --tier A
python scripts/measure_compare.py remake/logs/run-01.log --targets remake/targets.json
```

Done when `jump_apex`, `jump_rise_time` and `jump_fall_time` pass.

## 4. Match ground movement

Use a side-on standing-start clip (and a stop clip for deceleration). Run the same commands as
recipe 3, with `--analyze speed`. Add `--anchor-bbox` from `find_mover.py` when the camera pans.

```bash
python scripts/remake_calc.py accel --top-speed <steady_speed> --t90 <t90> --luau
```

Use `AccelerationTime` (linear model) in `Config.Movement`. Done when `ground_speed` and
`accel_t90` pass in `measure_compare.py`.

## 5. Match camera FOV and follow

1. Find the FOV convention (`roblox-translation.md` §2), then convert it:
   `python scripts/remake_calc.py fov --horizontal 90 --aspect 16:9`. If the game does not state
   it, solve it from a frame (recipe 13): `camera_solve.py vanishing` also gives pitch and height.
2. Lag: track the character's screen position after a sudden start (`motion_track.py` without
   `--px-per-unit`), read the overshoot and settle time, then
   `python scripts/remake_calc.py spring --overshoot <frac> --settle-time <s> --luau`.
3. Set `Config.Camera` (`FieldOfView`, `Distance`, `PivotOffset`, `FollowFrequency`, `FollowDamping`).
4. Verify with a matched shot (recipe 7) and `overlay.py checker` for alignment.

## 6. Recreate a HUD screen

```bash
python scripts/frame_zoom.py hud.png --region 0,940,520,140 --scale 3 --out remake/ui/zoom-health.png
python scripts/palette_extract.py hud.png --region <bar fill> --k 2
python scripts/ui_measure.py remake/ui/hud-boxes.json --luau > remake/ui/HudLayout.luau
```

Build the ScreenGui with the generated values, set the attribute `RemakeScaleUI = true`, capture at
the reference resolution, then:

```bash
python scripts/visual_compare.py pair hud.png remake/captures/hud.png --out remake/diff/hud
python scripts/ui_measure.py --compare remake/ui/hud-boxes.json remake/ui/hud-boxes-rec.json --tolerance 0.5
```

Done when every element is within tolerance at both aspect ratios (`ui-recreation.md`).

## 7. Match lighting and color for a shot

```bash
python scripts/studio_snippets.py apply-shot remake/shots.json --id SHOT-03     # run with execute_luau (Client)
python scripts/visual_compare.py pair remake/frames/ref/shot03.png remake/captures/SHOT-03.png --out remake/diff/shot03
python scripts/overlay.py checker remake/frames/ref/shot03.png remake/captures/SHOT-03.png --out remake/diff/shot03/checker.png
```

Align first (edge IoU, checker), then follow the `lab_shift` hints in `graphics-lighting.md` §3:
change one property group per iteration and log it in `diff-log.md`. Batch all shots with
`visual_compare.py batch remake/shots.json --out remake/diff`.

## 8. Recreate an animation cycle

```bash
python scripts/extract_frames.py clip.mp4 --out remake/frames/run-cycle --mode range --start <a> --end <b>
python scripts/overlay.py onion remake/frames/run-cycle/manifest.json --every 2 --out remake/sheets/run-onion.png
python scripts/pose_track.py remake/frames/run-cycle/manifest.json --point hip=x,y --point knee=x,y --point foot=x,y \
  --joint knee=hip,knee,foot --segment thigh=hip,knee --cycle foot.y --table remake/anim/run-keys.md
```

Key the clip in Blender or the Animation Editor from the table (`animation-analysis.md`), set
`AuthoredSpeed` to the measured ground speed, and compare frozen poses with
`visual_compare.py pair --edges-only`.

## 9. Build the level greybox from a metric map

Write `remake/layout-level1.json` from the `ENV` entry (sizes and positions in meters or studs), then:

```bash
python scripts/studio_snippets.py greybox remake/layout-level1.json --studs-per-meter 3.5714 --out remake/greybox-level1.luau
```

Run it with MCP `execute_luau` (Edit), or paste it into the command bar. Playtest the gaps with
the measured jump. Done when every gap is clearable as in the original and none is clearable
without the intended move.

## 10. Verify a Quest 3 control scheme and haptics

1. Set `Config.DevTools.InputProbe = true` and publish to a private test place.
2. On the headset, press every control. Copy the Output, then:

```bash
python scripts/studio_snippets.py extract-log console.txt --out remake/logs/quest-probe.log
python scripts/studio_snippets.py inputs remake/logs/quest-probe.log --out remake/ui/quest-bindings.md
python scripts/ledger.py add-evidence remake --type capture --title "Quest 3 InputProbe log" --source remake/logs/quest-probe.log --analysis "studio_snippets inputs"
```

3. Calibrate `Config.Haptics.SidePositions` (`vr-quest.md` §5). Done when every `VR-###` binding
   cites the probe log.

## 11. Footage you cannot access

```bash
python scripts/ledger.py add-evidence remake --type video --title "<what it was>" --source <url> --inaccessible --notes "<error>"
```

Tell the user plainly that you could not open it, give the capture guide
(`research-protocol.md` §5), and mark the dependent entries `UNKNOWN` with an `open:` question.

## 12. Before delivery

```bash
python scripts/breakdown_check.py remake --strict
python scripts/config_check.py remake --strict
python scripts/visual_compare.py batch remake/shots.json --out remake/diff
python scripts/measure_compare.py remake/logs/<latest>.log --targets remake/targets.json
python scripts/fidelity_report.py remake --label "delivery check"
python scripts/remake_status.py remake --write
```

Fill `remake/delivery-report.md` from these outputs and `remake/scorecard.md`, using the verification labels
(`verification-loop.md` §6).

## 13. Solve the camera and measure third-person footage

For a camera that looks down at an angle, where one pixels-per-stud scale is wrong.

```bash
python scripts/extract_frames.py clip.mp4 --out remake/frames/cam01 --mode range --start <a> --end <b>
python scripts/frame_zoom.py remake/frames/cam01/<first frame>.png --region <around a ground rectangle> --scale 4 --out remake/sheets/cam01-corners.png
python scripts/camera_solve.py vanishing --image 1920x1080 --lines-x "<x1,y1,x2,y2;...>" --lines-z "<...>" \
  --known-height <base_x,base_y,top_x,top_y,height> --luau --out remake/camera/cam01.json
python scripts/find_mover.py remake/frames/cam01/manifest.json
python scripts/motion_track.py remake/frames/cam01/manifest.json --bbox <whole body> --scale-search --out remake/tracks/cam01.json
python scripts/camera_solve.py ground --image 1920x1080 --corners "<x,y;x,y;x,y;x,y>" --rect <W>x<D> \
  --track remake/tracks/cam01.json --contact bottom --analyze speed --out remake/tracks/cam01-ground.json
python scripts/ledger.py import remake remake/camera/cam01.json --evidence EV-00N
python scripts/ledger.py import remake remake/tracks/cam01-ground.json --evidence EV-00N
```

Mark at least two long lines per ground direction (floor seams, wall bases, road edges) and a
vertical object or a ground distance of known size for the height. Put `camera_vfov` and
`camera_pitch` in `Config.Camera` (`FieldOfView`, `StartPitchDeg`) with their `MS` IDs. Done when
the solved camera reproduces the reference shot within its stated uncertainty
(`visual_compare.py` edge IoU), and `ground_speed` imports with no warnings. When `camera_solve`
withholds measurements, fix the track first (`footage-analysis.md` §5a).

## 14. Compare a recording of the build with the reference clip

After a jump or run passes `measure_compare`, check the whole motion over time.

```bash
python scripts/clip_compare.py remake/tracks/jump01.json remake/logs/run-05.log --targets remake/targets.json \
  --out remake/diff/jump01-it5/clip.json --plot remake/diff/jump01-it5/clip.png
```

The harness log is in studs, so the reference track needs `--px-per-unit` (or a `camera_solve
ground` conversion). To compare two videos instead (a screen recording of the build against the
reference), extract both and pass the manifests:

```bash
python scripts/clip_compare.py remake/frames/jump01/manifest.json remake/frames/build-jump/manifest.json \
  --ref-bbox <x,y,w,h> --rec-bbox <x,y,w,h> --ref-px-per-unit <ref px/stud> --rec-px-per-unit <build px/stud> \
  --align frames --ref-frame <takeoff frame> --rec-frame <takeoff frame> --plot remake/diff/jump01-video.png
```

Open the plot: a constant `bias` points at scale (speed, height), a growing error at timing (ramp,
gravity). Done when `clip_compare` exits 0 at the agreed tier and the result is logged in
`diff-log.md`.

## 15. Identify a UI tween, camera ease or acceleration ramp

```bash
python scripts/extract_frames.py clip.mp4 --out remake/frames/menu-open --mode range --start <a> --end <b>
python scripts/motion_track.py remake/frames/menu-open/manifest.json --bbox <panel edge> --out remake/tracks/menu-open.json
python scripts/fit_curve.py --track remake/tracks/menu-open.json --field x_px --plot remake/ui/menu-open-fit.png --luau --out remake/ui/menu-open-fit.json
python scripts/ledger.py import remake remake/ui/menu-open-fit.json --evidence EV-00N
```

Use `--field scale` (with `motion_track --scale-search`) for pop-ins, `y_px` for slides, and the
camera's screen-space track for follow lag. Trim to one transition with `--window`. Read the
warnings: "NOT DISTINGUISHABLE" means the footage cannot tell the listed curves apart, so record
them all in the breakdown entry's notes, pick by intent, and do not call the choice `MEASURED`
beyond its duration. Done when the chosen curve's `TweenInfo` or `Spring` values sit in Config or
the UI module with the `MS` ID.

## 16. Score an iteration and catch regressions

After every change in Phase 6 (one subsystem at a time):

```bash
python scripts/visual_compare.py batch remake/shots.json --out remake/diff/it08
python scripts/clip_compare.py remake/tracks/jump01.json remake/logs/run-08.log --targets remake/targets.json --clip jump01 \
  --out remake/diff/it08/clip-jump01.json --plot remake/diff/it08/clip-jump01.png
python scripts/fidelity_report.py remake --diff-log --label "it8: FallGravityMultiplier 1.8 -> 2.0"
```

`fidelity_report` exits 1 on a regression and lists it in `remake/scorecard.md`; revert or fix the
change before the next one. Done when the scorecard shows every judged system passing (or the
user has accepted the listed gaps) and the last iteration has no regression.

## 17. Measure a spawn timer, a drop rate or an enemy's behavior

Read `systems-analysis.md` first. Log every event in the range into `remake/systems/<name>.csv`
(`frame,event,entity,...`), then:

```bash
python scripts/event_stats.py remake/systems/wave1.csv --fps 60 --intervals spawn --by entity --out remake/systems/wave1.json
python scripts/event_stats.py remake/systems/loot.csv --fps 60 --rate drop/kill --plan-halfwidth 0.05 --out remake/systems/loot.json
python scripts/event_stats.py remake/systems/boss.csv --fps 60 --states idle,windup,attack,recover --by entity --out remake/systems/boss.json
python scripts/ledger.py import remake remake/systems/loot.json --evidence EV-00N
```

Write rates as intervals in the breakdown and tell the user how many more trials would narrow
them (`trials_needed`). Done when every `AI`/`SYS` timer, rate and state in the slice cites an
`MS` ID, and each wide interval is either narrowed with more footage or flagged `ASSUMED`.

## 18. Match a sound effect with an original or licensed replacement

```bash
python scripts/audio_onsets.py clip.mp4 --fps 60 --start 12 --end 14
python scripts/audio_compare.py analyze clip.mp4 --start <onset - 0.05> --end <onset + 0.6> --out remake/audio/jump-ref.json --plot remake/audio/jump-ref.png
python scripts/audio_compare.py compare clip.mp4 remake/audio/jump-new.wav --ref-start <onset - 0.05> --ref-end <onset + 0.6> --plot remake/audio/jump-cmp.png
```

The replacement is your own or licensed sound (`rights-and-policy.md`); the tool tunes it, it does
not copy the reference. Apply the hints (edit the attack and decay for envelope shape, then
`PlaybackSpeed` or `AudioPitchShifter.Pitch` for pitch, `AudioPlayer.Volume` for level), export,
and compare again. Done when `audio_compare compare` exits 0, or the remaining differences are
listed as intentional in the `AUD` entry.

