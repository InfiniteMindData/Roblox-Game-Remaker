#!/usr/bin/env python3
"""Validate an Agent Skill directory against the Agent Skills specification and repo rules.

Spec rules (agentskills.io/specification):
  - SKILL.md starts with YAML frontmatter; name and description are required
  - name: 1-64 chars, lowercase a-z, 0-9 and single hyphens, no leading/trailing hyphen,
    equals the directory name
  - description: 1-1024 chars; compatibility: <= 500 chars; metadata: string -> string map;
    allowed-tools: a string; no other top-level fields
  - keep SKILL.md under 500 lines (and the body under ~5000 tokens)
  - file references are relative to the skill root and resolve
Repo rules:
  - every file in references/ is linked from SKILL.md (one level deep)
  - description has no angle brackets
  - JSON files parse; agents/openai.yaml has display_name, a 25-64 char short_description and a
    default_prompt that mentions $<name>
  - with --run-help, every CLI script answers --help with exit status 0

Usage: python tools/validate_skill.py skills/roblox-game-remaker [--run-help] [--json]
Exit: 0 valid, 1 errors (or warnings with --strict), 2 bad target.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s#]+)(?:#[^)]*)?\)")
TICK_PATH_RE = re.compile(r"`((?:references|scripts|assets|examples|agents)/[A-Za-z0-9_./-]+)`")
NO_HELP = {"remake_common.py", "blender_roblox_export.py"}


def parse_frontmatter(text: str):
    if not text.startswith("---\n"):
        return None, "SKILL.md must start with '---' frontmatter"
    end = text.find("\n---", 4)
    if end < 0:
        return None, "frontmatter is not closed with '---'"
    raw = text[4:end]
    try:
        import yaml  # type: ignore
    except ImportError:
        return None, "PyYAML is required to parse frontmatter (pip install pyyaml)"
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:  # type: ignore[attr-defined]
        return None, f"frontmatter is not valid YAML: {exc}"
    if not isinstance(data, dict):
        return None, "frontmatter must be a mapping"
    return (data, text[end + 4:]), None


def validate(skill: Path, run_help: bool) -> tuple[list[str], list[str], dict]:
    errors: list[str] = []
    warnings: list[str] = []
    info: dict = {}
    md = skill / "SKILL.md"
    if not md.is_file():
        return [f"{md} not found"], [], info
    text = md.read_text(encoding="utf-8")
    parsed, err = parse_frontmatter(text)
    if err:
        return [err], [], info
    fm, body = parsed
    for key in fm:
        if key not in ALLOWED_FIELDS:
            errors.append(f"frontmatter: unknown field {key!r} (allowed: {', '.join(sorted(ALLOWED_FIELDS))})")
    name = fm.get("name")
    if not isinstance(name, str) or not name:
        errors.append("frontmatter: 'name' is required")
    else:
        if len(name) > 64:
            errors.append("name: longer than 64 characters")
        if not NAME_RE.match(name):
            errors.append("name: only lowercase letters, digits and single hyphens; no leading/trailing hyphen")
        if name != skill.name:
            errors.append(f"name {name!r} must equal the directory name {skill.name!r}")
    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errors.append("frontmatter: 'description' is required and non-empty")
    else:
        if len(desc) > 1024:
            errors.append(f"description: {len(desc)} characters (max 1024)")
        if "<" in desc or ">" in desc:
            errors.append("description: avoid angle brackets")
        if not re.search(r"\buse when\b", desc, re.IGNORECASE):
            warnings.append("description: say when to use the skill ('Use when ...')")
        info["description_chars"] = len(desc)
    comp = fm.get("compatibility")
    if comp is not None and (not isinstance(comp, str) or not 1 <= len(comp) <= 500):
        errors.append("compatibility: must be a string of 1-500 characters")
    meta = fm.get("metadata")
    if meta is not None:
        if not isinstance(meta, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in meta.items()):
            errors.append("metadata: must map string keys to string values (quote numbers)")
    if "allowed-tools" in fm and not isinstance(fm["allowed-tools"], str):
        errors.append("allowed-tools: must be a space-separated string")
    if "license" in fm and not isinstance(fm["license"], str):
        errors.append("license: must be a string")

    lines = text.count("\n") + 1
    tokens = len(body) // 4
    info.update({"lines": lines, "body_tokens_approx": tokens})
    if lines >= 500:
        warnings.append(f"SKILL.md has {lines} lines; keep it under 500")
    if tokens > 5000:
        warnings.append(f"SKILL.md body is about {tokens} tokens; keep it under about 5000")

    linked: set[str] = set()
    for target in LINK_RE.findall(body) + TICK_PATH_RE.findall(body):
        if re.match(r"^[a-z]+://", target) or target.startswith("mailto:"):
            continue
        clean = target.rstrip("/.,;:")
        linked.add(clean)
        if not (skill / clean).exists():
            errors.append(f"SKILL.md links to missing path: {clean}")
    refs = skill / "references"
    if refs.is_dir():
        for f in sorted(refs.glob("*.md")):
            rel = f"references/{f.name}"
            if rel not in linked:
                errors.append(f"{rel} is not linked from SKILL.md")
        for f in sorted(refs.glob("*.md")):
            for target in LINK_RE.findall(f.read_text(encoding="utf-8")):
                if not re.match(r"^[a-z]+://", target) and not (f.parent / target).exists():
                    errors.append(f"{f.relative_to(skill)} links to missing path: {target}")

    for jf in sorted(skill.rglob("*.json")):
        try:
            json.loads(jf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{jf.relative_to(skill)}: invalid JSON ({exc.msg} at line {exc.lineno})")

    oa = skill / "agents" / "openai.yaml"
    if oa.is_file():
        import yaml  # type: ignore

        data = yaml.safe_load(oa.read_text(encoding="utf-8")) or {}
        ui = data.get("interface", {}) if isinstance(data, dict) else {}
        if not ui.get("display_name"):
            errors.append("agents/openai.yaml: interface.display_name is required")
        sd = ui.get("short_description", "")
        if not 25 <= len(sd) <= 64:
            errors.append(f"agents/openai.yaml: short_description must be 25-64 characters (is {len(sd)})")
        if name and f"${name}" not in ui.get("default_prompt", ""):
            errors.append(f"agents/openai.yaml: default_prompt should mention ${name}")

    scripts = skill / "scripts"
    if scripts.is_dir():
        info["scripts"] = sorted(p.name for p in scripts.glob("*.py"))
        if run_help:
            for p in sorted(scripts.glob("*.py")):
                if p.name in NO_HELP:
                    continue
                proc = subprocess.run([sys.executable, str(p), "--help"], capture_output=True, timeout=60)
                if proc.returncode != 0 or b"usage" not in proc.stdout.lower():
                    errors.append(f"scripts/{p.name} --help failed (exit {proc.returncode})")
    return errors, warnings, info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("skill", type=Path)
    ap.add_argument("--run-help", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if not args.skill.is_dir():
        print(f"error: not a directory: {args.skill}", file=sys.stderr)
        return 2
    errors, warnings, info = validate(args.skill.resolve(), args.run_help)
    if args.json:
        print(json.dumps({"skill": str(args.skill), "errors": errors, "warnings": warnings, "info": info}, indent=2))
    else:
        for e in errors:
            print(f"ERROR {e}")
        for w in warnings:
            print(f"WARNING {w}")
        print(f"Summary: {args.skill.name}: {len(errors)} errors, {len(warnings)} warnings; "
              f"SKILL.md {info.get('lines')} lines, ~{info.get('body_tokens_approx')} body tokens, "
              f"description {info.get('description_chars')} chars")
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
