--!strict
--[[
	ShotCamera (client): put the camera exactly on a reference shot for comparison captures.

	ShotCamera.apply({ position = Vector3.new(12, 9, -30), lookAt = Vector3.new(0, 4, 0),
	                   fov = 58.7, hideGui = true, clockTime = 14.5 })
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
	hideGui: boolean?,
	clockTime: number?,
}

local saved: { cameraType: Enum.CameraType, fov: number, clock: number, guis: { [ScreenGui]: boolean } }? = nil
local BIND = "RemakeShotCamera"

function ShotCamera.apply(shot: Shot)
	local camera = Workspace.CurrentCamera
	if not saved then
		saved = { cameraType = camera.CameraType, fov = camera.FieldOfView, clock = Lighting.ClockTime, guis = {} }
	end
	local state = saved :: any
	if shot.hideGui ~= false then
		local playerGui = Players.LocalPlayer:FindFirstChildOfClass("PlayerGui")
		if playerGui then
			for _, gui in playerGui:GetChildren() do
				if gui:IsA("ScreenGui") and state.guis[gui] == nil then
					state.guis[gui] = gui.Enabled
					gui.Enabled = false
				end
			end
		end
		pcall(function()
			StarterGui:SetCoreGuiEnabled(Enum.CoreGuiType.All, false)
		end)
	end
	if shot.clockTime then
		Lighting.ClockTime = shot.clockTime
	end
	local cf = CFrame.lookAt(shot.position, shot.lookAt)
	local fov = shot.fov or camera.FieldOfView
	pcall(function()
		RunService:UnbindFromRenderStep(BIND)
	end)
	-- Re-apply after other camera logic every frame so nothing drifts during the capture.
	RunService:BindToRenderStep(BIND, Enum.RenderPriority.Last.Value, function()
		camera.CameraType = Enum.CameraType.Scriptable
		camera.FieldOfView = fov
		camera.CFrame = cf
	end)
end

function ShotCamera.release()
	pcall(function()
		RunService:UnbindFromRenderStep(BIND)
	end)
	local state = saved
	if not state then
		return
	end
	local camera = Workspace.CurrentCamera
	camera.CameraType = state.cameraType
	camera.FieldOfView = state.fov
	Lighting.ClockTime = state.clock
	for gui, enabled in state.guis do
		if gui.Parent then
			gui.Enabled = enabled
		end
	end
	pcall(function()
		StarterGui:SetCoreGuiEnabled(Enum.CoreGuiType.All, true)
	end)
	saved = nil
end

-- Convert one shots.json entry (decoded with HttpService:JSONDecode) into a Shot.
function ShotCamera.fromJson(entry: { [string]: any }): Shot
	local cam = entry.camera
	return {
		id = entry.id,
		position = Vector3.new(cam.position[1], cam.position[2], cam.position[3]),
		lookAt = Vector3.new(cam.look_at[1], cam.look_at[2], cam.look_at[3]),
		fov = cam.fov,
		clockTime = entry.clock_time,
		hideGui = true,
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
