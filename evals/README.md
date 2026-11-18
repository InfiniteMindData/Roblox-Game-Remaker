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
   `<workspace>/iteration-N/<with_skill|without_skill>/eval-<name>/response.txt`, plus any files
   produced.
3. Run wording lint only: `python evals/wording_lint.py <workspace>/iteration-N/<variant> --all`
   (run it on each variant folder). This matches vocabulary only, not tool execution or outcomes.
   Grade the remaining assertions by hand or with an LLM,
   quoting evidence from the outputs.
4. Compare the variants, and record tokens and duration per run. Fix the skill where it loses,
   and add a case for every real failure you see.

## Outcome artifacts (separate from wording lint)

No matched with/without-skill trials have been run; the 19 prompts and their wording checks are
not evidence of benefit. The old `grade.py` name is a deprecated alias for `wording_lint.py`.
In the audit, all 47 regex checks accepted replies explicitly admitting fabrication. Wording
lint intentionally cannot establish whether tools ran. Never report its matches as benchmark
passes.

For a numerical artifact trial, the harness/maintainer must provide an independent, held-out
expectations file **before** running the agent. Do not let the agent write the grading spec.
`outcomes-jump.json` is an example for the demo's 8-stud / 0.4-second jump, not a completed trial:

```bash
python evals/grade_outcomes.py <workspace>/iteration-N/with_skill/eval-measure-jump --expectations evals/outcomes-jump.json
```

Use the actual eval name/directory. Each run saves `remake/breakdown.md`, `evidence.json`,
`measurements.json`, local retained sources and the files named in the spec. The grader requires:
- a breakdown passing `breakdown_check` **strictly**, not accepted provisional gaps;
- nonempty ledgers, measurements backed by accessible evidence whose source files exist;
- every declared artifact is a nonempty file inside the run directory (no escaping symlinks);
- one measurement per expected metric, correct unit, finite value within independently set
  tolerance, and finite nonnegative uncertainty no larger than that tolerance.

Local source paths are run-directory-relative. Preserve downloaded/captured sources locally;
URL-only citations fail this network-free check. Non-numeric measurements (colors, for example)
remain checked by the breakdown validator; use a separate independently defined scorer for
those. Add per-case specs for other synthetic observables; no universal numerical spec is
claimed for rights refusals, inaccessible media or non-trigger cases. Record those separately,
with human review, rather than manufacturing a numeric pass.

A response-only “FABRICATED. No tools ran” now fails outcome grading even if wording lint
matches every term. This still cannot prove authorship, real tool execution, video content,
Studio fidelity, or resistance to an adversary forging internally consistent files. Retain
transcripts and have the harness capture tool logs; manually review source content and provenance.
An actual benchmark additionally needs isolated matched sessions, Studio runtime checks,
held-out owned-IP references, blind playtesting, and time/token/cost records including failures.
