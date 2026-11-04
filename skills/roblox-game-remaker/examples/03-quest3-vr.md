# Walkthrough: adding Meta Quest 3 support

Scenario: the remake of a flat-screen platformer should also play well on a Quest 3. This is a
platform adaptation, so record it as such in the `VR-###` entries rather than as 1:1 behavior.

## 1. Settings

- Keep `Config.Camera.Mode = "Default"` for VR players (the template already falls back to the
  default camera in VR unless `ForceInVR` is set). This keeps Roblox's comfort options: vignette,
  stepped rotation, and the third-person fixed camera.
- `Config.VR.AvatarGestures = true`, which the server Bootstrap applies (it must be set on the
  server).
- Optional: `Config.VR.HandModels = true` for simple tracked hand parts, and
  `Config.VR.SnapTurnDegrees = 30` if the game needs its own snap turn.

## 2. Verify the controller mapping on the headset

The Roblox docs do not publish a Touch-controller KeyCode table, so measure it:

1. Publish to a private test place with `Config.DevTools.InputProbe = true`.
2. On the Quest 3, press every control: A, B, X, Y, both triggers (half and full), both grips,
   both sticks (push and click).
3. Read the overlay or the Output lines:
   `REMAKE_INPUT {"e":"began","kc":"ButtonR2","ut":"Gamepad1","pos":[0,0,0.62],"gp":false}`.
4. Save the log as evidence (`type: capture`) and fill the `VR-###` binding table from it.
5. Turn the probe off before release.

## 3. Bind actions

Add Touch-controller bindings to the same `InputAction`s used on other devices, for example Jump
bound to the button the probe showed for A. Use `PressedThreshold` and `ReleasedThreshold` on
trigger bindings when the original distinguishes half and full pulls.

## 4. Haptics

```lua
local Haptics = require(script.Parent.Haptics)
Haptics.play("Hit")                          -- GameplayCollision preset
Haptics.play("Heartbeat", { side = "Left" }) -- custom waveform (keys in ms, intensity 0..1)
```

- Calibrate `Config.Haptics.SidePositions` on the device. Play the effect with each candidate
  `Position` and note which hand rumbles. The docs show this mapping only as a diagram.
- Pair every camera shake event with a haptic event of similar duration.

## 5. UI

- HUD information near screen edges is hard to read in VR. Put it on a `SurfaceGui` attached to a
  part that follows the left hand (`Handles.vr.getHandCFrame("Left")`), or leave the default VR
  panel for menus.
- Keep text large and high-contrast, and avoid many semi-transparent layers.

## 6. Performance

- Target at least 72 fps on Quest (Roblox's Auto Quality Mode aims for this).
- Enable streaming, reduce draw calls and transparency, and avoid heavy per-frame raycasts.
- Profile on the device with the MicroProfiler.

## 7. Report honestly

| Check | Level |
|---|---|
| Bindings via InputProbe on a Quest 3 | Executed (device), with a saved log |
| Haptics side calibration | Executed (device) |
| Frame rate in level 1-1 | Executed (device), with a MicroProfiler capture |
| VR code paths in Studio without a headset | Prepared, not run on hardware |
