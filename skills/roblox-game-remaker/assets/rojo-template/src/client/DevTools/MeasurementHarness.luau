--!strict
--[[
	MeasurementHarness (client, Studio only): logs character motion for measure_compare.py.

	Enable with Config.DevTools.Measure = true, or Workspace:SetAttribute("RemakeMeasure", true)
	before playing. Output lines look like:
	  REMAKE_MEASURE {"k":"b","s":[[t,x,y,z,vx,vy,vz,state,mv], ...]}
	  REMAKE_MEASURE {"k":"e","t":1.234,"n":"jump"}
	state codes: 0 Unknown, 1 Running, 2 Jumping, 3 Freefall, 4 Landed, 5 Climbing, 6 Swimming,
	7 Seated, 8 Dead, 9 Other.  mv = raw move-input magnitude (0..1), before any smoothing.

	Copy the Output (or MCP get_console_output) to remake/logs/run-NN.log, then:
	  python scripts/measure_compare.py remake/logs/run-NN.log --targets remake/targets.json
]]

local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local Workspace = game:GetService("Workspace")

local InputSampler = require(script.Parent.Parent:WaitForChild("InputSampler"))

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

function MeasurementHarness.start(config: { [string]: any }): () -> ()
	local dev = config.DevTools or {}
	local enabled = dev.Measure == true or Workspace:GetAttribute("RemakeMeasure") == true
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
