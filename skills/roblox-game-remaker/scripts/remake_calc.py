#!/usr/bin/env python3
"""Reproducible conversions for 1:1 remakes (units, FOV, frames, jumps, acceleration, springs).

Subcommands:
  units   lengths, speeds and accelerations between meters and studs
  fov     horizontal / vertical / diagonal FOV at an aspect ratio; Hor+ re-aspect
  frames  frame counts to seconds with +/- one-frame uncertainty
  jump    apex height + rise/fall times -> takeoff speed, rise/fall gravity, Roblox settings
  accel   top speed + time-to-90% -> linear acceleration, exponential tau, ControllerManager hints
  spring  overshoot + settle time -> damping ratio and angular frequency for Spring.luau
  scale   pixels-per-unit from a known-size reference in the same frame

Roblox facts used (creator docs): 1 stud = 0.28 m; Workspace.Gravity default 196.2 studs/s^2;
Camera.FieldOfView is vertical.

Examples:
  python remake_calc.py units --meters 1.8
  python remake_calc.py units --mps2 9.81 --studs-per-meter 3.571
  python remake_calc.py fov --horizontal 90 --aspect 16:9
  python remake_calc.py frames --start 240 --end 263 --fps 60
  python remake_calc.py jump --apex 7.4 --rise-time 0.383 --fall-time 0.300 --luau
  python remake_calc.py accel --top-speed 20 --t90 0.18
  python remake_calc.py spring --overshoot 0.08 --settle-time 0.35
  python remake_calc.py scale --pixels 160 --size 5.0
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

METERS_PER_STUD = 0.28
STUDS_PER_METER = 1.0 / METERS_PER_STUD
ROBLOX_DEFAULT_GRAVITY = 196.2


# ----------------------------------------------------------------- math (importable)

def vfov_from_hfov(h_deg: float, aspect: float) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(h_deg) / 2) / aspect))


def hfov_from_vfov(v_deg: float, aspect: float) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(v_deg) / 2) * aspect))


def vfov_from_dfov(d_deg: float, aspect: float) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(d_deg) / 2) / math.sqrt(1 + aspect * aspect)))


def dfov_from_vfov(v_deg: float, aspect: float) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(v_deg) / 2) * math.sqrt(1 + aspect * aspect)))


def solve_jump(apex: float, rise: float, fall: float | None = None,
               min_apex: float | None = None, release_time: float | None = None) -> dict:
    if apex <= 0 or rise <= 0:
        rc.fail("--apex and --rise-time must be positive")
    v0 = 2 * apex / rise
    g_rise = 2 * apex / rise ** 2
    out = {"apex": apex, "rise_time": rise, "takeoff_speed": v0, "g_rise": g_rise}
    if fall is not None:
        if fall <= 0:
            rc.fail("--fall-time must be positive")
        g_fall = 2 * apex / fall ** 2
        out.update({"fall_time": fall, "g_fall": g_fall, "fall_multiplier": g_fall / g_rise, "airtime": rise + fall})
    else:
        out.update({"fall_time": rise, "g_fall": g_rise, "fall_multiplier": 1.0, "airtime": 2 * rise})
    if min_apex is not None:
        t0 = release_time if release_time is not None else 0.0
        if not 0 < min_apex < apex:
            rc.fail("--min-apex must be between 0 and --apex")
        v1 = v0 - g_rise * t0
        h1 = v0 * t0 - 0.5 * g_rise * t0 * t0
        if v1 <= 0 or min_apex <= h1:
            rc.fail("release happens after the short-hop apex; check --release-time")
        m = v1 * v1 / (2 * g_rise * (min_apex - h1))
        out.update({"min_apex": min_apex, "release_time": t0, "release_multiplier": m})
    # Roblox: JumpPower behaves as the takeoff speed for the current gravity.
    out["roblox"] = {
        "Workspace.Gravity": g_rise,
        "CharacterUseJumpPower": False,
        "CharacterJumpHeight": apex,
        "equivalent_JumpPower": v0,
    }
    return out


def solve_accel(top: float, t90: float | None = None, time_to_top: float | None = None) -> dict:
    if top <= 0:
        rc.fail("--top-speed must be positive")
    if t90 is None and time_to_top is None:
        rc.fail("give --t90 (time to 90% speed) or --time-to-top (linear ramp duration)")
    if time_to_top is None:
        time_to_top = t90 / 0.9
    if t90 is None:
        t90 = 0.9 * time_to_top
    if t90 <= 0:
        rc.fail("times must be positive")
    tau = t90 / math.log(10)
    return {
        "top_speed": top,
        "t90": t90,
        "linear": {"time_to_top": time_to_top, "acceleration": top / time_to_top},
        "exponential": {"tau": tau, "t95": tau * math.log(20), "t99": tau * math.log(100)},
        "roblox": {
            "GroundController.AccelerationTime_start": t90,
            "note": "AccelerationTime is documented as an estimate; tune it until measure_compare accel_t90 matches",
        },
    }


def _step_settle_constant(zeta: float, band: float = 0.02) -> float:
    """omega_n * settle-time for a unit step response with damping ratio zeta."""
    t_end = 60.0 / max(zeta, 0.05)
    n = 60000
    last = 0.0
    for i in range(1, n + 1):
        t = t_end * i / n
        if zeta < 1:
            wd = math.sqrt(1 - zeta * zeta)
            y = 1 - math.exp(-zeta * t) * (math.cos(wd * t) + zeta / wd * math.sin(wd * t))
        elif zeta == 1:
            y = 1 - math.exp(-t) * (1 + t)
        else:
            s = math.sqrt(zeta * zeta - 1)
            r1, r2 = -zeta + s, -zeta - s
            y = 1 - (r2 * math.exp(r1 * t) - r1 * math.exp(r2 * t)) / (r2 - r1)
        if abs(y - 1) > band:
            last = t
    return last


def solve_spring(overshoot: float, settle: float, band: float = 0.02) -> dict:
    if not 0 <= overshoot < 1:
        rc.fail("--overshoot is a fraction 0..1 (0.08 = 8%)")
    if settle <= 0:
        rc.fail("--settle-time must be positive")
    if overshoot == 0:
        zeta = 1.0
    else:
        ln = math.log(overshoot)
        zeta = -ln / math.sqrt(math.pi ** 2 + ln ** 2)
    k = _step_settle_constant(zeta, band)
    omega = k / settle
    return {"overshoot": overshoot, "settle_time": settle, "band": band, "damping_ratio": zeta,
            "angular_frequency": omega, "frequency_hz": omega / (2 * math.pi)}


# ----------------------------------------------------------------- output

def fmt(v, digits=4):
    if isinstance(v, float):
        return f"{v:.{digits}f}".rstrip("0").rstrip(".") if abs(v) < 1e6 else f"{v:.4g}"
    return str(v)


def emit(data: dict, args, lines: list[str], luau: list[str] | None = None) -> int:
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
    else:
        print("\n".join(lines))
        if luau and getattr(args, "luau", False):
            print("\n-- Luau (paste into Config.luau; keep the evidence IDs)")
            print("\n".join(luau))
    return 0


def cmd_units(args) -> int:
    spm = args.studs_per_meter
    data, lines = {"studs_per_meter": spm}, [f"scale: {fmt(spm)} studs per meter ({fmt(1 / spm)} m per stud)"]
    pairs = [("meters", "m", "studs"), ("studs", "studs", "m"), ("mps", "m/s", "studs/s"),
             ("sps", "studs/s", "m/s"), ("mps2", "m/s^2", "studs/s^2"), ("sps2", "studs/s^2", "m/s^2")]
    found = False
    for attr, src, dst in pairs:
        val = getattr(args, attr)
        if val is None:
            continue
        found = True
        conv = val * spm if dst.startswith("studs") else val / spm
        data[attr] = {"input": val, "unit": src, "output": conv, "output_unit": dst}
        lines.append(f"{fmt(val)} {src} = {fmt(conv)} {dst}")
        if attr in ("mps2", "sps2"):
            g_studs = conv if dst.startswith("studs") else val
            lines.append(f"  (Roblox default gravity is {ROBLOX_DEFAULT_GRAVITY} studs/s^2 = "
                         f"{fmt(ROBLOX_DEFAULT_GRAVITY / spm)} m/s^2 at this scale; ratio {fmt(g_studs / ROBLOX_DEFAULT_GRAVITY)})")
    if not found:
        rc.fail("give at least one of --meters --studs --mps --sps --mps2 --sps2")
    return emit(data, args, lines)


def cmd_fov(args) -> int:
    aspect = rc.parse_aspect(args.aspect)
    given = [x for x in (args.horizontal, args.vertical, args.diagonal) if x is not None]
    if len(given) != 1:
        rc.fail("give exactly one of --horizontal, --vertical, --diagonal")
    if not 0 < given[0] < 180:
        rc.fail("FOV must be between 0 and 180 degrees")
    if args.horizontal is not None:
        v = vfov_from_hfov(args.horizontal, aspect)
    elif args.vertical is not None:
        v = args.vertical
    else:
        v = vfov_from_dfov(args.diagonal, aspect)
    data = {"aspect": aspect, "vertical": v, "horizontal": hfov_from_vfov(v, aspect), "diagonal": dfov_from_vfov(v, aspect)}
    lines = [f"aspect {fmt(aspect)}: vertical {fmt(v)} deg | horizontal {fmt(data['horizontal'])} deg | diagonal {fmt(data['diagonal'])} deg",
             f"Roblox Camera.FieldOfView (vertical) = {fmt(v)}"]
    if args.to_aspect:
        a2 = rc.parse_aspect(args.to_aspect)
        h = data["horizontal"]
        v_horplus = v  # Hor+: vertical stays, horizontal widens
        v_vertminus = vfov_from_hfov(h, a2)  # Vert-: horizontal stays
        data["to_aspect"] = {"aspect": a2, "hor_plus_vertical": v_horplus, "hor_plus_horizontal": hfov_from_vfov(v_horplus, a2),
                             "vert_minus_vertical": v_vertminus}
        lines.append(f"at aspect {fmt(a2)}: Hor+ keeps vertical {fmt(v_horplus)} (horizontal {fmt(hfov_from_vfov(v_horplus, a2))}); "
                     f"Vert- keeps horizontal {fmt(h)} (vertical {fmt(v_vertminus)})")
    if v > 120:
        lines.append("WARNING: Roblox clamps FieldOfView to 1..120 degrees")
    return emit(data, args, lines, [f"FieldOfView = {v:.3f}, -- vertical deg"])


def cmd_frames(args) -> int:
    if args.fps <= 0:
        rc.fail("--fps must be positive")
    if args.count is not None:
        n = args.count
    elif args.start is not None and args.end is not None:
        n = args.end - args.start
    else:
        rc.fail("give --count or --start and --end")
    if n < 0:
        rc.fail("frame count must not be negative")
    sec = n / args.fps
    unc = 1 / args.fps
    data = {"frames": n, "fps": args.fps, "seconds": sec, "uncertainty_s": unc, "ms": sec * 1000}
    lines = [f"{n} frames @ {fmt(args.fps)} fps = {fmt(sec)} s ± {fmt(unc)} s ({fmt(sec * 1000, 1)} ms ± {fmt(unc * 1000, 1)} ms)"]
    if args.roblox_fps:
        rf = n / args.fps * args.roblox_fps
        data["frames_at_roblox_fps"] = rf
        lines.append(f"= {fmt(rf, 2)} frames at {fmt(args.roblox_fps)} fps (Animation Editor default is 30)")
    return emit(data, args, lines)


def cmd_jump(args) -> int:
    d = solve_jump(args.apex, args.rise_time, args.fall_time, args.min_apex, args.release_time)
    u = args.unit
    lines = [
        f"apex {fmt(d['apex'])} {u}, rise {fmt(d['rise_time'])} s, fall {fmt(d['fall_time'])} s, airtime {fmt(d['airtime'])} s",
        f"takeoff speed v0 = {fmt(d['takeoff_speed'])} {u}/s",
        f"rise gravity = {fmt(d['g_rise'])} {u}/s^2   fall gravity = {fmt(d['g_fall'])} {u}/s^2   fall multiplier = {fmt(d['fall_multiplier'])}",
    ]
    if "release_multiplier" in d:
        lines.append(f"short hop {fmt(d['min_apex'])} {u} with release at {fmt(d['release_time'])} s -> release gravity multiplier {fmt(d['release_multiplier'])}")
    lines.append(f"Roblox: Workspace.Gravity = {fmt(d['g_rise'])}; StarterPlayer.CharacterUseJumpPower = false; CharacterJumpHeight = {fmt(d['apex'])}"
                 f" (equivalent JumpPower {fmt(d['takeoff_speed'])})")
    if abs(d["fall_multiplier"] - 1) > 0.05:
        lines.append("Asymmetric jump: use MovementFeel FallGravityMultiplier (extra downward VectorForce while falling).")
    luau = [
        f"Gravity = {d['g_rise']:.3f}, -- rise gravity (studs/s^2)",
        f"JumpApex = {d['apex']:.3f},",
        f"RiseTime = {d['rise_time']:.4f},",
        f"FallTime = {d['fall_time']:.4f},",
        f"FallGravityMultiplier = {d['fall_multiplier']:.4f},",
    ]
    if "release_multiplier" in d:
        luau.append(f"ReleaseGravityMultiplier = {d['release_multiplier']:.4f},")
    return emit(d, args, lines, luau)


def cmd_accel(args) -> int:
    d = solve_accel(args.top_speed, args.t90, args.time_to_top)
    lines = [
        f"top speed {fmt(d['top_speed'])}; t90 {fmt(d['t90'])} s",
        f"linear ramp: full speed after {fmt(d['linear']['time_to_top'])} s, acceleration {fmt(d['linear']['acceleration'])} units/s^2",
        f"exponential: tau {fmt(d['exponential']['tau'])} s (t95 {fmt(d['exponential']['t95'])} s, t99 {fmt(d['exponential']['t99'])} s)",
        f"ControllerManager: start GroundController.AccelerationTime at {fmt(d['t90'])} and tune with the harness",
    ]
    luau = [f"AccelerationTime = {d['linear']['time_to_top']:.4f}, -- linear ramp duration (s)",
            f"AccelerationTau = {d['exponential']['tau']:.4f}, -- if the exponential model fits better"]
    return emit(d, args, lines, luau)


def cmd_spring(args) -> int:
    d = solve_spring(args.overshoot, args.settle_time, args.band)
    kind = "critically damped" if abs(d["damping_ratio"] - 1) < 1e-9 else ("underdamped" if d["damping_ratio"] < 1 else "overdamped")
    lines = [f"{kind}: damping ratio {fmt(d['damping_ratio'])}, angular frequency {fmt(d['angular_frequency'])} rad/s "
             f"({fmt(d['frequency_hz'])} Hz); settles within {d['band']:.0%} in {fmt(d['settle_time'])} s"]
    luau = [f"Spring.new(initial, {d['angular_frequency']:.4f}, {d['damping_ratio']:.4f}) -- omega rad/s, zeta"]
    return emit(d, args, lines, luau)


def cmd_scale(args) -> int:
    if args.pixels <= 0 or args.size <= 0:
        rc.fail("--pixels and --size must be positive")
    ppu = args.pixels / args.size
    data = {"px_per_unit": ppu, "reference_pixels": args.pixels, "reference_size": args.size, "unit": args.unit}
    lines = [f"{fmt(args.pixels)} px for {fmt(args.size)} {args.unit} -> --px-per-unit {fmt(ppu)}",
             "valid only at the reference's depth; re-measure when the subject's distance to the camera changes"]
    return emit(data, args, lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("units")
    for name in ("meters", "studs", "mps", "sps", "mps2", "sps2"):
        p.add_argument(f"--{name}", type=float)
    p.add_argument("--studs-per-meter", type=float, default=STUDS_PER_METER,
                   help=f"world scale (default official {STUDS_PER_METER:.4f}; use a character-relative value if chosen)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_units)

    p = sub.add_parser("fov")
    p.add_argument("--horizontal", type=float)
    p.add_argument("--vertical", type=float)
    p.add_argument("--diagonal", type=float)
    p.add_argument("--aspect", required=True, help="width:height, for example 16:9")
    p.add_argument("--to-aspect", help="also show Hor+ and Vert- results at another aspect")
    p.add_argument("--json", action="store_true")
    p.add_argument("--luau", action="store_true")
    p.set_defaults(fn=cmd_fov)

    p = sub.add_parser("frames")
    p.add_argument("--start", type=int)
    p.add_argument("--end", type=int)
    p.add_argument("--count", type=int)
    p.add_argument("--fps", type=float, required=True, help="effective fps (from probe_video --dupes)")
    p.add_argument("--roblox-fps", type=float, help="also express the duration in frames at this rate (for example 30)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_frames)

    p = sub.add_parser("jump")
    p.add_argument("--apex", type=float, required=True)
    p.add_argument("--rise-time", type=float, required=True)
    p.add_argument("--fall-time", type=float)
    p.add_argument("--min-apex", type=float, help="apex of the shortest (tap) jump")
    p.add_argument("--release-time", type=float, help="seconds after takeoff when the tap jump's button is released")
    p.add_argument("--unit", default="studs")
    p.add_argument("--json", action="store_true")
    p.add_argument("--luau", action="store_true")
    p.set_defaults(fn=cmd_jump)

    p = sub.add_parser("accel")
    p.add_argument("--top-speed", type=float, required=True)
    p.add_argument("--t90", type=float)
    p.add_argument("--time-to-top", type=float)
    p.add_argument("--json", action="store_true")
    p.add_argument("--luau", action="store_true")
    p.set_defaults(fn=cmd_accel)

    p = sub.add_parser("spring")
    p.add_argument("--overshoot", type=float, required=True, help="fraction, for example 0.08; 0 = no overshoot (critical damping)")
    p.add_argument("--settle-time", type=float, required=True, help="seconds until within --band of the target")
    p.add_argument("--band", type=float, default=0.02)
    p.add_argument("--json", action="store_true")
    p.add_argument("--luau", action="store_true")
    p.set_defaults(fn=cmd_spring)

    p = sub.add_parser("scale")
    p.add_argument("--pixels", type=float, required=True, help="size of the reference in pixels")
    p.add_argument("--size", type=float, required=True, help="real size of the reference")
    p.add_argument("--unit", default="studs")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_scale)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    rc.run_main(main)
