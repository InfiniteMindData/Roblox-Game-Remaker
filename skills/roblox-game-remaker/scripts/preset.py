#!/usr/bin/env python3
"""Genre starting points for Config.luau, always labeled ASSUMED.

Presets give a remake sensible feel before footage is measured. They are typical genre values,
not measurements of any game. config_check.py and remake_status.py list every applied preset
value as an assumption until it is replaced with a measurement.

Subcommands:
  list                                   show available presets
  show NAME [--luau]                     values, and how to measure each one
  apply NAME --config Config.luau (--in-place | --out PATH)
      write the values into Config.luau and add "ASSUMED: preset NAME" Config.Evidence entries.
      Keys already backed by evidence (an EV-/MS- id in Config.Evidence) are never touched.

Examples:
  python preset.py list
  python preset.py show platformer --luau
  python preset.py apply platformer --config src/shared/Remake/Config.luau --in-place
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402
from config_check import ID_RE, parse_config  # noqa: E402

PRESETS = Path(__file__).resolve().parent.parent / "assets" / "presets" / "presets.json"
MEASURE = {
    "World.Gravity": "remake_calc.py jump from the measured apex and rise time",
    "Movement.WalkSpeed": "side-on standing-start clip -> motion_track --analyze speed (steady_speed)",
    "Movement.AccelerationTime": "same clip: linear ramp time_to_full_s (or t90)",
    "Movement.DecelerationTime": "side-on stop clip: time from release to standstill",
    "Movement.AirControl": "mid-air direction change: lateral acceleration in air / on ground",
    "Movement.JumpApex": "side-on standing jump -> motion_track --analyze jump (apex_height)",
    "Movement.FallGravityMultiplier": "same jump: g_fall / g_rise",
    "Movement.ReleaseGravityMultiplier": "tap jump apex -> remake_calc.py jump --min-apex --release-time",
    "Movement.MaxFallSpeed": "long drop: slope of height once it is linear",
    "Movement.CoyoteTime": "walk off a ledge and press jump late (input display needed)",
    "Movement.JumpBuffer": "press jump just before landing (input display needed)",
    "Movement.TurnSpeedDegrees": "reverse direction: facing angle over time",
    "Camera.FieldOfView": "stated FOV and its convention, or geometry (footage-analysis.md section 6) -> remake_calc.py fov",
    "Camera.Distance": "character size on screen with the known FOV",
    "Camera.FollowFrequency": "screen-space lag after a sudden start -> remake_calc.py spring",
}


def load() -> dict:
    data = rc.read_json(PRESETS)
    return data.get("presets", {})


def luau_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return f"{v:g}"
    if isinstance(v, str):
        return '"' + v.replace('"', '\\"') + '"'
    if isinstance(v, dict) and "vector3" in v:
        return "Vector3.new(" + ", ".join(f"{x:g}" for x in v["vector3"]) + ")"
    rc.fail(f"unsupported preset value {v!r}")


def get(name: str) -> dict:
    presets = load()
    if name not in presets:
        rc.fail(f"unknown preset {name!r}; available: {', '.join(sorted(presets))}")
    return presets[name]


def cmd_list(_args) -> int:
    for name, p in sorted(load().items()):
        print(f"{name:<22} {p['description']}")
    return 0


def cmd_show(args) -> int:
    p = get(args.name)
    print(f"-- Preset {args.name}: {p['description']}")
    print("-- ASSUMED starting values, not measurements of any game. Replace each with a measurement.")
    for key, v in p["values"].items():
        how = MEASURE.get(key, "measure from footage")
        if args.luau:
            print(f'{key.split(".")[-1]} = {luau_value(v)}, -- {key}: ASSUMED preset {args.name}; measure: {how}')
        else:
            print(f"{key:<36} {luau_value(v):<26} measure: {how}")
    if args.luau:
        print("-- Config.Evidence:")
        for key in p["values"]:
            print(f'["{key}"] = "ASSUMED: preset {args.name}",')
    return 0


def cmd_apply(args) -> int:
    if not args.in_place and not args.out:
        rc.fail("pass --in-place or --out PATH")
    p = get(args.name)
    if not args.config.is_file():
        rc.fail(f"Config not found: {args.config}")
    values, evidence, problems = parse_config(args.config)
    if problems:
        rc.fail("; ".join(problems))
    lines = args.config.read_text(encoding="utf-8").split("\n")
    applied, skipped = [], []
    for key, v in p["values"].items():
        if key not in values:
            skipped.append(f"{key} (not in this Config)")
            continue
        if key in evidence and ID_RE.search(evidence[key]["text"]):
            skipped.append(f"{key} (backed by {', '.join(ID_RE.findall(evidence[key]['text']))})")
            continue
        n = values[key]["line"] - 1
        leaf = key.split(".")[-1]
        m = re.match(rf"^(\s*{re.escape(leaf)}\s*=\s*)(.+?)(,?)(\s*--.*)?$", lines[n])
        if not m:
            skipped.append(f"{key} (line not in 'Key = value,' form)")
            continue
        lines[n] = f"{m.group(1)}{luau_value(v)}{m.group(3) or ','} -- ASSUMED preset {args.name}"
        applied.append(key)
    ev_line = next((i for i, ln in enumerate(lines) if re.match(r"^\s*Config\.Evidence\s*=\s*\{", ln)), None)
    if ev_line is None:
        rc.fail("Config.Evidence table not found")
    new_entries = []
    for key in applied:
        text = f"ASSUMED: preset {args.name}"
        if key in evidence:
            lines[evidence[key]["line"] - 1] = re.sub(r'=\s*"(?:[^"\\]|\\.)*"', f'= "{text}"', lines[evidence[key]["line"] - 1], count=1)
        else:
            new_entries.append(f'\t["{key}"] = "{text}",')
    lines[ev_line + 1:ev_line + 1] = new_entries
    out = args.config if args.in_place else args.out
    rc.ensure_parent(out)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"applied {len(applied)} ASSUMED values from preset {args.name} to {out}")
    for s in skipped:
        print(f"  kept {s}")
    print("next: python scripts/config_check.py remake  (lists every assumption until it is measured)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    p = sub.add_parser("show")
    p.add_argument("name")
    p.add_argument("--luau", action="store_true")
    p.set_defaults(fn=cmd_show)
    p = sub.add_parser("apply")
    p.add_argument("name")
    p.add_argument("--config", type=Path, required=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--in-place", action="store_true")
    g.add_argument("--out", type=Path)
    p.set_defaults(fn=cmd_apply)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    rc.run_main(main)
