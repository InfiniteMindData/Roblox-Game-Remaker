#!/usr/bin/env python3
"""Mechanical grading for the skill evals (the regex "checks" in evals.json).

Assertions that need judgment are graded by a person or an LLM, as the Agent Skills
evaluation guide describes; this script covers the checks that can be decided by pattern.

Usage:
  python evals/grade.py OUTPUT.txt --eval 2            grade one response (a transcript or the final reply)
  python evals/grade.py RUN_DIR --all                  RUN_DIR/eval-<name>/response.txt for every eval
Writes nothing; prints PASS/FAIL per check and exits 1 when any check fails.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parent / "evals.json"


def grade(text: str, ev: dict) -> list[tuple[str, bool]]:
    checks = ev.get("checks", {})
    out = [(f"must match /{p}/", re.search(p, text) is not None) for p in checks.get("must_match", [])]
    out += [(f"must not match /{p}/", re.search(p, text) is None) for p in checks.get("must_not_match", [])]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path)
    ap.add_argument("--eval", type=int)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    evals = json.loads(EVALS.read_text(encoding="utf-8"))["evals"]
    jobs = []
    if args.all:
        for ev in evals:
            jobs.append((ev, args.target / f"eval-{ev['name']}" / "response.txt"))
    elif args.eval is not None:
        ev = next((e for e in evals if e["id"] == args.eval), None)
        if ev is None:
            print(f"error: no eval {args.eval}", file=sys.stderr)
            return 2
        jobs.append((ev, args.target))
    else:
        print("error: pass --eval N or --all", file=sys.stderr)
        return 2
    failed = 0
    for ev, path in jobs:
        if not path.is_file():
            print(f"MISSING eval {ev['id']} {ev['name']}: {path}")
            failed += 1
            continue
        for label, ok in grade(path.read_text(encoding="utf-8", errors="replace"), ev):
            print(f"{'PASS' if ok else 'FAIL'} eval {ev['id']} {ev['name']}: {label}")
            failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
