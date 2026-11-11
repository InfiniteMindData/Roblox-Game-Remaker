#!/usr/bin/env bash
# End-to-end rehearsal of the measurement pipeline on synthetic footage with known answers.
# Usage: bash examples/demo/run_demo.sh /tmp/remake-demo
# Run from the skill directory (the folder that contains SKILL.md).
set -euo pipefail

OUT="${1:?usage: run_demo.sh OUTPUT_DIR (a new or empty directory)}"
SKILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
S="$SKILL/scripts"
mkdir -p "$OUT"

python3 "$SKILL/examples/demo/make_demo_footage.py" --out "$OUT"

echo "== probe"
python3 "$S/probe_video.py" "$OUT/demo_jump.mkv" --dupes

echo "== extract every frame of both clips"
python3 "$S/extract_frames.py" "$OUT/demo_jump.mkv" --out "$OUT/frames_jump" --mode all --overwrite
python3 "$S/extract_frames.py" "$OUT/demo_run.mkv" --out "$OUT/frames_run" --mode all --overwrite
python3 "$S/contact_sheet.py" "$OUT/frames_jump/manifest.json" --out "$OUT/sheet_jump.png" --cols 10 --scale 0.2 --every 2

echo "== jump (truth: apex 8, rise 0.4 s, fall 0.283 s, g_rise 100, g_fall 200)"
python3 "$S/motion_track.py" "$OUT/frames_jump/manifest.json" --bbox 288,288,24,24 \
  --px-per-unit 20 --analyze jump --out "$OUT/track_jump.json"

echo "== run on a panning camera (truth: 20 studs/s, linear ramp 0.25 s, t90 0.225 s)"
python3 "$S/motion_track.py" "$OUT/frames_run/manifest.json" --bbox 90,200,20,20 \
  --anchor-bbox 400,20,40,40 --search 40 --px-per-unit 20 --analyze speed --out "$OUT/track_run.json"

echo "== third-person clip: camera and ground plane (truth: vFOV 60, pitch -35, height 9, 10 studs/s, t90 0.27 s)"
python3 "$S/extract_frames.py" "$OUT/demo_perspective.mkv" --out "$OUT/frames_persp" --mode all --overwrite
python3 "$S/camera_solve.py" vanishing --image 640x360 --lines-x "187,305,484,218;184,140,360,113" \
  --lines-z "187,305,184,140;484,218,360,113" --known-ground 187,305,484,218,12
python3 "$S/motion_track.py" "$OUT/frames_persp/manifest.json" --bbox 225,193,31,52 --scale-search --out "$OUT/track_persp.json"
python3 "$S/camera_solve.py" ground --image 640x360 --corners "187,305;484,218;360,113;184,140" --rect 12x12 \
  --track "$OUT/track_persp.json" --contact bottom --analyze speed --out "$OUT/ground_persp.json"

echo "== convert to Roblox settings"
python3 "$S/remake_calc.py" jump --apex 8.0 --rise-time 0.4 --fall-time 0.2828 --luau
python3 "$S/remake_calc.py" accel --top-speed 20 --t90 0.225 --luau

echo "== UI layout and comparison (truth: health bar off by 12,5 px; recreation 18% darker)"
python3 "$S/ui_measure.py" "$OUT/hud_boxes.json"
python3 "$S/ui_measure.py" --compare "$OUT/hud_boxes.json" "$OUT/hud_boxes_rec.json" --tolerance 0.5 || true
python3 "$S/visual_compare.py" pair "$OUT/demo_hud.png" "$OUT/demo_hud_rec.png" --out "$OUT/diff_hud" || true
python3 "$S/palette_extract.py" "$OUT/demo_hud.png" --region 52,984,300,28 --k 1

echo "demo complete: outputs in $OUT"
