# Game breakdown specification

Read this in Phase 3. The breakdown (`remake/breakdown.md`) is the contract for the remake:
everything that gets built appears here first, with evidence, numbers, a Roblox plan and an
acceptance test. `scripts/breakdown_check.py` parses this exact format, so keep it.

## File set in `remake/`

| File | Purpose |
|---|---|
| `00-intake.md` | Game, version, platform, rights mode, scope, devices, fidelity tier |
| `evidence.json` | Source ledger (`EV-###`), see `research-protocol.md` |
| `measurements.json` | Measured values (`MS-###`), see `footage-analysis.md` |
| `breakdown.md` | This specification |
| `shots.json` | Matched reference shots for visual comparison |
| `targets.json` | Numeric targets and tolerances for `measure_compare.py` |
| `diff-log.md` | Verification iterations |
| `delivery-report.md` | Final report |
| `asset-manifest.json` | Provenance of every shipped asset |

`scripts/breakdown_init.py` creates all of them from `assets/templates/`.

## Entry format

Each entry is a level-3 heading with an ID and a title, followed by `- key: value` lines:

```markdown
### MOVE-002: Standing jump
- status: MEASURED
- priority: P0
- evidence: EV-007, MS-014, MS-015
- value: apex_height = 7.4 ± 0.3 studs
- value: rise_time = 0.383 ± 0.017 s
- value: fall_time = 0.300 ± 0.017 s
- roblox: Config.Movement.JumpApex/RiseTime/FallTime -> MovementFeel computes jump velocity and rise/fall gravity; Workspace.Gravity = rise gravity
- accept: measure_compare jump_apex within ±0.3 studs; rise_time and fall_time within ±1 frame (0.017 s)
- depends: MOVE-001
- notes: Fall faster than rise, so the original uses fall-gravity scaling.
```

### Keys

| Key | Required | Rule |
|---|---|---|
| `status` | always | One of `VERIFIED`, `MEASURED`, `OBSERVED`, `INFERRED`, `ASSUMED`, `UNKNOWN` |
| `evidence` | all but `ASSUMED` and `UNKNOWN` | Comma-separated `EV-###` and `MS-###` IDs that exist in the ledgers |
| `value` | `MEASURED` needs at least one | `name = number ± uncertainty unit`; repeat the line for each value |
| `roblox` | always | How it will be built. `TBD` gives a warning |
| `accept` | always | A checkable test with a tolerance |
| `open` | `UNKNOWN` | The open question and what evidence would resolve it |
| `priority` | optional | `P0` (slice-critical) to `P3` (nice to have) |
| `depends` | optional | IDs this entry relies on |
| `notes` | optional | Free text |

### Status rules (enforced by the checker)

- `VERIFIED` must cite at least one accessible `EV` of type `doc`, `patch-notes`, `talk`,
  `screenshot`, `capture` or `user-statement`.
- `MEASURED` must cite at least one `MS` whose own evidence is accessible, **or** an accessible
  `video`, `screenshot` or `capture` `EV`, and it must have at least one `value` with `±`.
- Nothing may cite an `EV` with `"accessible": false` as its only support.
- `ASSUMED` entries are listed in the summary. Under `--strict` they count as warnings, which
  fail the check.
- `UNKNOWN` entries need an `open:` line.

## Categories and ID prefixes

Every category needs at least one entry, or a coverage line declaring it not applicable.

| Prefix | Category | Must capture |
|---|---|---|
| `CTRL` | Controls and input | Bindings per device, hold/tap, buffers, deadzones, sensitivity, rebinding |
| `MOVE` | Movement and physics | Speeds, acceleration, jump, gravity, air control, slopes, steps, collisions, knockback |
| `CAM` | Camera | Mode, FOV and its convention, offset, distance, lag, collision, shake, zoom |
| `MECH` | Mechanics and rules | Combat frames, damage, interactions, pickups, win/lose rules, timers |
| `CHAR` | Characters | Height, proportions, silhouette, palette, variants, rig needs |
| `ANIM` | Animations | Cycle frames, transitions, markers, priorities, procedural layers |
| `UI` | UI screens and HUD | Every screen and state, layout boxes, fonts, colors, tween timing, navigation |
| `ENV` | Environment and levels | Layout metrics, materials, lighting, sky, fog, time of day, streaming needs |
| `VFX` | Visual effects | Particles, trails, flashes, post effects, screen effects, timing |
| `AUD` | Audio | Music cues, SFX list and timing, ducking, spatialization |
| `AI` | NPC and enemy behavior | States, perception ranges, timings, pathing |
| `SYS` | Systems | Progression, economy, saves, multiplayer, matchmaking, settings |
| `VR` | VR support | Locomotion, turning, hands, UI, haptics, comfort (only when VR is in scope) |

Declare non-applicable categories in a `## Coverage` section:

```markdown
## Coverage
- n/a: AI (no NPCs in the vertical slice)
- n/a: VR (flat-screen only, agreed in intake)
```

## How detailed is "complete"?

The test: could another developer build this entry to the acceptance tolerance from the
breakdown alone, without watching the footage? If not, add values, frames or references.

Per category, aim for:

- **CTRL:** a full binding table for each target device. On Roblox, plan the
  `InputContext` / `InputAction` / `InputBinding` set (see `roblox-translation.md`).
- **MOVE:** every number a designer would expose: speeds, times, heights, angles, plus
  interactions such as jumping on a slope or landing on a moving platform.
- **CAM:** enough to place the camera exactly: offset vector, pitch limits, distance, FOV, and
  damping as spring parameters.
- **UI:** one entry per screen, plus one per reusable widget. Boxes in reference pixels with the
  reference resolution, colors, fonts (and licensing status), animation timing per state.
- **ANIM:** cycle length and keypose table, as in `animation-analysis.md`.
- **ENV:** a metric map (top-down sketch or grid with stud dimensions), material list, lighting
  values.

## Summary block

End the breakdown with the summary the checker prints (counts per status and category, open
questions, assumptions), then present it to the user before building at scale.
