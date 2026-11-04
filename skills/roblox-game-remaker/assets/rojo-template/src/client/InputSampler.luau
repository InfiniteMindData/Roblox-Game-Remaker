--!strict
--[[
	InputSampler (client): the player's raw movement and jump input, before any smoothing.

	MovementFeel overrides Humanoid:Move(), so Humanoid.MoveDirection no longer shows what the
	player pressed. This module reads the default ControlModule's move vector instead (falling back
	to WASD and the left stick), so movement feel and the measurement harness see real input.
]]

local Players = game:GetService("Players")
local UserInputService = game:GetService("UserInputService")
local Workspace = game:GetService("Workspace")

local InputSampler = {}

local controls: any = nil
local triedControls = false
local lastJumpRequest = -math.huge

UserInputService.JumpRequest:Connect(function()
	lastJumpRequest = os.clock()
end)

local function getControls(): any
	if not triedControls then
		triedControls = true
		local ok, result = pcall(function()
			local playerScripts = Players.LocalPlayer:WaitForChild("PlayerScripts", 10)
			local module = playerScripts and playerScripts:WaitForChild("PlayerModule", 10)
			if module and module:IsA("ModuleScript") then
				return (require(module) :: any):GetControls()
			end
			return nil
		end)
		controls = if ok then result else nil
	end
	return controls
end

-- Camera-space move vector (x = right, z = back), magnitude 0..1.
function InputSampler.rawMove(): Vector3
	local c = getControls()
	local raw = Vector3.zero
	if c and c.GetMoveVector then -- api-check: ignore (PlayerModule ControlModule method)
		raw = c:GetMoveVector() -- api-check: ignore
	else
		local x, z = 0, 0
		if UserInputService:IsKeyDown(Enum.KeyCode.W) then
			z -= 1
		end
		if UserInputService:IsKeyDown(Enum.KeyCode.S) then
			z += 1
		end
		if UserInputService:IsKeyDown(Enum.KeyCode.A) then
			x -= 1
		end
		if UserInputService:IsKeyDown(Enum.KeyCode.D) then
			x += 1
		end
		for _, input in UserInputService:GetGamepadState(Enum.UserInputType.Gamepad1) do
			if input.KeyCode == Enum.KeyCode.Thumbstick1 and input.Position.Magnitude > 0.15 then
				x += input.Position.X
				z -= input.Position.Y
			end
		end
		raw = Vector3.new(x, 0, z)
	end
	if raw.Magnitude > 1 then
		raw = raw.Unit
	end
	return raw
end

-- World-space planar move vector, magnitude 0..1, relative to the current camera.
function InputSampler.worldMove(): Vector3
	local raw = InputSampler.rawMove()
	local camera = Workspace.CurrentCamera
	if not camera or raw.Magnitude < 1e-4 then
		return Vector3.zero
	end
	local cf = camera.CFrame
	local forward = Vector3.new(cf.LookVector.X, 0, cf.LookVector.Z)
	if forward.Magnitude < 1e-3 then
		forward = Vector3.new(-cf.UpVector.X, 0, -cf.UpVector.Z) -- looking straight down
	end
	local right = Vector3.new(cf.RightVector.X, 0, cf.RightVector.Z)
	if forward.Magnitude < 1e-3 or right.Magnitude < 1e-3 then
		return Vector3.zero
	end
	return right.Unit * raw.X + forward.Unit * -raw.Z
end

-- True while jump is held: Space, gamepad A, or repeated JumpRequest events (touch).
-- JumpRequest fires several times per press (creator docs), so treat recent requests as held.
function InputSampler.jumpHeld(): boolean
	if UserInputService:IsKeyDown(Enum.KeyCode.Space) then
		return true
	end
	if UserInputService:IsGamepadButtonDown(Enum.UserInputType.Gamepad1, Enum.KeyCode.ButtonA) then
		return true
	end
	return os.clock() - lastJumpRequest < 0.12
end

return InputSampler
