#!/usr/bin/env python3
"""Create the remake/ workspace in a project from the skill's templates.

Never overwrites: existing files are left untouched and reported. Creates the working
directories used by the other scripts (media, frames, sheets, tracks, captures, diff, logs,
ui, masks, audio).

Examples:
  python breakdown_init.py /path/to/project --game "Lantern Hop" --version 1.2.0 --platform "PC, gamepad"
  python breakdown_init.py . --game "My Game" --dry-run
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TEMPLATES = Path(__file__).resolve().parent.parent / "assets" / "templates"
SUBDIRS = ["media", "frames", "sheets", "tracks", "captures", "diff", "logs", "ui", "masks", "audio"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path, help="project root (remake/ is created inside it)")
    ap.add_argument("--game", required=True, help="name of the reference game")
    ap.add_argument("--version", default="TBD", help="version or patch of the reference")
    ap.add_argument("--platform", default="TBD", help="platform and input device of the reference")
    ap.add_argument("--date", help="override today's date (YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true", help="show what would be created")
    args = ap.parse_args()

    if not args.project.is_dir():
        rc.fail(f"project directory not found: {args.project}")
    if not TEMPLATES.is_dir():
        rc.fail(f"templates not found at {TEMPLATES}; is the skill installed completely?")
    root = args.project / "remake"
    date = args.date or _dt.date.today().isoformat()
    values = {"{{GAME}}": args.game, "{{VERSION}}": args.version, "{{PLATFORM}}": args.platform, "{{DATE}}": date}

    created, skipped = [], []
    if not args.dry_run:
        root.mkdir(exist_ok=True)
    for sub in SUBDIRS:
        d = root / sub
        if not d.exists():
            created.append(f"{d}/")
            if not args.dry_run:
                d.mkdir(parents=True)
    for tpl in sorted(TEMPLATES.iterdir()):
        if not tpl.is_file():
            continue
        target = root / tpl.name
        if target.exists():
            skipped.append(str(target))
            continue
        text = tpl.read_text(encoding="utf-8")
        for k, v in values.items():
            text = text.replace(k, v.replace('"', '\\"') if tpl.suffix == ".json" else v)
        created.append(str(target))
        if not args.dry_run:
            target.write_text(text, encoding="utf-8")

    prefix = "would create" if args.dry_run else "created"
    for c in created:
        print(f"{prefix} {c}")
    for s in skipped:
        print(f"kept existing {s}")
    print(f"{len(created)} {prefix.split()[-1]}, {len(skipped)} existing kept. Next: fill {root / '00-intake.md'}")
    return 0


if __name__ == "__main__":
    rc.run_main(main)
