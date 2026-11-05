"""End-to-end: a remake workspace taken through every phase gate with the skill's own tools.

Follows references/recipes.md (start, match a jump, match movement, greybox, before delivery) on
the synthetic demo footage, and checks remake_status.py advances phase by phase.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "roblox-game-remaker"
SCRIPTS = SKILL / "scripts"
TEMPLATE_CONFIG = SKILL / "assets" / "rojo-template" / "src" / "shared" / "Remake" / "Config.luau"


def run(script: str, *args, ok=(0,)) -> subprocess.CompletedProcess:
    proc = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=600)
    if proc.returncode not in ok:
        raise AssertionError(f"{script} {' '.join(map(str, args))} -> {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return proc


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe not installed")
class EndToEndTests(unittest.TestCase):
    def phase(self) -> int:
        return json.loads(run("remake_status.py", self.remake, "--json").stdout)["current_phase"]

    def test_full_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            self.remake = remake = proj / "remake"
            # Recipe 1: start
            run("breakdown_init.py", proj, "--game", "E2E Hop", "--version", "1.0", "--platform", "PC")
            self.assertEqual(self.phase(), 0)
            intake = (remake / "00-intake.md").read_text()
            intake = intake.replace("- [ ] Own IP", "- [x] Own IP").replace("- Vertical slice (first deliverable):", "- Vertical slice (first deliverable): level 1")
            (remake / "00-intake.md").write_text(intake)
            subprocess.run([sys.executable, str(SKILL / "examples" / "demo" / "make_demo_footage.py"), "--out", str(remake / "media")],
                           check=True, capture_output=True)
            ev_jump = run("ledger.py", "add-evidence", remake, "--type", "video", "--title", "jump", "--source", "remake/media/demo_jump.mkv",
                          "--analysis", "probe, extract, find_mover, motion_track").stdout.strip()
            ev_run = run("ledger.py", "add-evidence", remake, "--type", "video", "--title", "run", "--source", "remake/media/demo_run.mkv",
                         "--analysis", "probe, extract, find_mover, motion_track").stdout.strip()
            ev_hud = run("ledger.py", "add-evidence", remake, "--type", "screenshot", "--title", "hud", "--source", "remake/media/demo_hud.png",
                         "--analysis", "visual_compare").stdout.strip()
            run("ledger.py", "add-evidence", remake, "--type", "video", "--title", "speedrun", "--source", "https://example.invalid/v", "--inaccessible")
            self.assertEqual(self.phase(), 2)

            # Recipes 3 and 4: measure the jump and the run with suggested boxes
            ppu = json.loads(run("remake_calc.py", "scale", "--pixels", "20", "--size", "1", "--json").stdout)["px_per_unit"]
            for clip, analyze, ev in (("jump", "jump", ev_jump), ("run", "speed", ev_run)):
                run("probe_video.py", remake / "media" / f"demo_{clip}.mkv", "--dupes")
                run("extract_frames.py", remake / "media" / f"demo_{clip}.mkv", "--out", remake / "frames" / clip, "--mode", "all")
                mover = json.loads(run("find_mover.py", remake / "frames" / clip / "manifest.json", "--json").stdout)
                args = ["--bbox", ",".join(map(str, mover["candidates"][0]["bbox"]))]
                if mover["anchor_bbox"]:
                    args += ["--anchor-bbox", ",".join(map(str, mover["anchor_bbox"])), "--search", "40"]
                run("motion_track.py", remake / "frames" / clip / "manifest.json", *args, "--px-per-unit", ppu,
                    "--analyze", analyze, "--out", remake / "tracks" / f"{clip}.json")
                run("ledger.py", "import-track", remake, remake / "tracks" / f"{clip}.json", "--evidence", ev)
            ms = {m["metric"]: m for m in json.loads((remake / "measurements.json").read_text())["measurements"]}
            self.assertAlmostEqual(ms["jump_apex"]["value"], 8.0, delta=0.1)
            self.assertAlmostEqual(ms["ground_speed"]["value"], 20.0, delta=0.3)
            shots = {"schema": 1, "reference_resolution": [1920, 1080], "shots": [{
                "id": "SHOT-HUD", "evidence": ev_hud, "reference": "remake/media/demo_hud.png", "recreation": "remake/captures/SHOT-HUD.png",
                "camera": {"position": [0, 12, 30], "look_at": [0, 4, 0], "fov": 58.7155}, "thresholds": {"edge_iou": 0.5}}]}
            (remake / "shots.json").write_text(json.dumps(shots))
            self.assertEqual(self.phase(), 3)

            # Breakdown citing the ledger
            entries = [
                ("MOVE-001", "Ground run", "MEASURED", f"{ev_run}, {ms['ground_speed']['id']}, {ms['accel_t90']['id']}",
                 f"run_speed = {ms['ground_speed']['value']} ± {ms['ground_speed']['uncertainty']} studs/s"),
                ("MOVE-002", "Standing jump", "MEASURED", f"{ev_jump}, {ms['jump_apex']['id']}, {ms['jump_rise_time']['id']}",
                 f"apex_height = {ms['jump_apex']['value']} ± {ms['jump_apex']['uncertainty']} studs"),
                ("UI-001", "HUD", "OBSERVED", ev_hud, None),
            ]
            text = "## Coverage\n" + "".join(f"- n/a: {c} (outside this test slice)\n" for c in
                                             ("CTRL", "CAM", "MECH", "CHAR", "ANIM", "ENV", "VFX", "AUD", "AI", "SYS", "VR")) + "\n"
            for eid, title, status, evidence, value in entries:
                text += f"### {eid}: {title}\n- status: {status}\n- evidence: {evidence}\n"
                text += f"- value: {value}\n" if value else ""
                text += "- roblox: Config values from the ledger\n- accept: measure_compare within tier A\n\n"
            (remake / "breakdown.md").write_text(text)
            run("breakdown_check.py", remake, "--strict")
            self.assertEqual(self.phase(), 4)
            run("ledger.py", "targets", remake, "--tier", "A")
            self.assertEqual(self.phase(), 5)

            # Build: preset first, then measured values with evidence
            cfg_dir = proj / "src" / "shared" / "Remake"
            cfg_dir.mkdir(parents=True)
            cfg = cfg_dir / "Config.luau"
            shutil.copy(TEMPLATE_CONFIG, cfg)
            run("preset.py", "apply", "platformer", "--config", cfg, "--in-place")
            jump = json.loads(run("remake_calc.py", "jump", "--apex", ms["jump_apex"]["value"], "--rise-time", ms["jump_rise_time"]["value"],
                                  "--fall-time", ms["jump_fall_time"]["value"], "--json").stdout)
            c = cfg.read_text()
            for key, val in (("WalkSpeed", round(ms["ground_speed"]["value"], 2)), ("JumpApex", round(ms["jump_apex"]["value"], 3)),
                             ("Gravity", round(jump["g_rise"], 3))):
                lines = c.split("\n")
                i = next(n for n, ln in enumerate(lines) if ln.strip().startswith(f"{key} ="))
                lines[i] = f"\t{key} = {val}, -- measured"
                c = "\n".join(lines)
            c = c.replace('\t["Movement.WalkSpeed"] = "ASSUMED: preset platformer",', f'\t["Movement.WalkSpeed"] = "{ms["ground_speed"]["id"]}",')
            c = c.replace('\t["Movement.JumpApex"] = "ASSUMED: preset platformer",', f'\t["Movement.JumpApex"] = "{ms["jump_apex"]["id"]}",')
            c = c.replace('\t["World.Gravity"] = "ASSUMED: preset platformer",',
                          f'\t["World.Gravity"] = "derived: {ms["jump_apex"]["id"]}, {ms["jump_rise_time"]["id"]} (remake_calc jump)",')
            cfg.write_text(c)
            check = json.loads(run("config_check.py", remake, "--json").stdout)
            self.assertEqual(check["error_count"], 0, check["errors"])
            self.assertEqual(check["summary"]["direct_matches"], 2)
            self.assertGreater(len(check["summary"]["assumptions"]), 5)  # the rest of the preset, still flagged
            self.assertEqual(run("config_check.py", remake, "--strict", ok=(1,)).returncode, 1)
            self.assertEqual(self.phase(), 6)

            # Recipe 9: greybox
            layout = {"unit": "studs", "parts": [{"name": "Floor", "size": [64, 1, 64], "position": [0, -0.5, 0]},
                                                 {"name": "Gap", "size": [8, 1, 8], "position": [20, 4, 0]}], "spawn": [0, 1, 0]}
            (remake / "layout.json").write_text(json.dumps(layout))
            run("studio_snippets.py", "greybox", remake / "layout.json", "--out", remake / "greybox.luau")
            self.assertIn('part("Gap"', (remake / "greybox.luau").read_text())

            # Verify: a harness log consistent with the measured jump and run, plus a shot comparison
            dt, g_r, g_f = 1 / 60, jump["g_rise"], jump["g_fall"]
            v0, lines, batch, y, vy, x, airborne, done = jump["takeoff_speed"], [], [], 3.0, 0.0, 0.0, False, False
            lines.append('REMAKE_MEASURE {"k":"e","t":0.5,"n":"move_start"}')
            ramp = ms["accel_ramp"]["value"]
            for i in range(300):
                t = i * dt
                vx = min(ms["ground_speed"]["value"], max(0.0, (t - 0.5) / ramp * ms["ground_speed"]["value"]))
                st = 1
                if t >= 3.0 and not airborne and not done:
                    airborne, vy = True, v0
                    lines.append(f'REMAKE_MEASURE {{"k":"e","t":{t:.4f},"n":"jump"}}')
                if airborne:
                    g = g_r if vy > 0 else g_f
                    y += vy * dt - 0.5 * g * dt * dt
                    vy -= g * dt
                    st = 2 if vy > 0 else 3
                    if y <= 3.0:
                        y, vy, airborne, done, st = 3.0, 0.0, False, True, 1
                        lines.append(f'REMAKE_MEASURE {{"k":"e","t":{t:.4f},"n":"land"}}')
                x += vx * dt
                batch.append([round(t, 4), round(x, 3), round(y, 4), 0, round(vx, 3), round(vy, 3), 0, st, 1.0 if t >= 0.5 else 0.0])
                if len(batch) == 30:
                    lines.append("REMAKE_MEASURE " + json.dumps({"k": "b", "s": batch}))
                    batch = []
            (proj / "console.txt").write_text("\n".join(f"12:00:00.000  {ln}  -  Client" for ln in lines) + "\n")
            run("studio_snippets.py", "extract-log", proj / "console.txt", "--out", remake / "logs" / "run-01.log")
            run("measure_compare.py", remake / "logs" / "run-01.log", "--targets", remake / "targets.json", "--allow-missing")
            shutil.copy(remake / "media" / "demo_hud_rec.png", remake / "captures" / "SHOT-HUD.png")
            run("visual_compare.py", "batch", remake / "shots.json", "--out", remake / "diff", "--root", proj)
            self.assertEqual(self.phase(), 6)  # no iteration logged yet
            (remake / "diff-log.md").write_text("## Iteration 1\n- change: measured values\n- after: jump and run pass; SHOT-HUD pass\n")
            self.assertEqual(self.phase(), 7)
            report = (remake / "delivery-report.md").read_text().replace(
                "|---|---|---|---|---|\n", "|---|---|---|---|---|\n| MOVE-002 | apex ±0.56 | 8.0 | pass | logs/run-01.log |\n", 1)
            (remake / "delivery-report.md").write_text(report)
            self.assertEqual(self.phase(), 8)
            status = run("remake_status.py", remake, "--write").stdout
            self.assertIn("All gates pass", status)
            self.assertIn("speedrun", (remake / "STATUS.md").read_text())


if __name__ == "__main__":
    unittest.main()
