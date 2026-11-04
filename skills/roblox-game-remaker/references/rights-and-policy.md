# Rights, licensing and Roblox policy

Read this in Phase 0, and again before uploading or publishing anything. This is a
production practice guide, not legal advice. When rights are unclear or the project is
commercially significant, tell the user to get a qualified review.

## 1. What Roblox says

- From the Roblox IP licensing docs: "Publishing content on Roblox that uses someone else's IP
  rights without permission violates the Roblox Terms of Use and might result in the removal of
  the content and your Roblox account."
- Roblox runs an **IP licensing program**: creators browse the Licenses catalog (Creator Hub ⟩
  Explore ⟩ Licenses), request a full-game or in-game-sales license from a rights holder, and
  follow that license's revenue share, content standards and brand guidelines. The game must be
  public before requesting.
- Animation Capture inputs and uploaded assets must also follow the Roblox Community Standards
  and Terms of Use.

## 2. Rights modes (choose one in Phase 0)

| Mode | When | What may be reproduced |
|---|---|---|
| **Own IP** | The user (or their studio) owns the original game | Everything they own: names, characters, art, audio, levels |
| **Licensed IP** | A license exists (Roblox licensing program or a direct agreement) | Whatever the license grants, within its brand guidelines |
| **Homage** | No rights to the original's expression | Mechanics, rules, timing, physics feel, camera behavior, UI *layout patterns*, genre conventions. All names, characters, art, models, textures, music, SFX, logos, fonts and level designs that are distinctive expression must be **original** or properly licensed replacements |

In homage mode, the remake should be recognizably *in the style of* the original's design
while being its own work: different title, characters, world and assets. Say this plainly to
the user at intake. It does not reduce measurement work, because feel, timing and layout are
still measured 1:1.

Do not let an "it's just for personal use" or "it's a parody" framing switch the mode. If the user
asserts ownership or a license, record that assertion in the intake (who, what, where documented).

## 3. Hard rules (all modes)

1. **No asset ripping.** Do not extract, decompile, datamine or convert models, textures, audio,
   animations or code from the original's files, and do not guide the user to. Reference footage
   and screenshots are for **study and measurement**, not for tracing into shipped assets.
2. **No uploading third-party copyrighted media** (music, sound effects, textures, logos, fonts)
   without a license that permits it on Roblox.
3. **No misleading branding.** Do not use the original's name, logo or trade dress to market the
   remake unless licensed, and do not imply official endorsement.
4. **Marketplace assets:** check each Creator Store asset's terms and inspect it for scripts before
   use, and record it in the manifest.
5. **AI-generated assets** (Studio `generate_mesh` or `generate_material`, other generators): treat
   them as new assets with provenance records. Do not prompt them to reproduce protected designs
   or living artists' styles by name.
6. **Fonts:** use Roblox-available fonts, or fonts whose license permits embedding in the game.
7. **Footage handling:** keep the user's reference footage in `remake/media/` locally, and do not
   upload it to Roblox or redistribute it.

## 4. Asset provenance manifest (`remake/asset-manifest.json`)

One record per shipped asset:

```json
{
  "id": "AST-031",
  "name": "Courier_Body",
  "roblox_asset_id": "rbxassetid://0",
  "type": "mesh",
  "origin": "original",
  "author": "user (Blender)",
  "source_files": "art/courier/courier_body.blend",
  "license": "project-owned",
  "references_used": ["EV-012", "EV-019"],
  "generated": false,
  "notes": "Proportions from MS-021; design original (homage mode)"
}
```

`origin` is one of `original`, `licensed`, `roblox-provided`, `creator-store`, `generated`, or
`user-owned-ip`. The delivery report includes a manifest summary.

## 5. Handling user requests that cross the line

When asked to rip assets, use the original's name or logo without a license, or upload copyrighted
music:

- Decline that specific part briefly, and explain the risk (content removal, account action).
- Offer the faithful alternative: measure and recreate the feel, build original look-alike-in-
  spirit assets, find licensed or Roblox-provided audio, or apply for an IP license.
- Continue with everything else.
