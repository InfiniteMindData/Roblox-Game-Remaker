--!strict
--[[
	Bootstrap (server): applies world, character, lighting and VR settings from Config.

	Character physics constants are set on StarterPlayer so every spawned character inherits them,
	and re-applied to characters that already exist (for live tuning in Studio).
	UseJumpPower is turned off so JumpHeight is exact for the configured gravity.
]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local StarterPlayer = game:GetService("StarterPlayer")
local VRService = game:GetService("VRService")
local Workspace = game:GetService("Workspace")

local Remake = ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Remake")
local Config = require(Remake:WaitForChild("Config"))
local LightingPreset = require(Remake:WaitForChild("LightingPreset"))

local movement = Config.Movement

Workspace.Gravity = Config.World.Gravity
StarterPlayer.CharacterWalkSpeed = movement.WalkSpeed
StarterPlayer.CharacterUseJumpPower = false
StarterPlayer.CharacterJumpHeight = movement.JumpApex
StarterPlayer.CharacterMaxSlopeAngle = movement.MaxSlopeAngle

if Config.VR.Enabled then
	-- Must be set on the server (creator docs: VRService.AvatarGestures).
	VRService.AvatarGestures = Config.VR.AvatarGestures
end

LightingPreset.apply(Config.Lighting)

local function applyToHumanoid(humanoid: Humanoid)
	humanoid.WalkSpeed = movement.WalkSpeed
	humanoid.UseJumpPower = false
	humanoid.JumpHeight = movement.JumpApex
	humanoid.MaxSlopeAngle = movement.MaxSlopeAngle
end

local function onCharacter(character: Model)
	local humanoid = character:WaitForChild("Humanoid", 10)
	if humanoid and humanoid:IsA("Humanoid") then
		applyToHumanoid(humanoid)
	end
end

local function onPlayer(player: Player)
	player.CharacterAdded:Connect(onCharacter)
	if player.Character then
		task.spawn(onCharacter, player.Character)
	end
end

Players.PlayerAdded:Connect(onPlayer)
for _, player in Players:GetPlayers() do
	onPlayer(player)
end

Workspace:SetAttribute("RemakeBootstrapped", true)
