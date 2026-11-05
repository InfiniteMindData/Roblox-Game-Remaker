# Skill evals

Test cases for measuring whether the skill helps, following the Agent Skills evaluation guide
(agentskills.io, "Evaluating skill output quality"). They cover measurement accuracy, honesty
about inaccessible footage, rights handling, conventions (FOV), resuming a workspace, VR APIs,
assumptions without footage, honest test reports, and one prompt that should not trigger the skill.

1. Generate the input files: `python examples/demo/make_demo_footage.py --out evals/files/demo`
   (run from the skill directory; the files are not committed).
2. For each case in `evals.json`, run the prompt twice in a fresh session: once with this skill
   installed and once without it (or with the previous version). Save each final reply as
   `<workspace>/iteration-N/eval-<name>/<with_skill|without_skill>/response.txt`, plus any files
   produced.
3. Grade the pattern checks: `python evals/grade.py <workspace>/iteration-N/<variant> --all`
   (run it on each variant folder), then grade the remaining assertions by hand or with an LLM,
   quoting evidence from the outputs.
4. Compare the variants, and record tokens and duration per run. Fix the skill where it loses,
   and add a case for every real failure you see.
