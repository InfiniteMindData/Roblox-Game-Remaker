# Graphics, lighting and materials

Read this for `ENV` and `VFX` entries and whenever a matched shot fails on color, brightness
or mood. Work from matched shots: the same camera, the same time of day, the same subject.

## 1. Establish the target look

For each key shot in `remake/shots.json`, record:

- the dominant palette (`palette_extract.py`) of sky, ground, key surfaces, shadows and skin;
- **shadow color and hardness**, which reveal ambient color and light size;
- the **sun direction**: shadow direction gives azimuth, and shadow length over object height
  gives elevation (`elevation = atan(height / shadow_length)`);
- fog: the distance at which landmarks lose contrast, and the fog color (sample the horizon);
- bloom: halos around bright sources, and how big they are;
- grading: saturation, contrast, and tint in highlights and shadows;
- material response: specular highlights, roughness, metal, emissive surfaces.

## 2. Map to Roblox lighting

| Target trait | Roblox controls |
|---|---|
| Realistic, physically lit | `Lighting.LightingStyle = Realistic`, `PrioritizeLightingQuality = true` |
| Flat, stylized, soft shadows | `LightingStyle = Soft` (with `PrioritizeLightingQuality` enabled it uses shadow maps) |
| Sun position | `Lighting.ClockTime` plus `GeographicLatitude`; compare `Lighting:GetSunDirection()` with the measured direction |
| Overall exposure | `Lighting.ExposureCompensation` (tune first), then `Brightness` |
| Shadowed-area color | `Ambient` (indoors and occluded areas), `OutdoorAmbient` |
| Sky-light contribution | `EnvironmentDiffuseScale`, `EnvironmentSpecularScale` |
| Shadow softness | `ShadowSoftness`, `GlobalShadows` |
| Distance haze | `Atmosphere` (`Density`, `Offset`, `Haze`, `Glare`, `Color`, `Decay`), or `FogStart`, `FogEnd` and `FogColor` when no Atmosphere exists |
| Tonemapping | `ColorGradingEffect.TonemapperPreset` (`Default` is post-2019 vivid; `Retro` is the pre-2019 look) |
| Grading | `ColorCorrectionEffect` (`Brightness`, `Contrast`, `Saturation`, `TintColor`) |
| Glow | `BloomEffect` (`Intensity`, `Size`, `Threshold`) |
| Depth of field | `DepthOfFieldEffect` |
| God rays | `SunRaysEffect` |
| Sky | `Sky` with skybox textures (original or licensed art), sun and moon textures, star count |

`Lighting.Technology` is deprecated. Use `LightingStyle` and `PrioritizeLightingQuality`.

`LightingPreset.apply(Config.Lighting)` in the template sets all of these from one table and
creates or updates the effect instances under `Lighting` (named `Remake_*`) idempotently.

## 3. The lighting-match loop

1. Put the camera on the shot with `ShotCamera` (or MCP `screen_capture` with a camera position and
   look-at), with UI hidden and the same time of day.
2. Capture, then `python scripts/visual_compare.py pair ref.png rec.png --out remake/diff/shot03`.
3. Read `lab_shift` in the report:
   - `dL` < 0 (recreation darker): raise `ExposureCompensation` in steps of about 0.25;
   - `db` > 0 (recreation more yellow) or `da` (red/green): adjust `ColorCorrectionEffect.TintColor`,
     or the light and ambient colors;
   - `chroma_ratio` < 1 (recreation less saturated): raise `Saturation`;
   - `contrast_ratio` < 1: raise `Contrast`, or lower `Ambient` and `OutdoorAmbient`.
4. Use the per-cell heatmap to localize errors: sky only (Sky/Atmosphere), shadows only (Ambient),
   distance only (fog/Atmosphere), a single material (SurfaceAppearance or MaterialVariant).
5. Change one group of properties per iteration, re-capture, and log it. Stop when the tier
   threshold is met or the remaining difference is attributable to assets (homage mode).

The `hints` list in the report is heuristic. Always confirm a change by re-measuring.

## 4. Materials

- Roblox built-in materials map well to generic surfaces. Use a `MaterialVariant` (custom
  ColorMap, NormalMap, MetalnessMap, RoughnessMap, with `StudsPerTile`) to match the original's
  tiling scale, which you can measure as the repeat distance of a texture pattern in studs.
- Unique assets use `SurfaceAppearance` on a `MeshPart`: ColorMap (sRGB), NormalMap (OpenGL,
  tangent space), MetalnessMap and RoughnessMap (single channel), plus an emissive mask with
  `EmissiveStrength` and `EmissiveTint` for glowing parts. `AlphaMode` controls transparency
  handling.
- Texel density: Roblox's guidance is 256×256 per 2×2×2-stud volume as a baseline, up to 4096².
  Match the original's apparent sharpness at the gameplay camera distance, not its source files.

## 5. Environment building for 1:1 metrics

- Build a **metric greybox first**: platform sizes, gaps, heights and corridor widths in studs
  from the breakdown, and check jumps and sightlines before any art.
- Use a 1-stud or 0.25-stud grid with Snap to Grid. Record key dimensions in `ENV` entries.
- Terrain: voxels are 4×4×4 studs. Use Terrain for organic ground and water; use parts or meshes
  where edges must be exact.
- Replace greybox with art incrementally and re-run the matched-shot comparisons after each pass.

## 6. VFX

For each `VFX` entry measure lifetime (frames), emission count or rate, start and end size,
color over life, speed, spread, gravity and drag, plus flipbook frame count and rate when the
effect is a sprite animation.

| Effect type | Roblox |
|---|---|
| Sprite or flipbook particles | `ParticleEmitter` with `FlipbookLayout`, `FlipbookFramerate`; `Size`, `Transparency` and `Color` as sequences matched to the measured curves |
| Trails | `Trail` (lifetime, width scale, texture) |
| Beams and lasers | `Beam` (texture, `TextureSpeed`, curve) |
| Flashes and glows | `PointLight` or `SpotLight` with a short tween, emissive mesh, `BloomEffect` |
| Shockwaves and rings | A mesh with a scale and transparency tween |
| Outlines and hover glows | `Highlight` (the client shows at most 255 at once), or shell meshes |

Trigger timing comes from animation markers, never from `task.wait` guesses.

## 7. Performance guardrails

- Measure the frame time on the lowest target device, and on Quest when VR is in scope.
- Transparent overdraw (glass, many particles, decals) is the usual cost on mobile and VR.
- Large `SurfaceGui` counts are costly; prefer textures where the content is static.
- Prefer fewer, larger meshes for static scenery; use streaming for big worlds.
