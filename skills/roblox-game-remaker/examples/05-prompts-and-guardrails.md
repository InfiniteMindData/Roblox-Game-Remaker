# Example requests and expected behavior

How an agent using this skill should respond. "Game X" stands for whatever game the user names.

## "Recreate Game X in Roblox, 1:1."

1. Run `scripts/doctor.py` and check for image viewing and Studio MCP.
2. Intake: ask only what is missing: the version or patch, the reference media they can supply,
   who owns the IP, the vertical slice, target devices, and the fidelity tier.
3. Explain the rights modes in two sentences. If the user does not own or license Game X, the
   remake recreates mechanics, timing and feel, with original names, characters, art and audio
   (homage mode).
4. Run `breakdown_init.py`, research and record evidence, then ask for test captures (the capture
   guide in `references/research-protocol.md`).
5. Do not write gameplay code until the breakdown covers the slice.

## "Here's a YouTube link, analyze the jump frame by frame."

- First make the per-observable feasibility table from `references/research-protocol.md`:
  scale, camera geometry/motion, visible inputs, content fps, and aspect ratios. A public clip
  rarely identifies all requested quantities. Offer one bounded original greybox/HUD slice.
- If permitted tools can fetch and decode it: preserve local provenance, probe, extract and
  measure only identifiable quantities. The bundled scripts do not download URLs.
- If you cannot (the network is blocked, there is no download tool, or the platform's terms
  forbid it), say so plainly: "I couldn't access that video, so I haven't analyzed it." Record it
  in `evidence.json` with `"accessible": false`. Ask the user to download or record the clip and
  put it in `remake/media/`.
- Never describe the jump from memory, the title or the thumbnail as if you had measured it.

## "I can't send footage. Just make the jump feel like Game X."

Proceed with clearly labeled `ASSUMED` values (for example "typical platformer: about 0.4 s
rise, falls faster"). List them for the user, make them easy to tune in `Config`, and say that
1:1 needs measurement. Ask for explicit consent for the bounded slice, then persist who,
when and why with `ledger.py accept-gap` for each affected entry/phase. Status advances
provisionally, not as measured verification; strict checking still reports assumptions.

## "Extract the models and music from the game files and put them in Roblox."

Decline that part: extracting and uploading someone else's assets violates their rights and
Roblox's Terms of Use (content can be removed and accounts actioned). Offer what does work:
measure the originals for proportions, scale and timing; build original models in Blender to
those measurements; use original or licensed audio; or apply for an IP license through Roblox's
licensing program. Then continue with the rest of the remake.

## "Use the real logo and title, it's just a fan game."

Fan intent does not grant rights. Use an original title and logo unless the user owns or has
licensed the IP. Recreating the gameplay feel is fine.

## "It's my own game from Unity; port it."

Own-IP mode: the user's source assets can be reused. Ask for the project's numbers first
(Rigidbody settings, character controller parameters, camera FOV and its convention, UI canvas
scaler settings) and record them as `VERIFIED` (`type: doc`). Still measure footage of the
original build to catch behavior that the numbers alone do not show.

## "Is it done? Did you test it?"

Report by level: Executed (Studio Output or a log saved), Executed by user, Statically checked
(StyLua, Selene, Rojo build, Lune tests), Prepared not run, or Unverified. Give the numbers from
`measure_compare.py` and `visual_compare.py`, plus the list of remaining gaps.
