# Skill evals

Test cases for measuring whether the skill helps, following the Agent Skills evaluation guide
(agentskills.io, "Evaluating skill output quality"). They cover:

| Cases | What they test |
|---|---|
| 1, 4 | Measurement and conventions: a side-on jump; horizontal versus vertical FOV |
| 10, 11 | Third-person perspective: solving FOV and pitch from marked lines; a run speed through the ground plane, not one px-per-stud scale |
| 12 | Degraded footage, where the right answer is a wide uncertainty and a refusal to promise more precision |
| 13 | A drop rate from too few samples: an interval, never "15%", and how many more trials are needed |
| 14, 15, 16, 18 | The newer tools: fitting a UI tween, comparing a build's jump over time, tuning a replacement sound, scoring an iteration for regressions |
| 17 | Input latency without a visible input: say it cannot be measured |
| 2, 3, 7, 8 | Honesty and rights: inaccessible footage, asset ripping, no footage, honest test reports |
| 5, 6 | Resuming a workspace; Quest 3 APIs |
| 9, 19 | Prompts that should not trigger the skill (DataStore, a generic Roblox scripting question) |

These live at the repository root, outside the skill folder, so they do not ship with the skill.
Run the commands below from the repository root.

1. Generate the input files with the `setup` command in `evals.json` (the files are not
   committed):
   `python skills/roblox-game-remaker/examples/demo/make_demo_footage.py --out evals/files/demo --only jump,run,perspective,hud,degraded,extras`.
2. For each case in `evals.json`, run the prompt twice in a fresh session: once with this skill
   installed and once without it (or with the previous version). Save each final reply as
   `<workspace>/iteration-N/eval-<name>/<with_skill|without_skill>/response.txt`, plus any files
   produced.
3. Grade the pattern checks: `python evals/grade.py <workspace>/iteration-N/<variant> --all`
   (run it on each variant folder), then grade the remaining assertions by hand or with an LLM,
   quoting evidence from the outputs.
4. Compare the variants, and record tokens and duration per run. Fix the skill where it loses,
   and add a case for every real failure you see.
