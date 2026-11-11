#!/usr/bin/env python3
"""Report which remake tools are available and which working mode applies.

Checks Python and its packages, ffmpeg/ffprobe, Blender, Rojo, Lune, StyLua, Selene, luau-lsp
and git, and looks for a remake/ workspace and a Rojo project in PROJECT (default: the current
directory). It cannot detect MCP tools or image viewing: the agent checks those itself.

Examples:
  python doctor.py
  python doctor.py /path/to/project --json
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = {
    "ffmpeg": (["ffmpeg", "-version"], "video frame extraction, duplicate analysis, audio onsets"),
    "ffprobe": (["ffprobe", "-version"], "video probing and frame timestamps"),
    "blender": (["blender", "--version"], "modeling, rigging and the export script"),
    "rojo": (["rojo", "--version"], "file-based Studio sync and place builds"),
    "lune": (["lune", "--version"], "running Luau unit tests outside Studio"),
    "stylua": (["stylua", "--version"], "Luau formatting and syntax checks"),
    "selene": (["selene", "--version"], "Luau linting with the Roblox standard library"),
    "luau-lsp": (["luau-lsp", "--version"], "Luau type checking with Roblox definitions"),
    "git": (["git", "--version"], "version control"),
}


def probe(cmd: list[str]) -> dict:
    """Locate a tool and run its version command. "runs" is True only when the tool actually started."""
    path = shutil.which(cmd[0])
    if not path:
        return {"path": None, "version": None, "runs": False}
    try:
        # Run the resolved path: Windows does not start .cmd/.bat launchers (such as blender.cmd) by bare name.
        proc = subprocess.run([path, *cmd[1:]], capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"path": path, "version": "found (version check timed out)", "runs": False}
    except OSError as exc:
        return {"path": path, "version": f"found (could not start: {exc.strerror or exc})", "runs": False}
    text = (proc.stdout or proc.stderr).decode("utf-8", "replace").strip().splitlines()
    ok = proc.returncode == 0
    version = (text[0][:100] if text else "found") if ok else f"found (exit {proc.returncode})"
    return {"path": path, "version": version, "runs": ok}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path, nargs="?", default=Path.cwd())
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report: dict = {"python": platform.python_version(), "platform": platform.platform(), "packages": {}, "tools": {}}
    for mod, pip_name in (("numpy", "numpy"), ("PIL", "Pillow")):
        try:
            m = __import__(mod)
            report["packages"][pip_name] = getattr(m, "__version__", "installed")
        except ImportError:
            report["packages"][pip_name] = None
    for name, (cmd, purpose) in TOOLS.items():
        report["tools"][name] = {**probe(cmd), "purpose": purpose}

    proj = args.project
    report["project"] = {
        "path": str(proj),
        "remake_workspace": (proj / "remake").is_dir(),
        "rojo_projects": sorted(p.name for p in proj.glob("*.project.json")) if proj.is_dir() else [],
        "selene_toml": (proj / "selene.toml").is_file(),
    }
    py_ok = sys.version_info >= (3, 10) and all(report["packages"].values())

    def runs(name: str) -> bool:
        return bool(report["tools"][name]["runs"])

    video_ok = runs("ffmpeg") and runs("ffprobe")
    report["capabilities"] = {
        "image_scripts": py_ok,
        "video_scripts": py_ok and video_ok,
        "luau_static_checks": runs("stylua") or runs("selene"),
        "luau_unit_tests": runs("lune"),
        "place_builds": runs("rojo"),
        "blender_export": runs("blender"),
    }
    advice = []
    if not py_ok:
        advice.append("Install Python packages: pip install -r scripts/requirements.txt (Python 3.10+).")
    if not video_ok:
        advice.append("Install ffmpeg (provides ffmpeg and ffprobe) for the video scripts.")
    if not runs("rojo"):
        advice.append("Optional: Rojo (https://rojo.space) or `cargo install rojo` for file-based projects.")
    if not runs("lune"):
        advice.append("Optional: Lune (`cargo install lune`) to run the template's Luau unit tests.")
    if not runs("blender"):
        where = "found but did not start" if report["tools"]["blender"]["path"] else "not on PATH"
        advice.append(f"Blender {where}: give the user the Blender steps and scripts/blender_roblox_export.py to run.")
    for name, info in report["tools"].items():
        if info["path"] and not info["runs"] and name != "blender":
            advice.append(f"{name} is on PATH ({info['path']}) but did not start: {info['version']}.")
    advice.append("Check yourself: can you view images? Are Studio MCP tools (list_roblox_studios, execute_luau, screen_capture) available?")
    report["advice"] = advice

    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"python {report['python']}  ({report['platform']})")
    for pkg, ver in report["packages"].items():
        print(f"  {pkg:<10} {ver or 'MISSING'}")
    for name, info in report["tools"].items():
        print(f"  {name:<10} {info['version'] or '-'}")
    p = report["project"]
    print(f"project {p['path']}: remake/ {'yes' if p['remake_workspace'] else 'no'}; rojo {', '.join(p['rojo_projects']) or 'none'}")
    print("capabilities: " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in report["capabilities"].items()))
    for a in advice:
        print(f"- {a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
