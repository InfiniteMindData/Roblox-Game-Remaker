# Blender pipeline for Roblox

Read this when modeling, rigging, skinning or animating assets for the remake. All
requirements below come from the Roblox creator docs (modeling specifications, export
settings, character body specifications). Recheck them when the docs change.

## 1. Reference setup (accuracy first)

1. Collect orthographic-ish references: side-on and front-on frames from footage, screenshots
   from model viewers or galleries in the game, and the measured height from the breakdown.
2. In Blender, add the references as **Reference images** on front and side views, scaled so the
   character or object height matches the measured height in your chosen unit.
3. For perspective frames, match the camera: create a camera with the measured FOV (from
   `footage-analysis.md`), set the frame as the camera background, and align known geometry. Use
   it to check proportions, not to trace directly.
4. Block out primitives to the measured dimensions before any detail. Proportions carry likeness.

In homage mode, references inform proportions, scale and function. The model's design must be
original (see `rights-and-policy.md`).

## 2. Scale and axes

- Decide the unit mapping from `Config.World.StudsPerMeter` (`roblox-translation.md`).
- **FBX:** export with Transform ⟩ Apply Scalings set to **FBX Unit Scale**, with all other scale
  values at 1.0. This is Roblox's recommended way to keep the same scale.
- **glTF (`.gltf` or `.glb`):** Roblox imports glTF without the FBX scaling adjustments.
- For general exports the Roblox docs set **Forward = Z Forward** and **Up = Y Up**. Verify the
  orientation on the first import and record it.
- Apply transforms (Ctrl+A ⟩ All Transforms) before rigging. Bones must have rotation (0, 0, 0)
  and scale (1, 1, 1) in rest pose, and the root bone sits at (0, 0, 0).

## 3. Geometry limits and gates

| Requirement | Value |
|---|---|
| Triangles per mesh | at most **20,000** (avatar items have their own, lower budgets) |
| Topology | quads where possible, no n-gons, watertight, no zero-thickness surfaces |
| Materials | one material per mesh object on import; split by material when needed |
| Normals | consistent outward normals; inverted-hull outline shells deliberately flipped |
| Cages | `_InnerCage` and `_OuterCage` suffixes on the primary mesh name; do not change cage vertices or UVs |

## 4. Textures

- Formats for separately uploaded textures: `.png`, `.jpg`, `.tga`, `.bmp`; up to 4096×4096.
- PBR (`SurfaceAppearance`): Albedo RGB (24-bit), Normal RGB (**OpenGL** tangent space only),
  Roughness, Metalness and Emissive mask as single-channel 8-bit grayscale.
- In Blender, use **Path Mode: Copy** and **Embed Textures** in the FBX exporter so textures
  import with the mesh.
- Size textures by on-screen coverage. Roblox's baseline is 256×256 per 2×2×2-stud volume; a
  20×20-stud object uses about 1024×1024.
- Bake normal and AO detail from high-poly sculpts. Keep lighting out of the albedo unless the
  original's art style is hand-painted lighting.

## 5. Rigging and skinning

- At most **4 bone influences per vertex**; no influences on the Root bone; keep weights
  symmetric where the design is symmetric.
- **Standard R15 hierarchy** for humanoids (names are exact):
  `Root > HumanoidRootNode > LowerTorso > UpperTorso > Head`, `LeftUpperArm > LeftLowerArm > LeftHand`,
  `RightUpperArm > RightLowerArm > RightHand` under UpperTorso, and
  `LeftUpperLeg > LeftLowerLeg > LeftFoot`, `RightUpperLeg > RightLowerLeg > RightFoot` under
  LowerTorso. LowerTorso and Root at (0, 0, 0). Export in I-pose, A-pose or T-pose.
- Advanced R15 rigs may add up to 37 optional named bones (fingers, shoulders, spine). Then insert
  `HumanoidRigDescription` and, for hands, `DigitsRigDescription` after import.
- Non-humanoids: any hierarchy works. Animate with `AnimationController` + `Animator`.
- In the FBX exporter, turn **Add Leaf Bones off**.

## 6. Animation export

- Roblox imports **one animation track per FBX**. Export each clip as its own file.
- Turn **Bake Animation on** only for files that carry animation. Turn it off for static meshes.
- Key at the target frame rate. The Studio Animation Editor shows 30 fps by default; keys at
  other rates are resampled, so check marker frames after import.
- Import with Animation Editor ⟩ ⋯ ⟩ Import ⟩ From FBX Animation, select the rig first, then
  publish and record the asset ID in `Config.Animation`.
- Root motion: keep clips in place and move the character from code (see `animation-analysis.md`).

## 7. The bundled export script

`scripts/blender_roblox_export.py` runs **inside Blender** (it needs `bpy`). It checks the
selection (or all meshes) against the limits above, then exports with the documented settings
and writes a JSON report.

```bash
blender -b asset.blend --python scripts/blender_roblox_export.py -- \
  --out exports/crate.fbx --report exports/crate.report.json
blender -b hero.blend --python scripts/blender_roblox_export.py -- \
  --out exports/hero_run.fbx --animation --r15 --report exports/hero_run.report.json
blender -b prop.blend --python scripts/blender_roblox_export.py -- --out exports/prop.glb --format glb
```

Checks: triangle count per mesh, n-gons, non-manifold edges, zero-area faces, unapplied object
transforms, influence count per vertex, root-bone influences, bone rest rotation and scale,
R15 bone names and hierarchy (`--r15`), and cage naming. The script exits with status 1 on
errors without exporting, unless you pass `--force`.

## 8. Roblox Blender plugin

The official Roblox Blender plugin (an open-source Open Cloud client) can upload directly from
Blender to the user's Roblox account. Its setup needs the user's own sign-in. Never handle the
user's credentials or API keys yourself; ask them to do the sign-in step.

## 9. Import and verify in Studio

1. Import with the Importer (File ⟩ Import). Check the triangle counts, warnings, scale and
   orientation in the preview.
2. Compare the dimensions in Studio with the breakdown values (Size in studs).
3. Put the asset into its matched shot and run `visual_compare.py` for silhouette (edge IoU) and
   palette.
4. Record the asset in `remake/asset-manifest.json` with its source and license.
