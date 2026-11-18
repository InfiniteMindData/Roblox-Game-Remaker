-- Service doubles test the actual event wiring, not Studio physics or device latency.
local fs = require("@lune/fs")
local luau = require("@lune/luau")
local serde = require("@lune/serde")
local roblox = require("@lune/roblox")
local Probe = require("../../src/shared/Remake/LatencyProbe")
local T = require("./T")
local V = roblox.Vector3

local function fixture(keys)
	local function signal()
		local callbacks = {}
		return {
			Connect = function(_, fn)
				table.insert(callbacks, fn)
				return { Disconnect = function() end }
			end,
			fire = function(...)
				for _, fn in callbacks do
					fn(...)
				end
			end,
		}
	end
	local now = 0
	local logs = {}
	local input, render = signal(), signal()
	local root = {
		Position = V.zero,
		AssemblyLinearVelocity = V.zero,
		IsA = function()
			return true
		end,
	}
	local humanoid = {
		MoveDirection = V.zero,
		FloorMaterial = "Ground",
		state = "Running",
		IsA = function()
			return true
		end,
		StateChanged = signal(),
		GetState = function(self)
			return self.state
		end,
	}
	local character = {
		WaitForChild = function(_, name)
			return if name == "Humanoid" then humanoid else root
		end,
	}
	local node = {}
	function node:WaitForChild(name)
		return if name == "InputSampler" or name == "LatencyProbe" then name else self
	end
	node.Parent = node
	local services = {
		HttpService = {
			JSONEncode = function(_, value)
				return serde.encode("json", value)
			end,
		},
		Players = { LocalPlayer = { Character = character, CharacterAdded = signal() } },
		RunService = {
			PreRender = render,
			PostSimulation = signal(),
			IsStudio = function()
				return true
			end,
		},
		UserInputService = { InputBegan = input },
		Workspace = {
			CurrentCamera = { CFrame = roblox.CFrame.new() },
			GetAttribute = function()
				return nil
			end,
		},
		ReplicatedStorage = node,
	}
	local states = {}
	for _, name in
		{ "Running", "RunningNoPhysics", "Jumping", "Freefall", "Landed", "Climbing", "Swimming", "Seated", "Dead" }
	do
		states[name] = name
	end
	local clock = table.clone(os)
	clock.clock = function()
		return now
	end
	local module = luau.load(fs.readFile("src/client/DevTools/MeasurementHarness.luau"), {
		injectGlobals = true,
		environment = {
			game = {
				GetService = function(_, name)
					return services[name]
				end,
			},
			script = node,
			Enum = { HumanoidStateType = states, Material = { Air = "Air" } },
			Vector3 = V,
			os = clock,
			task = {
				spawn = function(fn, ...)
					fn(...)
				end,
			},
			require = function(name)
				return if name == "LatencyProbe"
					then Probe
					else {
						rawMove = function()
							return V.zero
						end,
					}
			end,
			print = function(line)
				table.insert(logs, serde.decode("json", string.sub(line, 16)))
			end,
		},
	})()
	module.start({ DevTools = { MeasureLatency = true, LatencyKeys = keys } })
	local function step(dt)
		now += dt
		render.fire(dt)
	end
	local function press(key)
		input.fire({ KeyCode = { Name = key } }, false)
	end
	local function latency()
		local result = {}
		for _, event in logs do
			if event.k == "l" then
				table.insert(result, event)
			end
		end
		return result
	end
	return root, humanoid, step, press, latency, logs, services
end

T.describe("MeasurementHarness event wiring", function()
	T.it("requires a fresh baseline for a replacement character", function()
		local root, humanoid, step, press, latency, logs, services = fixture()
		for _ = 1, 10 do
			step(0.02)
		end
		local replacement = table.clone(root)
		services.Players.LocalPlayer.CharacterAdded.fire({
			WaitForChild = function(_, name)
				return if name == "Humanoid" then humanoid else replacement
			end,
		})
		press("Space")
		T.eq(#latency(), 0)
		T.eq(logs[#logs].n, "latency_skipped")
	end)
	T.it("rejects a probe before the still baseline is established", function()
		local _, _, _, press, latency, logs = fixture()
		press("Space")
		T.eq(#latency(), 0)
		T.eq(logs[#logs].n, "latency_skipped")
	end)
	T.it("cancels a probe when an unwatched gameplay key overlaps", function()
		local root, humanoid, step, press, latency = fixture({ "Space" })
		for _ = 1, 10 do
			step(0.02)
		end
		press("Space")
		press("W")
		humanoid.state = "Jumping"
		root.AssemblyLinearVelocity = V.new(0, 10, 0)
		step(0.02)
		T.eq(#latency(), 0)
	end)
	T.it("skips pre-existing motion instead of counting it", function()
		local root, _, step, press, latency, logs = fixture()
		for _ = 1, 10 do
			step(0.02)
		end
		root.AssemblyLinearVelocity = V.new(10, 0, 0)
		press("Space")
		step(0.02)
		T.eq(#latency(), 0)
		T.eq(logs[#logs].n, "latency_skipped")
	end)
	T.it("ignores unrelated jump motion and records actual elapsed seconds", function()
		local root, humanoid, step, press, latency = fixture()
		for _ = 1, 10 do
			step(0.02)
		end
		press("Space")
		root.Position = V.new(1, 0, 0)
		root.AssemblyLinearVelocity = V.new(10, 0, 0)
		step(0.01)
		step(0.01)
		T.eq(#latency(), 0)
		humanoid.state = "Jumping"
		root.AssemblyLinearVelocity = V.new(0, 10, 0)
		step(0.1)
		T.eq(#latency(), 1)
		T.eq(latency()[1].f, 3)
		T.near(latency()[1].dt, 0.12, 1e-9)
	end)
	T.it("ignores movement opposite to the key and counts the matching response", function()
		local root, _, step, press, latency = fixture()
		for _ = 1, 10 do
			step(0.02)
		end
		press("W")
		root.Position, root.AssemblyLinearVelocity = V.new(0, 0, 1), V.new(0, 0, 10)
		step(0.02)
		T.eq(#latency(), 0)
		root.Position, root.AssemblyLinearVelocity = V.new(0, 0, -1), V.new(0, 0, -10)
		step(0.02)
		T.eq(#latency(), 1)
	end)
	T.it("cancels overlapping probes", function()
		local root, humanoid, step, press, latency = fixture()
		for _ = 1, 10 do
			step(0.02)
		end
		press("Space")
		press("W")
		humanoid.state = "Jumping"
		root.AssemblyLinearVelocity = V.new(0, 10, 0)
		step(0.02)
		T.eq(#latency(), 0)
	end)
end)
return nil
