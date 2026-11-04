# Sharp edges

Each entry: **symptom → cause → fix**. Read this when something "almost matches", and before
delivery.

## Measurement traps

| Symptom | Cause | Fix |
|---|---|---|
| Timings consistently off by about 2× frame precision | 60 fps container with 30 fps content (duplicate frames) | `probe_video.py --dupes`; count at `effective_fps` |
| Timings drift over long clips | Variable frame rate recording | Use the `pts_time` values from the manifests, not `index / fps` |
| Speeds differ between clips | Perspective: the subject moved toward or away from the camera, or the camera zoomed | Side-on test clips; `--anchor-bbox`; per-clip `--px-per-unit` |
| Jump apex varies by 10–20% between measurements | Tracked a body part that animates (hands, hair) | Track the feet or the root region; average 3 or more jumps |
| Colors don't match any sampled value | Compression, tonemapping or HDR capture | Sample bigger flat regions over several frames; capture in SDR |
| FOV feels wrong despite the "same" number | Horizontal versus vertical convention, or a different aspect ratio | `remake_calc.py fov` with explicit `--aspect` |
| UI misplaced on other screens | Anchoring rule unknown | Capture a second aspect ratio; use the anchors that `ui_measure.py` derives |

## Roblox physics and character

| Symptom | Cause | Fix |
|---|---|---|
| Everything falls too fast or too slow | Real-world gravity entered in m/s² as studs/s² | Convert units; derive gravity from apex and airtime |
| Jump height ignores your value | `UseJumpPower` true (the default) while setting `JumpHeight` | Set `StarterPlayer.CharacterUseJumpPower = false` (Bootstrap does this) |
| Props fall at the wrong rate after a gravity change | `Workspace.Gravity` is global | Keep the world physical; shape the character with `VectorForce` |
| Character snaps to full speed | Humanoid ground acceleration is effectively instant | `MovementFeel` ramp, or `ControllerManager` `AccelerationTime` |
| Behavior differs at 144 fps | Per-frame increments without `dt` | Multiply by `dt` or use `FixedStep` |
| Slight jitter on moving platforms | Kinematic platform moved with CFrame jumps | Use `AlignPosition`/`PrismaticConstraint`, or move in `PreSimulation` and carry passengers |
| Physics stutter on fast objects | Adaptive timestepping placed them in slow islands | Check the island visualization; consider Fixed stepping for that place |
| Exploiters move faster than allowed | Client owns its character's physics | Server-side sanity checks on position deltas; keep gameplay results on the server |

## Animation

| Symptom | Cause | Fix |
|---|---|---|
| Custom run never plays | Default `Animate` script overrides it | Replace IDs in `Animate` (server, on character added), or disable it for custom rigs |
| Marker events never fire | Using the deprecated `KeyframeReached`, or a marker name typo | `GetMarkerReachedSignal(name)`; check names in the editor |
| Clip timing slightly off after import | Resampled to the editor frame rate (30 fps default) | Key at 30 fps, or check the editor's frame-rate setting; re-time markers |
| Imported FBX has only one clip | Roblox imports one animation per FBX | Export each clip separately |
| Blender model is 100× too big | FBX scale settings | Apply Scalings = FBX Unit Scale, or use glTF |

## Rendering and UI

| Symptom | Cause | Fix |
|---|---|---|
| Lighting property seems to do nothing | Using the deprecated `Lighting.Technology` | `LightingStyle` + `PrioritizeLightingQuality` |
| Fog settings ignored | An `Atmosphere` exists | Tune the Atmosphere, or remove it to use classic fog |
| Normal maps look inverted | DirectX-format normal map | Flip the green channel (OpenGL format required) |
| Light can't reach a far area | Light range is clamped to 120 studs | Emissive surfaces, more lights, fog |
| HUD element under the Roblox top bar | `ScreenInsets` / core UI safe area | See `ui-recreation.md` §3 |
| Text size differs across devices | `TextScaled` or mixed scale and offset | Offset sizes plus `UIScale` |

## Input, VR and haptics

| Symptom | Cause | Fix |
|---|---|---|
| Haptics silent | `HapticService` is deprecated, or the device is unsupported | `HapticEffect`; check supported devices; probe on a Quest |
| VR detection wrong | `UserInputService.VREnabled` is deprecated | `VRService.VREnabled` |
| Avatar hands fight the custom rig | `VRService.AvatarGestures` on | Set it to false **on the server** |
| Binding conflicts with the Roblox menu | Reserved keys and buttons | Remap and record the substitution |

## Process

| Symptom | Cause | Fix |
|---|---|---|
| Studio edits vanish | Rojo sync overwrote them | Edit the files on disk for synced scripts |
| "Tested" claims don't hold up | A lower verification level reported as a higher one | Use the labels in `verification-loop.md` §6 |
| A breakdown value has no source | Guessed during implementation | Add evidence or mark it `ASSUMED`; tell the user |

## Deprecated → current

| Deprecated | Use |
|---|---|
| `wait`, `spawn`, `delay` | `task.wait`, `task.spawn`, `task.delay` |
| `AnimationTrack.KeyframeReached` | `AnimationTrack:GetMarkerReachedSignal()` |
| `BodyVelocity`, `BodyPosition`, `BodyGyro` (BodyMovers) | `LinearVelocity`, `AlignPosition`, `AlignOrientation`, `VectorForce` |
| `PhysicsService` collision group methods | `Workspace:RegisterCollisionGroup()`, `Workspace:CollisionGroupSetCollidable()`, `BasePart.CollisionGroup` |
| `Lighting.Technology` | `Lighting.LightingStyle` + `Lighting.PrioritizeLightingQuality` |
| `HapticService` | `HapticEffect` |
| `UserInputService.VREnabled` | `VRService.VREnabled` |
| `AnimationClipProvider:GetAnimationClip()` | `GetAnimationClipAsync()` |
