--!strict
--[[
	ShotCamera (client): put the camera exactly on a reference shot for comparison captures.

	ShotCamera.apply({ position = Vector3.new(12, 9, -30), lookAt = Vector3.new(0, 4, 0),
	                   fov = 58.7, guiPolicy = "hide_developer", clockTime = 14.5 })
	-- capture (MCP screen_capture, or a screenshot at the reference resolution)
	ShotCamera.release()

	Shots come from remake/shots.json (camera.position, camera.look_at, camera.fov, clock_time).
	Copy them into ReplicatedStorage.Shared.Remake.Shots (a ModuleScript returning a list) to use
	the Studio hotkeys: F7 = next shot, F8 = release. Hotkeys only run in Studio.
]]

local Lighting = game:GetService("Lighting")
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local StarterGui = game:GetService("StarterGui")
local UserInputService = game:GetService("UserInputService")
local Workspace = game:GetService("Workspace")

local ShotCamera = {}

export type Shot = {
	id: string?,
	position: Vector3,
	lookAt: Vector3,
	fov: number?,
	fovMode: string?,
	projection: string?,
	orthographicSize: number?,
	orthographicAxis: string?,
	guiPolicy: string?, -- keep | hide_developer (default) | hide_all
	hideGui: boolean?, -- legacy: true = hide_all; false = keep
	clockTime: number?,
}

-- Save the camera instance, not just CurrentCamera: another system may replace it.
local saved: any = nil
local BIND = "RemakeShotCamera"
local CAMERA_PROPERTIES = {
	"CameraType",
	"FieldOfViewMode",
	"FieldOfView",
	"CFrame",
	"Focus",
	"ProjectionType",
	"OrthographicMode",
	"OrthographicSize",
}

function ShotCamera.release()
	RunService:UnbindFromRenderStep(BIND)
	local state = saved
	if not state then
		return
	end
	for _, property in CAMERA_PROPERTIES do
		(state.camera :: any)[property] = state.properties[property]
	end
	Lighting.ClockTime = state.clock
	for gui, enabled in state.guis do
		if gui.Parent then
			gui.Enabled = enabled
		end
	end
	for kind, enabled in state.core do
		pcall(function()
			StarterGui:SetCoreGuiEnabled(kind, enabled)
		end)
	end
	saved = nil
end

function ShotCamera.apply(shot: Shot)
	local policy = shot.guiPolicy
		or (if shot.hideGui == true then "hide_all" elseif shot.hideGui == false then "keep" else "hide_developer")
	assert(policy == "keep" or policy == "hide_developer" or policy == "hide_all", "unknown shot GUI policy")
	local projection = shot.projection or "Perspective"
	assert(projection == "Perspective" or projection == "Orthographic", "unknown shot projection")
	assert((Enum.FieldOfViewMode :: any)[shot.fovMode or "Vertical"], "unknown shot FOV mode")
	assert((Enum.OrthographicMode :: any)[shot.orthographicAxis or "Vertical"], "unknown orthographic axis")
	if projection == "Orthographic" then
		assert(
			shot.orthographicSize and shot.orthographicSize > 0 and shot.orthographicSize < math.huge,
			"orthographic shot needs positive finite size"
		)
	end
	-- Switching shots restores prior visibility before applying the new policy.
	ShotCamera.release()
	local camera = Workspace.CurrentCamera
	if not camera then
		return
	end
	local state = {
		camera = camera,
		properties = {} :: { [string]: any },
		clock = Lighting.ClockTime,
		guis = {} :: { [ScreenGui]: boolean },
		core = {} :: { [Enum.CoreGuiType]: boolean },
	}
	for _, property in CAMERA_PROPERTIES do
		state.properties[property] = (camera :: any)[property]
	end
	saved = state
	local playerGui = Players.LocalPlayer:FindFirstChildOfClass("PlayerGui")
	if playerGui then
		for _, gui in playerGui:GetChildren() do
			if
				gui:IsA("ScreenGui")
				and (
					policy == "hide_all"
					or (policy == "hide_developer" and gui:GetAttribute("RemakeDeveloperOverlay") == true)
				)
			then
				if gui.Enabled then
					state.guis[gui] = gui.Enabled
					gui.Enabled = false
				end
			end
		end
	end
	if policy == "hide_all" then
		for _, kind in Enum.CoreGuiType:GetEnumItems() do
			if kind ~= Enum.CoreGuiType.All then
				pcall(function()
					local enabled = StarterGui:GetCoreGuiEnabled(kind)
					if enabled then
						StarterGui:SetCoreGuiEnabled(kind, false)
						state.core[kind] = enabled
					end
				end)
			end
		end
	end
	if shot.clockTime then
		Lighting.ClockTime = shot.clockTime
	end
	local cf = CFrame.lookAt(shot.position, shot.lookAt)
	local fov = shot.fov or camera.FieldOfView
	-- Last runs after CameraRig: projection, focus and framing must all win.
	RunService:BindToRenderStep(BIND, Enum.RenderPriority.Last.Value, function()
		camera.CameraType = Enum.CameraType.Scriptable
		camera.ProjectionType = (Enum.ProjectionType :: any)[projection]
		camera.FieldOfViewMode = (Enum.FieldOfViewMode :: any)[shot.fovMode or "Vertical"]
		camera.FieldOfView = fov
		if projection == "Orthographic" then
			camera.OrthographicMode = (Enum.OrthographicMode :: any)[shot.orthographicAxis or "Vertical"]
			camera.OrthographicSize = shot.orthographicSize :: number
		end
		camera.CFrame = cf
		camera.Focus = CFrame.new(shot.lookAt)
	end)
end

-- Convert one shots.json entry (decoded with HttpService:JSONDecode) into a Shot.
function ShotCamera.fromJson(entry: { [string]: any }): Shot
	local cam = entry.camera
	local projection = cam.projection or "perspective"
	assert(projection == "perspective" or projection == "orthographic", "unknown JSON shot projection")
	return {
		id = entry.id,
		position = Vector3.new(cam.position[1], cam.position[2], cam.position[3]),
		lookAt = Vector3.new(cam.look_at[1], cam.look_at[2], cam.look_at[3]),
		fov = cam.fov,
		fovMode = cam.fov_mode,
		projection = if projection == "orthographic" then "Orthographic" else "Perspective",
		orthographicSize = cam.orthographic_size,
		orthographicAxis = cam.orthographic_axis,
		clockTime = entry.clock_time,
		guiPolicy = entry.gui_policy or "hide_developer",
	}
end

function ShotCamera.installHotkeys(shots: { Shot }): () -> ()
	if not RunService:IsStudio() or #shots == 0 then
		return function() end
	end
	local index = 0
	local conn = UserInputService.InputBegan:Connect(function(input, processed)
		if processed then
			return
		end
		if input.KeyCode == Enum.KeyCode.F7 then
			index = index % #shots + 1
			ShotCamera.apply(shots[index])
			print(`ShotCamera: {shots[index].id or index} ({index}/{#shots})`)
		elseif input.KeyCode == Enum.KeyCode.F8 then
			ShotCamera.release()
		end
	end)
	return function()
		conn:Disconnect()
	end
end

return ShotCamera
