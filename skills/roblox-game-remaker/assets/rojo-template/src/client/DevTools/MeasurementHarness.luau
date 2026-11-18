--!strict
--[[
	MeasurementHarness (client, Studio only): logs character motion for measure_compare.py.

	Enable with Config.DevTools.Measure = true, or Workspace:SetAttribute("RemakeMeasure", true)
	before playing. Output lines look like:
	  REMAKE_MEASURE {"k":"b","s":[[t,x,y,z,vx,vy,vz,state,mv], ...]}
	  REMAKE_MEASURE {"k":"e","t":1.234,"n":"jump"}
	state codes: 0 Unknown, 1 Running, 2 Jumping, 3 Freefall, 4 Landed, 5 Climbing, 6 Swimming,
	7 Seated, 8 Dead, 9 Other.  mv = raw move-input magnitude (0..1), before any smoothing.

	Input response time (Config.DevTools.MeasureLatency = true, or Workspace attribute
	RemakeMeasureLatency): for each press of a key in Config.DevTools.LatencyKeys, count rendered frames
	(RunService.PreRender) from an isolated input after 150 ms still/grounded to an action-consistent response.
	W/A/S/D require grounded displacement and velocity along the camera-relative probed direction;
	Space/ButtonA require upward velocity in Jumping state. Unsupported/overlapping inputs are skipped:
	  REMAKE_MEASURE {"k":"l","t":1.234,"in":"Space","f":2,"fd":0.0167,"dt":0.0251}
	f = frames (-1 = no change within LatencyTimeout), fd = frame duration at the change, dt = seconds by
	os.clock. This is action-consistent response timing, not proof of causality; external forces can confound it.
	It excludes the display and capture chain. Use default camera-relative controls in a quiet test scene.

	Copy the Output (or MCP get_console_output) to remake/logs/run-NN.log, then:
	  python scripts/measure_compare.py remake/logs/run-NN.log --targets remake/targets.json
]]

local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")
local Workspace = game:GetService("Workspace")

local InputSampler = require(script.Parent.Parent:WaitForChild("InputSampler"))
local LatencyProbe = require(
	game:GetService("ReplicatedStorage"):WaitForChild("Shared"):WaitForChild("Remake"):WaitForChild("LatencyProbe")
)

local MeasurementHarness = {}

local TAG = "REMAKE_MEASURE"
local STATE_CODES: { [Enum.HumanoidStateType]: number } = {
	[Enum.HumanoidStateType.Running] = 1,
	[Enum.HumanoidStateType.RunningNoPhysics] = 1,
	[Enum.HumanoidStateType.Jumping] = 2,
	[Enum.HumanoidStateType.Freefall] = 3,
	[Enum.HumanoidStateType.Landed] = 4,
	[Enum.HumanoidStateType.Climbing] = 5,
	[Enum.HumanoidStateType.Swimming] = 6,
	[Enum.HumanoidStateType.Seated] = 7,
	[Enum.HumanoidStateType.Dead] = 8,
}

local function round(v: number, digits: number): number
	local m = 10 ^ digits
	return math.round(v * m) / m
end

type Press = {
	key: string,
	frame: number,
	clock: number,
	pos: Vector3,
	action: string,
	direction: Vector3,
	root: BasePart,
}

-- Input response time: rendered frames from a watched key press to the first frame that shows a change.
local function startLatency(
	dev: { [string]: any },
	emit: ({ [string]: any }) -> (),
	t0: number,
	rig: () -> (Humanoid?, BasePart?)
): { RBXScriptConnection }
	local watch: { [string]: boolean } = {}
	for _, name in dev.LatencyKeys or { "Space", "ButtonA", "W", "A", "S", "D" } do
		watch[name] = true
	end
	local timeout = dev.LatencyTimeout or 1
	local frame = 0
	local pending: { Press } = {}
	local stillTime = 0
	local baselineRoot: BasePart? = nil
	local function grounded(humanoid: Humanoid): boolean
		local state = humanoid:GetState()
		return humanoid.FloorMaterial ~= Enum.Material.Air
			and (
				state == Enum.HumanoidStateType.Running
				or state == Enum.HumanoidStateType.RunningNoPhysics
				or state == Enum.HumanoidStateType.Landed
			)
	end
	local function skip(key: string, reason: string)
		emit({ k = "e", t = round(os.clock() - t0, 4), n = "latency_skipped", key = key, reason = reason })
	end
	local conns: { RBXScriptConnection } = {}
	table.insert(
		conns,
		UserInputService.InputBegan:Connect(function(input: InputObject, processed: boolean)
			if processed then
				return
			end
			local action = LatencyProbe.action(input.KeyCode.Name)
			if #pending > 0 and (action or watch[input.KeyCode.Name]) then
				for _, press in pending do
					skip(press.key, "overlapping_input")
				end
				table.clear(pending)
				stillTime = 0
				return
			end
			if not watch[input.KeyCode.Name] then
				return
			end
			local humanoid, root = rig()
			if not (action and humanoid and root) then
				skip(input.KeyCode.Name, "unsupported_action_or_missing_rig")
				return
			end
			if
				root ~= baselineRoot
				or not LatencyProbe.ready(
					stillTime,
					root.AssemblyLinearVelocity.Magnitude,
					humanoid.MoveDirection.Magnitude,
					grounded(humanoid)
				)
			then
				skip(input.KeyCode.Name, "baseline_not_still_grounded")
				return
			end
			local direction = Vector3.zero
			if action ~= "jump" then
				local camera = Workspace.CurrentCamera
				if not camera then
					return
				end
				local axis = if action == "forward" or action == "back"
					then camera.CFrame.LookVector
					else camera.CFrame.RightVector
				direction = Vector3.new(axis.X, 0, axis.Z)
				if direction.Magnitude < 1e-3 then
					skip(input.KeyCode.Name, "ambiguous_camera_direction")
					return
				end
				direction = direction.Unit * (if action == "back" or action == "left" then -1 else 1)
			end
			stillTime = 0
			table.insert(pending, {
				key = input.KeyCode.Name,
				frame = frame,
				clock = os.clock(),
				pos = root.Position,
				action = action,
				direction = direction,
				root = root,
			})
		end)
	)
	table.insert(
		conns,
		RunService.PreRender:Connect(function(deltaTime: number)
			frame += 1
			local humanoid, root = rig()
			if root ~= baselineRoot then
				stillTime = 0
				baselineRoot = root
			end
			if
				humanoid
				and root
				and LatencyProbe.ready(
					0.15,
					root.AssemblyLinearVelocity.Magnitude,
					humanoid.MoveDirection.Magnitude,
					grounded(humanoid)
				)
			then
				stillTime += deltaTime
			else
				stillTime = 0
			end
			local now = os.clock()
			for i = #pending, 1, -1 do
				local p = pending[i]
				local changed = false
				if humanoid and root and root == p.root then
					changed = LatencyProbe.responded(
						p.action,
						(root.Position - p.pos):Dot(p.direction),
						root.AssemblyLinearVelocity:Dot(p.direction),
						root.AssemblyLinearVelocity.Y,
						humanoid:GetState() == Enum.HumanoidStateType.Jumping,
						grounded(humanoid)
					)
				end
				if changed or now - p.clock > timeout then
					emit({
						k = "l",
						t = round(p.clock - t0, 4),
						["in"] = p.key,
						f = if changed then frame - p.frame else -1,
						fd = round(deltaTime, 5),
						dt = round(now - p.clock, 4),
					})
					table.remove(pending, i)
				end
			end
		end)
	)
	return conns
end

function MeasurementHarness.start(config: { [string]: any }): () -> ()
	local dev = config.DevTools or {}
	local latency = dev.MeasureLatency == true or Workspace:GetAttribute("RemakeMeasureLatency") == true
	local enabled = latency or dev.Measure == true or Workspace:GetAttribute("RemakeMeasure") == true
	if not (enabled and RunService:IsStudio()) then
		return function() end
	end
	local player = Players.LocalPlayer
	local batchSize = dev.MeasureBatch or 30
	local t0 = os.clock()
	local batch = {}
	local conns: { RBXScriptConnection } = {}
	local charConns: { RBXScriptConnection } = {}
	local moving = false
	local rigHumanoid: Humanoid? = nil
	local rigRoot: BasePart? = nil

	local function emit(obj: { [string]: any })
		print(`{TAG} {HttpService:JSONEncode(obj)}`)
	end
	local function flush()
		if #batch > 0 then
			emit({ k = "b", s = batch })
			batch = {}
		end
	end
	local function event(name: string)
		flush()
		emit({ k = "e", t = round(os.clock() - t0, 4), n = name })
	end

	local function bind(character: Model)
		for _, c in charConns do
			c:Disconnect()
		end
		table.clear(charConns)
		local humanoid = character:WaitForChild("Humanoid", 10)
		local root = character:WaitForChild("HumanoidRootPart", 10)
		if not (humanoid and humanoid:IsA("Humanoid") and root and root:IsA("BasePart")) then
			return
		end
		rigHumanoid, rigRoot = humanoid, root
		event("spawn")
		table.insert(
			charConns,
			humanoid.StateChanged:Connect(function(old, new)
				if new == Enum.HumanoidStateType.Jumping then
					event("jump")
				elseif
					(old == Enum.HumanoidStateType.Freefall or old == Enum.HumanoidStateType.Jumping)
					and (new == Enum.HumanoidStateType.Landed or new == Enum.HumanoidStateType.Running)
				then
					event("land")
				end
			end)
		)
		table.insert(
			charConns,
			RunService.PostSimulation:Connect(function()
				local mv = InputSampler.rawMove().Magnitude
				if mv > 0.05 and not moving then
					moving = true
					event("move_start")
				elseif mv <= 0.05 and moving then
					moving = false
					event("move_stop")
				end
				local p, v = root.Position, root.AssemblyLinearVelocity
				table.insert(batch, {
					round(os.clock() - t0, 4),
					round(p.X, 3),
					round(p.Y, 4),
					round(p.Z, 3),
					round(v.X, 3),
					round(v.Y, 3),
					round(v.Z, 3),
					STATE_CODES[humanoid:GetState()] or 9,
					round(mv, 3),
				})
				if #batch >= batchSize then
					flush()
				end
			end)
		)
	end

	table.insert(conns, player.CharacterAdded:Connect(bind))
	if latency then
		local latencyConns = startLatency(dev, emit, t0, function()
			return rigHumanoid, rigRoot
		end)
		for _, c in latencyConns do
			table.insert(conns, c)
		end
	end
	if player.Character then
		task.spawn(bind, player.Character)
	end
	print(`{TAG} {HttpService:JSONEncode({ k = "e", t = 0, n = "session" })}`)

	return function()
		flush()
		for _, c in conns do
			c:Disconnect()
		end
		for _, c in charConns do
			c:Disconnect()
		end
	end
end

return MeasurementHarness
