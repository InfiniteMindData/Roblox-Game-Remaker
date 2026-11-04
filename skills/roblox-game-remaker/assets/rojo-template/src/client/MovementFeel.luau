--!strict
--[[
	MovementFeel (client): measured movement feel on top of the standard Humanoid.

	  * acceleration and deceleration ramps (Config.Movement.AccelerationTime / DecelerationTime)
	  * reduced air control (AirControl)
	  * asymmetric jumps: extra gravity while falling (FallGravityMultiplier)
	  * variable jump height: extra gravity after an early release (ReleaseGravityMultiplier)
	  * fall-speed cap (MaxFallSpeed), coyote time, jump buffering, air jumps, turn rate

	How it works: the default ControlModule calls Humanoid:Move() in a RenderStep binding at
	Enum.RenderPriority.Input. This module binds just after it and calls Humanoid:Move() with the
	smoothed vector (a magnitude below 1 walks slower than WalkSpeed). Extra gravity is a world-space
	VectorForce on the root, so Workspace.Gravity (rise gravity) stays global and physical.

	Verify the result with the MeasurementHarness and measure_compare.py. If a project's control
	scripts update the Humanoid after this binding (custom PlayerModule, Input Action System
	rollouts), move the ramp into that controller or use ControllerManager instead.
]]

local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local Workspace = game:GetService("Workspace")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared"):WaitForChild("Remake")
local MovementMath = require(Shared:WaitForChild("MovementMath"))
local InputSampler = require(script.Parent:WaitForChild("InputSampler"))

local MovementFeel = {}

export type Options = {
	config: { [string]: any },
	getMoveInput: (() -> Vector3)?, -- world-space planar input, magnitude 0..1
	isJumpHeld: (() -> boolean)?,
}

local BIND_NAME = "RemakeMovementFeel"

function MovementFeel.start(options: Options): () -> ()
	local cfg = options.config
	local player = Players.LocalPlayer
	local getMove = options.getMoveInput or InputSampler.worldMove
	local jumpHeld = options.isJumpHeld or InputSampler.jumpHeld
	local cleanup: { () -> () } = {}
	local characterCleanup: { () -> () } = {}

	local function clearCharacter()
		for i = #characterCleanup, 1, -1 do
			characterCleanup[i]()
		end
		table.clear(characterCleanup)
	end

	local function bind(character: Model)
		if player.Character ~= character then
			return
		end
		clearCharacter()
		local humanoid = character:WaitForChild("Humanoid", 10)
		local root = character:WaitForChild("HumanoidRootPart", 10)
		if not (humanoid and humanoid:IsA("Humanoid") and root and root:IsA("BasePart")) then
			return
		end
		if player.Character ~= character then
			return
		end

		local attachment = Instance.new("Attachment")
		attachment.Name = "RemakeFeelAttachment"
		attachment.Parent = root
		local force = Instance.new("VectorForce")
		force.Name = "RemakeFeelForce"
		force.Attachment0 = attachment
		force.RelativeTo = Enum.ActuatorRelativeTo.World
		force.ApplyAtCenterOfMass = true
		force.Force = Vector3.zero
		force.Parent = root

		local assist = MovementMath.JumpAssist.new(cfg.CoyoteTime or 0, cfg.JumpBuffer or 0)
		local useRamp = (cfg.AccelerationTime or 0) > 0 or (cfg.DecelerationTime or 0) > 0 or (cfg.AirControl or 1) < 1
		local turnRate = math.rad(cfg.TurnSpeedDegrees or 0)
		local planar = Vector3.zero
		local wasHeld = false
		local jumpedThisAir = false
		local airJumpsLeft = cfg.AirJumps or 0
		local previousAutoRotate = humanoid.AutoRotate
		if turnRate > 0 then
			humanoid.AutoRotate = false
		end

		local stateConn = humanoid.StateChanged:Connect(function(_, new)
			if new == Enum.HumanoidStateType.Jumping then
				assist:notifyJumped()
				jumpedThisAir = true
			elseif
				new == Enum.HumanoidStateType.Landed
				or new == Enum.HumanoidStateType.Running
				or new == Enum.HumanoidStateType.RunningNoPhysics
			then
				jumpedThisAir = false
				airJumpsLeft = cfg.AirJumps or 0
			end
		end)

		local function step(dt: number)
			if humanoid.Health <= 0 or dt <= 0 then
				return
			end
			local airborne = humanoid.FloorMaterial == Enum.Material.Air
			local state = humanoid:GetState()
			local grounded = not airborne
				and state ~= Enum.HumanoidStateType.Swimming
				and state ~= Enum.HumanoidStateType.Climbing
				and state ~= Enum.HumanoidStateType.Seated

			if useRamp then
				local top = humanoid.WalkSpeed
				local desired = getMove() * top
				local speedingUp = desired.Magnitude >= planar.Magnitude - 1e-6
				local rampTime = if speedingUp then cfg.AccelerationTime or 0 else cfg.DecelerationTime or 0
				local rate = MovementMath.rampRate(top, rampTime)
				if airborne then
					rate *= cfg.AirControl or 1
				end
				local nx, nz = MovementMath.approachPlanar(planar.X, planar.Z, desired.X, desired.Z, rate * dt)
				planar = Vector3.new(nx, 0, nz)
				if top > 0 then
					humanoid:Move(planar / top, false)
				end
			end

			if turnRate > 0 then
				local dir = if useRamp then planar else humanoid.MoveDirection
				if dir.Magnitude > 0.05 then
					local look = root.CFrame.LookVector
					local current = math.atan2(-look.X, -look.Z)
					local target = math.atan2(-dir.X, -dir.Z)
					local delta = (target - current + math.pi) % (2 * math.pi) - math.pi
					local maxStep = turnRate * dt
					local yaw = current + math.clamp(delta, -maxStep, maxStep)
					root.CFrame = CFrame.new(root.Position) * CFrame.Angles(0, yaw, 0)
				end
			end

			local held = jumpHeld()
			local pressed = held and not wasHeld
			wasHeld = held
			local reason = assist:update(dt, grounded, pressed)
			if reason == "coyote" or reason == "buffer" then
				humanoid:ChangeState(Enum.HumanoidStateType.Jumping)
			elseif pressed and airborne and reason == nil and airJumpsLeft > 0 then
				airJumpsLeft -= 1
				local apex = if (cfg.AirJumpApex or 0) > 0 then cfg.AirJumpApex else cfg.JumpApex
				local v = root.AssemblyLinearVelocity
				humanoid:ChangeState(Enum.HumanoidStateType.Jumping)
				root.AssemblyLinearVelocity = Vector3.new(v.X, math.sqrt(2 * Workspace.Gravity * apex), v.Z)
				assist:notifyJumped()
			end
		end

		local function shapeGravity()
			local v = root.AssemblyLinearVelocity
			local multiplier = 1
			if humanoid.FloorMaterial == Enum.Material.Air then
				if v.Y < 0 then
					multiplier = cfg.FallGravityMultiplier or 1
				elseif jumpedThisAir and not jumpHeld() then
					multiplier = cfg.ReleaseGravityMultiplier or 1
				end
			end
			force.Force = Vector3.new(0, -root.AssemblyMass * Workspace.Gravity * (multiplier - 1), 0)
			local cap = cfg.MaxFallSpeed or 0
			if cap > 0 and v.Y < -cap then
				root.AssemblyLinearVelocity = Vector3.new(v.X, -cap, v.Z)
			end
		end

		RunService:BindToRenderStep(BIND_NAME, Enum.RenderPriority.Input.Value + 1, step)
		local physicsConn = RunService.PreSimulation:Connect(shapeGravity)

		table.insert(characterCleanup, function()
			RunService:UnbindFromRenderStep(BIND_NAME)
			physicsConn:Disconnect()
			stateConn:Disconnect()
			force:Destroy()
			attachment:Destroy()
			if humanoid.Parent then
				humanoid.AutoRotate = previousAutoRotate
			end
		end)
	end

	local addedConn = player.CharacterAdded:Connect(bind)
	local removingConn = player.CharacterRemoving:Connect(function()
		clearCharacter()
	end)
	table.insert(cleanup, function()
		addedConn:Disconnect()
		removingConn:Disconnect()
	end)
	if player.Character then
		task.spawn(bind, player.Character)
	end

	return function()
		clearCharacter()
		for _, fn in cleanup do
			fn()
		end
	end
end

return MovementFeel
