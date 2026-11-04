--!strict
--[[
	Handles: references to the running client systems, filled in by Main.client.luau.

	local Handles = require(StarterPlayerScripts path .. Remake.Handles)
	Handles.camera.shake(2, 12, 0.3)          -- amplitude deg, frequency Hz, duration s
	Handles.animation.playAction("Attack1")
	local hand = Handles.vr.getHandCFrame("Right")
]]

local Handles = {
	camera = nil :: any,
	animation = nil :: any,
	vr = nil :: any,
}

return Handles
