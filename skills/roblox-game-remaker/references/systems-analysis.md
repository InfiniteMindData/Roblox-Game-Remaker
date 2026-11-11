# Systems analysis: enemies, spawns, drops, cooldowns, economy

Read this when a breakdown entry is in `AI`, `SYS` or `MECH` and its numbers come from what
happens over time rather than from one motion: enemy behavior, spawn timing, drop rates,
cooldowns, damage, economy and progression. Movement and camera are in
`movement-camera-feel.md`; footage handling is in `footage-analysis.md`.

These systems are hidden: the game runs a timer, a state machine or a random roll, and the
footage shows only outcomes. Measuring them means logging outcomes into a table, then letting
`scripts/event_stats.py` say what the table supports and how far.

## 1. Log events into a table

One CSV per clip or session, one row per event, written while stepping through frames:

```csv
frame,event,entity,loot,xp
1204,spawn,spawner_A,,
1207,kill,slime_03,common,
1208,drop,slime_03,,
1354,spawn,spawner_A,,
```

- `frame` is the source frame index from `extract_frames.py` file names (`f001204_t20.066667.png`),
  or `t` in seconds. Pass `--fps` to convert, or `--manifest` for exact per-frame times on
  variable-frame-rate clips.
- `event` is a short verb or a state name. Decide the definition once and write it in the
  breakdown: "spawn = first frame the enemy is visible", "drop = first frame the item appears".
  The same visual cue every time matters more than which cue.
- `entity` separates independent timers (two spawners, three enemies). Intervals and state
  sequences are computed per entity.
- Add a column for any outcome you want a rate of (`loot`, `crit`, `hit`) and for numbers read
  from the UI (`xp`, `damage`, `price`). Read numbers with `frame_zoom.py`, never by squinting at a
  full frame.
- Log every occurrence in the range, including the boring ones. Skipping "normal" kills makes a
  drop rate wrong.
- Keep the table next to its evidence (`remake/systems/<name>.csv`) and add the clip with
  `ledger.py add-evidence ... --analysis "event table remake/systems/<name>.csv"`.

Contact sheets (`contact_sheet.py --every N`) find the region of interest quickly; log from the
individual frames.

## 2. Intervals: spawn timers, attack rhythm, cooldowns

```bash
python scripts/event_stats.py remake/systems/wave1.csv --fps 60 --intervals spawn --by entity --out remake/systems/wave1.json
```

- Each gap is known to about one frame (each event to half a frame either side). The tool
  reports the mean with a Student-t interval combined with that quantization, the spread, and
  the range.
- `pattern: fixed` means the gaps vary by no more than one frame: a fixed timer. Build it as a
  constant with the measured value.
- `pattern: variable` means a random or state-dependent interval. Look at the range and the
  spread before assuming a uniform random wait; check whether the gap depends on something you
  can see (distance to the player, the previous attack). Build the distribution, not the mean.
- **Cooldowns:** a cooldown is at most the shortest gap observed, and equals it only when the
  input was pressed as fast as possible. Ask for (or record) footage that spams the ability, and
  log the input frames too if an input overlay is visible.
- Sample size: the mean's interval shrinks with the square root of the number of gaps. Ten gaps
  give a usable mean; about 30 are needed before the spread itself is trustworthy.

## 3. Rates: drops, crits, procs, spawn variants

```bash
python scripts/event_stats.py remake/systems/loot.csv --fps 60 --rate drop/kill --rate kill:loot=rare --plan-halfwidth 0.05
python scripts/event_stats.py --counts 3/20
```

A rate seen k times in n trials is a range, never a percentage. 3 drops in 20 kills is
"0.032 to 0.379 (95%, exact binomial)", which is compatible with anything from a 1-in-30 to a
1-in-3 drop. The tool prints k of n, the exact (Clopper-Pearson) interval and the Wilson
interval, and never the bare fraction.

Trials needed for a 95% interval of a given half-width (from `trials_for_halfwidth`, exact):

| True rate about | ± 0.10 | ± 0.05 | ± 0.02 |
|---|---|---|---|
| 0.05 | 26 | 101 | 518 |
| 0.15 | 56 | 224 | 1315 |
| 0.50 | 106 | 415 | 2453 |

Zero successes is not a zero rate: 0 of 20 still allows up to 0.168.

- A rate stated in the game's own UI, patch notes or the developer's docs is `VERIFIED`; use the
  footage to check it, not to replace it.
- Rates that depend on history (pity timers, pseudo-random distributions, bad-luck protection)
  show up as streaks that are shorter than independent rolls would give. Testing that needs
  hundreds of trials; until then, record the dependency as an open question.
- In the breakdown, write the interval: `- value: drop_rate = 0.21 ± 0.17 probability (3 of 20;
  95% interval 0.032–0.379)`. The ledger stores the midpoint and half-width with `successes`,
  `trials` and `interval`. When the interval is wider than about 0.2, the build value inside it is
  a choice: label it `ASSUMED` in Config, cite the `MS` entry, and say so to the user.

## 4. State machines: enemy and boss behavior

```bash
python scripts/event_stats.py remake/systems/boss.csv --manifest remake/frames/boss/manifest.json \
  --states idle,windup,attack,recover,stagger --by entity
```

- Name the states you can see change (pose, color flash, sound cue, movement mode) and log the
  first frame of each. The tool counts transitions (`windup -> attack: 6 of 6`) and dwell times
  per state.
- A transition seen once among many is a rare branch or a logging mistake: confirm it on the
  frames before building it.
- Triggers: when a transition seems to depend on the player (distance, facing, line of sight),
  log the player's and enemy's positions at those frames. Third-person footage needs the ground
  plane (`camera_solve.py ground --points`) to turn them into studs.
- Telegraphs (windup length) and recovery windows are the numbers players feel most; measure
  them to a frame and give them `accept:` tests in frames.

## 5. Economy and progression

```bash
python scripts/event_stats.py remake/systems/levels.csv --fps 60 --series level_up:xp
```

- Numbers shown in the game's UI (XP to next level, prices, rewards) are `VERIFIED` from a
  screenshot or capture; log them with the frame they came from.
- `--series EVENT:column` fits the value against its occurrence number (level 1, 2, 3, ...) with
  linear, quadratic, exponential (constant ratio) and power curves. With fewer than about six
  points several curves fit equally well; the tool says so. Do not extrapolate a fitted curve far
  past the observed levels without saying it is `INFERRED`.
- Damage and health: read the numbers the UI shows for several known inputs (weapon, level,
  armor) and reconstruct the formula; keep each data point in the table.

## 6. Recording and building

```bash
python scripts/ledger.py import remake remake/systems/loot.json --evidence EV-00N
```

- `event_stats` writes a `measurements` block: interval means, dwell times and rates with their
  uncertainties and sample sizes. `ledger.py import` gives them `MS` IDs. They are Config inputs,
  so `ledger.py targets` does not turn them into harness targets.
- Put timers, cooldowns and rates in Config with their `MS` IDs, and roll them on the server:
  spawns, drops, damage and currency are server-owned (see `luau-architecture.md`). For
  reproducible tests, seed a `Random.new(seed)` and draw with `Random:NextNumber()` or
  `Random:NextInteger(min, max)`.
- What footage cannot settle: hidden seeds, formulas outside the observed range, server rules
  never triggered on camera. Label those `INFERRED` or `ASSUMED`, list them as open questions,
  and ask the user for documentation or longer recordings.
