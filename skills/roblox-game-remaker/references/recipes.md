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
python scripts/ledger.py import-track remake remake/tracks/jump01.json --evidence EV-00N
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
   `python scripts/remake_calc.py fov --horizontal 90 --aspect 16:9`.
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
python scripts/remake_status.py remake --write
```

Fill `remake/delivery-report.md` from these outputs, using the verification labels
(`verification-loop.md` §6).
