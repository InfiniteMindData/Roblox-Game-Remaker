--!strict
--[[
	Shots: matched reference shots for ShotCamera (Studio hotkeys F7 = next, F8 = release).

	Copy entries from remake/shots.json. Example:
	{ id = "SHOT-03", position = Vector3.new(12, 9, -30), lookAt = Vector3.new(0, 4, 0), fov = 58.7, clockTime = 14.5 },
]]

local Shots: { { [string]: any } } = {}

return Shots
