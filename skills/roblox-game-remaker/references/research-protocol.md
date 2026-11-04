# Research protocol

Read this in Phase 1, before anything is measured or built. The goal is a pinned, cited
picture of the original game that the breakdown can reference by evidence ID.

## 1. Pin the target

Record in `remake/00-intake.md`:

- exact title, edition, platform, and **version or patch**. Physics, speeds and UI change
  between patches, and footage from different patches must not be mixed silently;
- input device of the reference (keyboard and mouse, gamepad, touch, VR), because aim assist,
  acceleration curves and UI differ by device;
- render settings visible in footage: resolution, aspect ratio, FOV setting, graphics preset,
  HUD scale option, motion blur;
- the slice being remade first (one level, one loop, one character).

## 2. Source hierarchy

Prefer higher tiers. When sources disagree, keep both in the ledger and resolve by measurement.

| Tier | Source | Typical yield |
|---|---|---|
| 1 | The game itself running (the user's own captures, the in-game UI) | Ground truth for that version |
| 1 | Official docs, manuals, patch notes, developer talks, official wikis | Stated values, rules, intent |
| 2 | Community technical resources: speedrun wikis, frame-data sites, datamined tables already published by the community | Precise numbers. Check the version and cross-check with footage |
| 3 | High-quality gameplay footage: 60 fps, no commentary overlay, stable camera | Measurement material |
| 4 | Fan wikis, forum posts, reviews | Leads only. Verify before use |

Do not datamine or decompile the game yourself, and do not tell the user to. Using numbers the
community has already published is fine when cited; extracting assets is not (see
`rights-and-policy.md`).

## 3. Evidence ledger (`remake/evidence.json`)

One entry per source, including inaccessible ones:

```json
{
  "id": "EV-007",
  "type": "video",
  "title": "Level 1 full run, 60 fps, no HUD mods",
  "source": "remake/media/level1_run.mp4",
  "version": "1.4.2",
  "accessed": "2026-11-04",
  "accessible": true,
  "analysis": "probe_video + extract_frames range 0-900 + motion_track jump",
  "rights": "user-captured reference, not for redistribution",
  "notes": "Container 60 fps; probe shows 0% duplicates"
}
```

- `type` is one of `video`, `screenshot`, `capture`, `doc`, `patch-notes`, `wiki`, `community-data`,
  `talk`, `forum`, `user-statement`, or `measurement`.
- `accessible: false` means you could not open it, for example a dead link, blocked network,
  unsupported codec, or a paywall. Such entries **cannot** back a `MEASURED` or `VERIFIED` value.
  `breakdown_check.py` enforces this.
- `user-statement` covers facts the user tells you ("the dash is 0.2 s"). Mark values from it as
  `VERIFIED` only if the user is the developer; otherwise mark them `OBSERVED` or `INFERRED`, and
  measure when possible.

## 4. Research checklist per category

Work through these and note "not applicable" where a category does not apply.

- **Controls:** every binding per device, hold versus tap, buffers, rebinding, sensitivity curves.
- **Movement and physics:** walk, run and sprint speeds, acceleration and deceleration, jump
  height and airtime, fall speed cap, air control, slopes, steps, swimming, climbing, knockback.
- **Camera:** mode, FOV and its convention, distance, height, offset, lag, collision, shake, zoom
  limits, lock-on.
- **Combat and interaction:** startup, active and recovery frames, hitboxes, i-frames, damage
  formulas, cooldowns, interaction ranges.
- **Characters:** proportions and height in meters, rig type, silhouettes, color palettes,
  accessories, variants.
- **Animation:** cycle lengths, transitions, idles, special moves, facial animation, root motion.
- **UI:** every screen and state, HUD layout per aspect ratio, fonts, icon sets, transition timings,
  sounds.
- **World:** layout, metrics (door width, step height, platform spacing), materials, lighting,
  time of day, weather, sky, fog.
- **VFX and audio:** particles, trails, flashes, screen effects, music cues, SFX timing, ducking.
- **Systems:** progression, economy, save data, AI states, spawning, difficulty, multiplayer
  rules.

## 5. Capture guide (give this to the user)

The best evidence is footage the user records for the purpose:

1. Record at the game's native frame rate, ideally 60 fps or more, at 1080p or higher, with
   **constant frame rate** (in OBS: Settings, Video, use an integer FPS value).
2. Turn off motion blur, film grain, chromatic aberration and dynamic resolution where the game
   allows it.
3. Show inputs: enable an on-screen input display, or say aloud when each button is pressed.
4. Record **test clips**, not only normal play:
   - stand still, then press forward until full speed, then release (acceleration and
     deceleration);
   - one jump from flat ground with the camera side-on if possible (apex and airtime);
   - camera rotation at fixed input (turn rate), and every zoom level;
   - each UI screen opening and closing, unedited;
   - each attack or ability, isolated, three times.
5. Put a known-size object in frame for scale (a doorway, the character, a crate), and
   tell us its real size if you know it.
6. Save files losslessly, or at a high bitrate, and do not trim with re-encoding tools that
   change the frame rate.
7. Take screenshots of every menu at native resolution, plus one at another aspect ratio to
   reveal anchoring.

## 6. When access fails

- Say exactly what failed (URL, error, codec) and record it as `accessible: false`.
- Do not summarize a video from its title, thumbnail, description or memory. That is not
  analysis.
- Offer alternatives: ask the user to download or capture the clip, to paste screenshots, or to
  describe the moment with timestamps.
- Continue with the categories that have evidence. List blocked questions in the breakdown as
  `UNKNOWN` with what would resolve them.

## 7. Output of this phase

- `remake/evidence.json` with every source.
- `remake/research-log.md`: questions, answers, conflicts, and decisions with evidence IDs.
- An updated `remake/00-intake.md` with the pinned version.
