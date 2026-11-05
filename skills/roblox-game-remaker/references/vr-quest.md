# VR and Meta Quest 3

Read this when VR is in scope: porting a VR original, or adding VR to a flat-screen remake.
Facts here come from the Roblox VR guidelines and the `VRService`, `HapticEffect` and
`HapticService` API references. Items marked **verify on device** are not stated in the docs:
confirm them with the bundled `InputProbe` before relying on them.

## 1. Platform facts

- Roblox VR runs on **OpenXR**, so the same implementation serves Quest (standalone) and PC VR
  headsets. The docs note that testing on PC VR is valid for Quest 2. Still test on a real Quest 3
  for performance.
- On Quest, **Auto Quality Mode** tries to hold at least **72 fps** by scaling render detail. If
  visuals degrade too far, optimize: enable streaming, reduce draw calls, transparency and
  `SurfaceGui` counts, and avoid heavy per-frame raycasting.
- Users choose comfort settings (Comfort, Default, Expert, Custom: vignette, stepped rotation,
  third-person fixed camera). The **default camera scripts** implement these, and custom cameras
  opt out of future updates. Keep the default VR camera unless the original's design requires
  otherwise, and record that decision.

## 2. Detect VR and read tracking (LocalScript only)

```lua
local VRService = game:GetService("VRService")
if VRService.VREnabled then -- not UserInputService.VREnabled, which is deprecated
	local head = VRService:GetUserCFrame(Enum.UserCFrame.Head)
	local left = VRService:GetUserCFrame(Enum.UserCFrame.LeftHand)
	local right = VRService:GetUserCFrame(Enum.UserCFrame.RightHand)
end
VRService.UserCFrameChanged:Connect(function(kind, cframe) end)
VRService.UserCFrameEnabled:Connect(function(kind, enabled) end)
```

- `UserCFrame` values: `Head`, `LeftHand`, `RightHand`, `Floor`.
- User CFrames are offsets in real-world tracking space. To get world space, the common pattern
  (used by the template's `VRSupport`) is
  `camera.CFrame * CFrame.new(user.Position * camera.HeadScale) * user.Rotation`.
  **Verify on device** with the Studio VR preview or a headset, because camera scripts and
  `HeadLocked` affect the result.
- `VRService:RecenterUserHeadCFrame()` recenters, and `GetUserCFrameEnabled(kind)` checks
  whether a device is tracked.

## 3. Service properties to set

| Property | Notes |
|---|---|
| `VRService.AvatarGestures` | Hands and head animate from tracking. **Must be set on the server.** Turn it off if it conflicts with custom rigs or weapon systems |
| `VRService.AutomaticScaling` | `World` scales `Camera.HeadScale` so the world is seen from the avatar's size; `Off` disables this |
| `VRService.ControllerModels` | `Transparent` (default) or `Disabled` |
| `VRService.LaserPointer` | `Pointer` (default), `DualPointer` or `Disabled` |
| `VRService.FadeOutViewOnCollision` | Fades to black when the head enters geometry |
| `Camera.HeadScale` | World scale from the player's perspective |
| `Camera.VRTiltAndRollEnabled` | Allows tilt and roll of the VR camera |

## 4. Quest 3 controller input

Touch controllers arrive through the gamepad input path. Prefer the **Input Action System**
(`InputAction` + `InputBinding`) so bindings live in one place and work across devices.

Typical mapping (**verify on device** with `DevTools/InputProbe`, which logs the `KeyCode`,
`UserInputType` and analog `Position` of every input):

| Quest control | Usually arrives as |
|---|---|
| Right A / B | `Enum.KeyCode.ButtonA` / `ButtonB` |
| Left X / Y | `Enum.KeyCode.ButtonX` / `ButtonY` |
| Index triggers (analog) | `ButtonL2` / `ButtonR2`; analog value in `InputObject.Position.Z` |
| Grip buttons | `ButtonL1` / `ButtonR1` |
| Thumbsticks | `Thumbstick1` (left) / `Thumbstick2` (right), value in `InputObject.Position` |
| Thumbstick clicks | `ButtonL3` / `ButtonR3` |
| Menu | Reserved by the system and Roblox; do not bind |

Run the probe, press every control, and save the Output as evidence (`EV-###`, type `capture`)
before finalizing `CTRL`/`VR` entries. `scripts/studio_snippets.py inputs probe.log --out remake/ui/quest-bindings.md`
turns the log into a binding table (KeyCode, input type, events, analog range). Threshold analog triggers with `InputBinding.PressedThreshold`
and `ReleasedThreshold` to reproduce the original's half-pull and full-pull behavior.

## 5. Haptics (HapticEffect)

`HapticService` is **deprecated**, superseded by `HapticEffect` instances. Supported devices
include the **Quest Touch controller**, Xbox and PlayStation gamepads, and supported phones.

```lua
local effect = Instance.new("HapticEffect")
effect.Type = Enum.HapticEffectType.GameplayCollision -- UIHover, UIClick, UINotification,
                                                       -- GameplayExplosion, GameplayCollision, Custom
effect.Parent = workspace
effect:Play()
```

- **Custom waveforms:** set `Type = Custom`, then `effect:SetWaveformKeys({FloatCurveKey.new(timeMs,
  intensity0to1, Enum.KeyInterpolationMode.Linear), ...})`. Time is in **milliseconds**.
  `Looped = true` repeats, `:Stop()` ends it, and `Ended` fires on completion.
- **Spatial targeting:** `Position` and `Radius` place the impact relative to the input device
  and set how widely it spreads to nearby motors. The mapping from `Position` to the left or right
  Quest controller is shown only as a diagram in the docs, so **verify on device**. The template's
  `Haptics.play(name, {side = "Left"})` uses `Config.Haptics.SidePositions`, which you calibrate
  with the probe.
- **Fallback:** `HapticService:SetMotor(Enum.UserInputType.Gamepad1, Enum.VibrationMotor.LeftHand,
  value)` (motors include `LeftHand` and `RightHand` for VR) still exists but is deprecated. The
  template uses it only when `Config.Haptics.AllowLegacyMotorFallback = true`.
- Measure the original's haptics where possible (controller-recording tools, or the user's
  description: strength, duration and pattern) and record them as `VR-###` entries. Unmeasured
  haptics are `ASSUMED`.

## 6. Recreating VR interactions

| Original VR feature | Roblox approach |
|---|---|
| Hand presence | Hand models welded to tracked CFrames on the client; AvatarGestures for avatar hands |
| Grabbing | Client detects a grip near an object (`GetPartBoundsInRadius`); the server validates and then assigns network ownership or welds; `AlignPosition` and `AlignOrientation` for physical held objects |
| Smooth locomotion | Default VR movement with `Thumbstick1`; match the measured speed through `WalkSpeed` |
| Teleport | `VRService:RequestNavigation(cframe, inputUserCFrame)` and the `NavigationRequested` event, or a custom arc plus a server-validated move |
| Snap turn | Rotate the character root by the measured degrees on a `Thumbstick2` flick; respect the user's stepped-rotation comfort setting |
| Wrist or world menus | `SurfaceGui` on a part following a hand CFrame; keep the default VR panel for system UI |
| Two-handed weapons | Orientation from both hand CFrames; validate fire on the server |

## 7. Adding VR to a flat-screen remake

1. Keep the default VR camera and comfort features.
2. Make every `CTRL` action reachable on Touch controllers (Input Action System bindings).
3. Move HUD information that depends on screen edges onto a VR-friendly panel or diegetic
   `SurfaceGui`, at a comfortable reading distance.
4. Replace aim-by-mouse with aim-by-hand where it makes sense, and document the change as a
   platform adaptation (not 1:1).
5. Add haptics to the same events that trigger screen shake.
6. Profile on Quest 3 against the 72 fps floor.

## 8. Testing

- **Studio:** test VR paths without a headset by forcing a code path in a test mode, plus
  `InputProbe` for the bindings. This is "Prepared, not run" for real hardware.
- **Device:** publish to a private test place, play on Quest 3, and run the probe and the
  measurement harness. Record frame rate with the MicroProfiler or the developer console.
- Report clearly which VR features were verified on hardware.
