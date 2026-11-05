# Instructions for Claude

- **Always commit and push to `main`.** The owner wants every change on `main`, not on feature
  branches.
- The skill lives in `skills/roblox-game-remaker/`. Before pushing, run:
  `python tools/validate_skill.py skills/roblox-game-remaker --strict --run-help` and
  `python -m unittest discover -s tests`.
