# Instructions for Claude

- The skill lives in `skills/roblox-game-remaker/`. Before committing, run:
  `python tools/validate_skill.py skills/roblox-game-remaker --strict --run-help` and
  `python -m unittest discover -s tests`.
- Skill evals (prompts with expected behavior, and a grader) live in `evals/` at the repository
  root, not in the skill: everything under `skills/roblox-game-remaker/` ships to users.
- Personal workflow rules (branching, pushing) go in `CLAUDE.local.md`, which is not committed.
