--!strict
--[[
	VRSupport (client): VR head and hand tracking, optional hand models and snap turn.

	Uses VRService.VREnabled (UserInputService.VREnabled is deprecated). Leaves the default VR
	camera and its comfort settings alone. VRService.AvatarGestures is set by the server Bootstrap
	(it must be set on the server).

	local vr = VRSupport.start(Config)
	local leftHand = vr.getHandCFrame("Left") -- world space, or nil when not tracked

	World-space conversion uses camera.CFrame * (user position * HeadScale) * user rotation.
	Verify alignment on a headset; custom cameras or HeadLocked changes can alter it.
]]

local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")
local VRService = game:GetService("VRService")
local Workspace = game:GetService("Workspace")

local VRSupport = {}

export type Handle = {
	enabled: boolean,
	getHandCFrame: (side: string) -> CFrame?,
	getHeadCFrame: () -> CFrame?,
	stop: () -> (),
}

local function worldFromUser(kind: Enum.UserCFrame): CFrame?
	if not VRService:GetUserCFrameEnabled(kind) then
		return nil
	end
	local camera = Workspace.CurrentCamera
	local user = VRService:GetUserCFrame(kind)
	return camera.CFrame * CFrame.new(user.Position * camera.HeadScale) * user.Rotation
end

function VRSupport.start(config: { [string]: any }): Handle
	local vrCfg = config.VR or {}
	if not (VRService.VREnabled and vrCfg.Enabled ~= false) then
		return {
			enabled = false,
			getHandCFrame = function(_side: string): CFrame?
				return nil
			end,
			getHeadCFrame = function(): CFrame?
				return nil
			end,
			stop = function() end,
		}
	end
	local player = Players.LocalPlayer
	local connections: { RBXScriptConnection } = {}
	local hands: { [string]: BasePart } = {}

	if vrCfg.HandModels then
		for _, side in { "Left", "Right" } do
			local part = Instance.new("Part")
			part.Name = `RemakeHand{side}`
			part.Size = Vector3.new(0.4, 0.4, 0.8)
			part.Anchored = true
			part.CanCollide = false
			part.CanQuery = false
			part.CanTouch = false
			part.CastShadow = false
			part.Parent = Workspace.CurrentCamera -- local-only cosmetic
			hands[side] = part
		end
		table.insert(
			connections,
			RunService.RenderStepped:Connect(function()
				for side, part in hands do
					local kind = if side == "Left" then Enum.UserCFrame.LeftHand else Enum.UserCFrame.RightHand
					local cf = worldFromUser(kind)
					part.Transparency = if cf then 0 else 1
					if cf then
						part.CFrame = cf
					end
				end
			end)
		)
	end

	local snap = vrCfg.SnapTurnDegrees or 0
	if snap > 0 then
		local armed = true
		table.insert(
			connections,
			UserInputService.InputChanged:Connect(function(input)
				if input.KeyCode ~= Enum.KeyCode.Thumbstick2 then
					return
				end
				local x = input.Position.X
				if armed and math.abs(x) > 0.7 then
					armed = false
					local character = player.Character
					local root = character and character:FindFirstChild("HumanoidRootPart")
					if root and root:IsA("BasePart") then
						local sign = if x > 0 then -1 else 1
						root.CFrame = root.CFrame * CFrame.Angles(0, math.rad(snap) * sign, 0)
					end
				elseif math.abs(x) < 0.3 then
					armed = true
				end
			end)
		)
	end

	return {
		enabled = true,
		getHandCFrame = function(side: string): CFrame?
			return worldFromUser(if side == "Left" then Enum.UserCFrame.LeftHand else Enum.UserCFrame.RightHand)
		end,
		getHeadCFrame = function(): CFrame?
			return worldFromUser(Enum.UserCFrame.Head)
		end,
		stop = function()
			for _, c in connections do
				c:Disconnect()
			end
			for _, part in hands do
				part:Destroy()
			end
		end,
	}
end

return VRSupport
