-- Execute the real ShotCamera against service doubles; this is NOT Studio rendering.
local fs = require("@lune/fs")
local luau = require("@lune/luau")
local roblox = require("@lune/roblox")
local T = require("./T")

local function fixture()
	local function enum(names)
		local result = {}
		for _, name in names do
			result[name] = name
		end
		return result
	end
	local enums = {
		CameraType = enum({ "Custom", "Scriptable" }),
		ProjectionType = enum({ "Perspective", "Orthographic" }),
		OrthographicMode = enum({ "Vertical", "Horizontal" }),
		FieldOfViewMode = enum({ "Vertical", "Diagonal", "MaxAxis" }),
		CoreGuiType = enum({ "All", "Chat", "Backpack", "Health" }),
		RenderPriority = { Last = { Value = 2000 } },
	}
	function enums.CoreGuiType:GetEnumItems()
		return { "All", "Chat", "Backpack", "Health" }
	end
	local function gui(enabled, developer)
		return {
			Enabled = enabled,
			Parent = true,
			IsA = function()
				return true
			end,
			GetAttribute = function()
				return developer
			end,
		}
	end
	local hud, disabled, overlay = gui(true, false), gui(false, false), gui(true, true)
	local guis = { hud, disabled, overlay }
	local core = { Chat = false, Backpack = true, Health = false }
	local originalCore = table.clone(core)
	local camera = {
		CameraType = "Custom",
		FieldOfView = 71,
		FieldOfViewMode = "Diagonal",
		CFrame = roblox.CFrame.new(1, 2, 3),
		Focus = roblox.CFrame.new(4, 5, 6),
		ProjectionType = "Orthographic",
		OrthographicMode = "Horizontal",
		OrthographicSize = 90,
	}
	local original = table.clone(camera)
	local callback = nil
	local services = {
		Workspace = { CurrentCamera = camera },
		Lighting = { ClockTime = 12 },
		Players = {
			LocalPlayer = {
				FindFirstChildOfClass = function()
					return {
						GetChildren = function()
							return guis
						end,
					}
				end,
			},
		},
		RunService = {
			UnbindFromRenderStep = function()
				callback = nil
			end,
			BindToRenderStep = function(_, _, priority, fn)
				T.eq(priority, 2000)
				callback = fn
			end,
		},
		StarterGui = {
			GetCoreGuiEnabled = function(_, kind)
				return core[kind]
			end,
			SetCoreGuiEnabled = function(_, kind, enabled)
				if kind == "All" then
					for key in core do
						core[key] = enabled
					end
				else
					core[kind] = enabled
				end
			end,
		},
		UserInputService = {},
	}
	local module = luau.load(fs.readFile("src/client/ShotCamera.luau"), {
		environment = {
			game = {
				GetService = function(_, name)
					return services[name]
				end,
			},
			Enum = enums,
			Vector3 = roblox.Vector3,
			CFrame = roblox.CFrame,
		},
		injectGlobals = true,
	})()
	return module, camera, original, core, originalCore, guis, function()
		callback()
	end, services
end

T.describe("ShotCamera mocked services", function()
	T.it("keeps HUD, hides developer overlays, restores disabled GUI and CoreGui states", function()
		local shot, _, _, core, originalCore, guis, render = fixture()
		shot.apply({
			position = roblox.Vector3.new(0, 2, 10),
			lookAt = roblox.Vector3.zero,
			guiPolicy = "hide_developer",
		})
		render()
		T.eq(guis[1].Enabled, true)
		T.eq(guis[2].Enabled, false)
		T.eq(guis[3].Enabled, false)
		shot.release()
		T.eq(guis[3].Enabled, true)
		for key, value in originalCore do
			T.eq(core[key], value)
		end
	end)
	T.it("restores each CoreGui flag after hide-all and policy switches", function()
		local shot, _, _, core, originalCore, guis = fixture()
		local entry = { position = roblox.Vector3.new(0, 2, 10), lookAt = roblox.Vector3.zero, guiPolicy = "hide_all" }
		shot.apply(entry)
		for _, gui in guis do
			T.eq(gui.Enabled, false)
		end
		for key in originalCore do
			T.eq(core[key], false)
		end
		entry.guiPolicy = "keep"
		shot.apply(entry)
		T.eq(guis[1].Enabled, true)
		T.eq(guis[2].Enabled, false)
		T.eq(guis[3].Enabled, true)
		for key, value in originalCore do
			T.eq(core[key], value)
		end
		shot.release()
	end)
	for _, projection in { "Perspective", "Orthographic" } do
		T.it(`overrides rig with {projection} then restores full camera`, function()
			local shot, camera, original, _, _, _, render, services = fixture()
			camera.ProjectionType = if projection == "Perspective" then "Orthographic" else "Perspective"
			original.ProjectionType = camera.ProjectionType
			shot.apply({
				position = roblox.Vector3.new(0, 2, 10),
				lookAt = roblox.Vector3.zero,
				projection = projection,
				fov = 55,
				fovMode = "Vertical",
				orthographicSize = 40,
				orthographicAxis = "Vertical",
				clockTime = 18,
				guiPolicy = "keep",
			})
			-- Simulate the earlier CameraRig render binding.
			camera.ProjectionType = "rig"
			render()
			T.eq(camera.ProjectionType, projection)
			T.eq(camera.FieldOfViewMode, "Vertical")
			T.eq(camera.FieldOfView, 55)
			if projection == "Orthographic" then
				T.eq(camera.OrthographicSize, 40)
			end
			shot.release()
			for key, value in original do
				T.eq(camera[key], value, key)
			end
			T.eq(services.Lighting.ClockTime, 12)
			shot.release() -- idempotent
		end)
	end
	T.it("converts JSON projection and visibility", function()
		local shot = fixture()
		local result = shot.fromJson({
			id = "HUD",
			gui_policy = "keep",
			camera = {
				position = { 0, 2, 10 },
				look_at = { 0, 0, 0 },
				projection = "orthographic",
				orthographic_size = 40,
				orthographic_axis = "Horizontal",
			},
		})
		T.eq(result.guiPolicy, "keep")
		T.eq(result.projection, "Orthographic")
		T.eq(result.orthographicSize, 40)
		T.throws(function()
			shot.fromJson({ camera = { position = { 0, 2, 10 }, look_at = { 0, 0, 0 }, projection = "typo" } })
		end)
	end)
end)
return nil
