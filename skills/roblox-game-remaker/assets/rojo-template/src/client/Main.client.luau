--!strict
--[[
	Main (client): wires the remake's client systems from Config.

	Every system reads Config, so tuning happens in ReplicatedStorage.Shared.Remake.Config only.
	ScreenGuis with the attribute RemakeScaleUI = true get a reference-resolution UIScale.
]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Remake")
local Config = require(Shared:WaitForChild("Config"))

local Remake = script.Parent
local MovementFeel = require(Remake:WaitForChild("MovementFeel"))
local CameraRig = require(Remake:WaitForChild("CameraRig"))
local AnimationDriver = require(Remake:WaitForChild("AnimationDriver"))
local UIScaler = require(Remake:WaitForChild("UIScaler"))
local VRSupport = require(Remake:WaitForChild("VRSupport"))
local ShotCamera = require(Remake:WaitForChild("ShotCamera"))
local DevTools = Remake:WaitForChild("DevTools")
local MeasurementHarness = require(DevTools:WaitForChild("MeasurementHarness"))
local InputProbe = require(DevTools:WaitForChild("InputProbe"))

MovementFeel.start({ config = Config.Movement })
local camera = CameraRig.start(Config.Camera)
local animation = AnimationDriver.start(Config.Animation)
local vr = VRSupport.start(Config)
MeasurementHarness.start(Config)
InputProbe.start(Config)

-- Reference-resolution UI scaling for opted-in ScreenGuis.
local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")
local function maybeScale(gui: Instance)
	if gui:IsA("ScreenGui") and gui:GetAttribute("RemakeScaleUI") == true then
		UIScaler.attach(gui, { reference = Config.UI.ReferenceResolution, rule = Config.UI.ScaleRule })
	end
end
for _, gui in playerGui:GetChildren() do
	maybeScale(gui)
end
playerGui.ChildAdded:Connect(maybeScale)

-- Studio shot hotkeys (F7 next, F8 release) when a Shots module exists.
local shotsModule = Shared:FindFirstChild("Shots")
if Config.DevTools.ShotHotkeys and shotsModule and shotsModule:IsA("ModuleScript") then
	ShotCamera.installHotkeys(require(shotsModule) :: any)
end

-- Expose the running systems to other client code (LocalScripts cannot be required).
local Handles = require(Remake:WaitForChild("Handles"))
Handles.camera = camera
Handles.animation = animation
Handles.vr = vr
