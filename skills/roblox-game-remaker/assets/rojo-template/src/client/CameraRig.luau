--!strict
--[[
	CameraRig (client): measured camera behavior.

	Modes (Config.Camera.Mode):
	  Default       keep Roblox's camera scripts (best for VR comfort); set FOV, zoom limits, offset
	  Follow        third-person orbit: pivot offset, shoulder offset, distance, pitch limits,
	                spring-smoothed pivot, spherecast collision
	  Fixed         a static authored shot (Config.Camera.FixedShot = { Position, LookAt })
	  Orthographic  Camera.ProjectionType = Orthographic at a fixed angle (isometric or 2D-style)

	Every mode supports shake(amplitudeDeg, frequencyHz, durationSeconds) and an FOV override.
	In VR, Follow/Fixed/Orthographic fall back to Default unless Config.Camera.ForceInVR is true.
]]

local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")
local VRService = game:GetService("VRService")
local Workspace = game:GetService("Workspace")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared"):WaitForChild("Remake")
local Spring = require(Shared:WaitForChild("Spring"))

local CameraRig = {}

export type Handle = {
	shake: (amplitudeDeg: number, frequencyHz: number, duration: number) -> (),
	setFieldOfView: (fov: number?) -> (),
	stop: () -> (),
}

type Shake = { amp: number, freq: number, duration: number, t: number, px: number, py: number }

local RIG_BIND = "RemakeCameraRig"
local SHAKE_BIND = "RemakeCameraShake"

function CameraRig.start(cfg: { [string]: any }): Handle
	local player = Players.LocalPlayer
	local camera = Workspace.CurrentCamera
	local mode: string = cfg.Mode or "Default"
	if VRService.VREnabled and mode ~= "Default" and not cfg.ForceInVR then
		mode = "Default"
	end
	local fovOverride: number? = nil
	local shakes: { Shake } = {}
	local connections: { RBXScriptConnection } = {}
	local rng = Random.new()

	local function baseFov(): number
		return fovOverride or cfg.FieldOfView or 70
	end

	-- Shake runs after whichever camera logic is active.
	RunService:BindToRenderStep(SHAKE_BIND, Enum.RenderPriority.Camera.Value + 2, function(dt)
		if #shakes == 0 then
			return
		end
		local rx, ry = 0, 0
		for i = #shakes, 1, -1 do
			local s = shakes[i]
			s.t += dt
			if s.t >= s.duration then
				table.remove(shakes, i)
			else
				local envelope = (1 - s.t / s.duration) ^ 2
				local a = math.rad(s.amp) * envelope
				rx += a * math.sin(2 * math.pi * s.freq * s.t + s.px)
				ry += a * math.sin(2 * math.pi * s.freq * 1.37 * s.t + s.py)
			end
		end
		camera.CFrame = camera.CFrame * CFrame.Angles(rx, ry, 0)
	end)

	local function stopRig()
		pcall(function()
			RunService:UnbindFromRenderStep(RIG_BIND)
		end)
	end

	if mode == "Default" then
		camera.FieldOfView = baseFov()
		player.CameraMinZoomDistance = cfg.MinZoom or 0.5
		player.CameraMaxZoomDistance = cfg.MaxZoom or 128
		local function onCharacter(character: Model)
			local humanoid = character:WaitForChild("Humanoid", 10)
			if humanoid and humanoid:IsA("Humanoid") then
				humanoid.CameraOffset = cfg.HumanoidCameraOffset or Vector3.zero
			end
		end
		table.insert(connections, player.CharacterAdded:Connect(onCharacter))
		if player.Character then
			task.spawn(onCharacter, player.Character)
		end
	elseif mode == "Follow" then
		local yaw = 0
		local pitch = math.rad(cfg.StartPitchDeg or -15)
		local touchDelta = Vector2.zero
		local pivotSpring = Spring.new(Vector3.zero, cfg.FollowFrequency or 16.67, cfg.FollowDamping or 1)
		local initialized = false
		local params = RaycastParams.new()
		params.FilterType = Enum.RaycastFilterType.Exclude

		table.insert(
			connections,
			UserInputService.InputChanged:Connect(function(input, processed)
				if not processed and input.UserInputType == Enum.UserInputType.Touch then
					touchDelta += Vector2.new(input.Delta.X, input.Delta.Y)
				end
			end)
		)

		camera.CameraType = Enum.CameraType.Scriptable
		RunService:BindToRenderStep(RIG_BIND, Enum.RenderPriority.Camera.Value + 1, function(dt)
			local character = player.Character
			local root = character and character:FindFirstChild("HumanoidRootPart")
			if not (character and root and root:IsA("BasePart")) then
				return
			end
			camera.CameraType = Enum.CameraType.Scriptable
			if cfg.LockMouse ~= false then
				UserInputService.MouseBehavior = Enum.MouseBehavior.LockCenter
			end
			local md = UserInputService:GetMouseDelta()
			local sens = math.rad(cfg.MouseSensitivity or 0.25)
			yaw -= md.X * sens
			pitch -= md.Y * sens
			for _, input in UserInputService:GetGamepadState(Enum.UserInputType.Gamepad1) do
				if input.KeyCode == Enum.KeyCode.Thumbstick2 and input.Position.Magnitude > 0.15 then
					local speed = math.rad(cfg.GamepadSpeedDeg or 220) * dt
					yaw -= input.Position.X * speed
					pitch += input.Position.Y * speed
				end
			end
			local tsens = math.rad(cfg.TouchSensitivity or 0.3)
			yaw -= touchDelta.X * tsens
			pitch -= touchDelta.Y * tsens
			touchDelta = Vector2.zero
			pitch = math.clamp(pitch, math.rad(cfg.PitchMinDeg or -70), math.rad(cfg.PitchMaxDeg or 60))

			local pivotTarget = root.Position + (cfg.PivotOffset or Vector3.new(0, 2, 0))
			if not initialized then
				pivotSpring:snap(pivotTarget)
				initialized = true
			end
			pivotSpring.target = pivotTarget
			local pivot = pivotSpring:step(dt)
			local rot = CFrame.Angles(0, yaw, 0) * CFrame.Angles(pitch, 0, 0)
			local desired = pivot
				+ rot:VectorToWorldSpace(cfg.ShoulderOffset or Vector3.zero)
				- rot.LookVector * (cfg.Distance or 12)
			params.FilterDescendantsInstances = { character }
			local offset = desired - pivot
			local hit = if offset.Magnitude > 1e-3
				then Workspace:Spherecast(pivot, cfg.CollisionRadius or 0.5, offset, params)
				else nil
			local position = desired
			if hit then
				position = pivot + offset.Unit * math.max(hit.Distance - 0.1, 0.2)
			end
			camera.FieldOfView = baseFov()
			camera.CFrame = CFrame.new(position) * rot
			camera.Focus = CFrame.new(pivot)
		end)
	elseif mode == "Fixed" then
		local shot = cfg.FixedShot or { Position = Vector3.new(0, 20, 40), LookAt = Vector3.zero }
		RunService:BindToRenderStep(RIG_BIND, Enum.RenderPriority.Camera.Value + 1, function()
			camera.CameraType = Enum.CameraType.Scriptable
			camera.FieldOfView = baseFov()
			camera.CFrame = CFrame.lookAt(shot.Position, shot.LookAt)
		end)
	elseif mode == "Orthographic" then
		RunService:BindToRenderStep(RIG_BIND, Enum.RenderPriority.Camera.Value + 1, function()
			local character = player.Character
			local root = character and character:FindFirstChild("HumanoidRootPart")
			if not (root and root:IsA("BasePart")) then
				return
			end
			camera.CameraType = Enum.CameraType.Scriptable
			camera.ProjectionType = Enum.ProjectionType.Orthographic
			camera.OrthographicMode = (Enum.OrthographicMode :: any)[cfg.OrthographicAxis or "Vertical"]
			camera.OrthographicSize = cfg.OrthographicSize or 60
			local rot = CFrame.Angles(0, math.rad(cfg.OrthographicYawDeg or 45), 0)
				* CFrame.Angles(math.rad(cfg.OrthographicPitchDeg or -35.264), 0, 0)
			local focus = root.Position + (cfg.PivotOffset or Vector3.zero)
			camera.CFrame = CFrame.new(focus - rot.LookVector * 500) * rot
			camera.Focus = CFrame.new(focus)
		end)
	else
		warn(`CameraRig: unknown mode {mode}; using Default`)
	end

	local handle: Handle = {
		shake = function(amplitudeDeg: number, frequencyHz: number, duration: number)
			if duration > 0 and amplitudeDeg > 0 then
				table.insert(shakes, {
					amp = amplitudeDeg,
					freq = frequencyHz,
					duration = duration,
					t = 0,
					px = rng:NextNumber(0, 2 * math.pi),
					py = rng:NextNumber(0, 2 * math.pi),
				})
			end
		end,
		setFieldOfView = function(fov: number?)
			fovOverride = fov
			if mode == "Default" then
				camera.FieldOfView = baseFov()
			end
		end,
		stop = function()
			stopRig()
			pcall(function()
				RunService:UnbindFromRenderStep(SHAKE_BIND)
			end)
			for _, c in connections do
				c:Disconnect()
			end
			camera.CameraType = Enum.CameraType.Custom
			camera.ProjectionType = Enum.ProjectionType.Perspective
			UserInputService.MouseBehavior = Enum.MouseBehavior.Default
		end,
	}
	return handle
end

return CameraRig
