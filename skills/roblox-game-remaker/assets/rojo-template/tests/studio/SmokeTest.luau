--[[
	SmokeTest: checks that the remake template is installed and its config is applied.

	Run it one of these ways (it prints REMAKE_SMOKE lines and returns a summary table):
	  * Studio MCP: execute_luau with datamodel_type "Server" during a playtest (full checks), or
	  "Edit" outside play (structure checks only).
	  * Studio command bar: paste and run.
	  * Studio CLI (Windows/macOS):
	      RobloxStudio --task RunScript --localPlaceFile <abs path>.rbxlx \
	        --runScriptFile <abs path>/SmokeTest.luau --outputFile smoke.log --quitAfterExecution
	    (edit-mode structure checks; Bootstrap only runs in play mode)
]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local ServerScriptService = game:GetService("ServerScriptService")
local StarterPlayer = game:GetService("StarterPlayer")
local Workspace = game:GetService("Workspace")

local passed, failed = 0, 0
local function check(name: string, ok: boolean, detail: string?)
	if ok then
		passed += 1
		print(`REMAKE_SMOKE PASS {name}`)
	else
		failed += 1
		warn(`REMAKE_SMOKE FAIL {name}{if detail then ": " .. detail else ""}`)
	end
end

local shared = ReplicatedStorage:FindFirstChild("Shared")
local remake = shared and shared:FindFirstChild("Remake")
check("ReplicatedStorage.Shared.Remake exists", remake ~= nil)
for _, name in { "Config", "Units", "Spring", "FixedStep", "StateMachine", "MovementMath", "Easing", "LightingPreset" } do
	local m = remake and remake:FindFirstChild(name)
	check(`module {name}`, m ~= nil and m:IsA("ModuleScript"))
end
local server = ServerScriptService:FindFirstChild("Remake")
local bootstrap = server and server:FindFirstChild("Bootstrap")
check("server Bootstrap script", bootstrap ~= nil and bootstrap:IsA("Script"))
local client = StarterPlayer:FindFirstChild("StarterPlayerScripts")
local clientRemake = client and client:FindFirstChild("Remake")
local main = clientRemake and clientRemake:FindFirstChild("Main")
check("client Main LocalScript", main ~= nil and main:IsA("LocalScript"))

if remake then
	local ok, Config = pcall(require, remake:FindFirstChild("Config"))
	check("Config loads", ok, if ok then nil else tostring(Config))
	if ok then
		local Units = require(remake:FindFirstChild("Units"))
		check("Units FOV conversion", math.abs(Units.verticalFromHorizontalFov(90, 16 / 9) - 58.7155) < 1e-3)
		if RunService:IsRunning() and RunService:IsServer() then
			check("Bootstrap ran", Workspace:GetAttribute("RemakeBootstrapped") == true)
			check(
				"Workspace.Gravity applied",
				math.abs(Workspace.Gravity - Config.World.Gravity) < 1e-3,
				`{Workspace.Gravity} vs {Config.World.Gravity}`
			)
			check("UseJumpPower off", StarterPlayer.CharacterUseJumpPower == false)
			check("JumpHeight applied", math.abs(StarterPlayer.CharacterJumpHeight - Config.Movement.JumpApex) < 1e-3)
			check("WalkSpeed applied", math.abs(StarterPlayer.CharacterWalkSpeed - Config.Movement.WalkSpeed) < 1e-3)
		else
			print("REMAKE_SMOKE INFO not running as server in play mode: runtime checks skipped")
		end
	end
end

print(`REMAKE_SMOKE SUMMARY {passed} passed, {failed} failed`)
return { passed = passed, failed = failed }
