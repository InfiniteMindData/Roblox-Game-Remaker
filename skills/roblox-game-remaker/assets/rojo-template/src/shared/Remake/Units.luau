--!strict
--[[
	Units: unit, FOV, timing and jump conversions for 1:1 remakes.

	Pure Luau with no Roblox APIs, so it runs in Studio and in Lune unit tests.
	Facts from the Roblox creator docs: 1 stud is about 28 cm; Workspace.Gravity defaults to
	196.2 studs/s^2; Camera.FieldOfView is the vertical field of view.
]]

local Units = {}

Units.METERS_PER_STUD = 0.28
Units.STUDS_PER_METER = 1 / Units.METERS_PER_STUD
Units.ROBLOX_DEFAULT_GRAVITY = 196.2

function Units.studsFromMeters(meters: number, studsPerMeter: number?): number
	return meters * (studsPerMeter or Units.STUDS_PER_METER)
end

function Units.metersFromStuds(studs: number, studsPerMeter: number?): number
	return studs / (studsPerMeter or Units.STUDS_PER_METER)
end

-- Field of view conventions (degrees). aspect = width / height.
function Units.verticalFromHorizontalFov(horizontalDeg: number, aspect: number): number
	return math.deg(2 * math.atan(math.tan(math.rad(horizontalDeg) / 2) / aspect))
end

function Units.horizontalFromVerticalFov(verticalDeg: number, aspect: number): number
	return math.deg(2 * math.atan(math.tan(math.rad(verticalDeg) / 2) * aspect))
end

function Units.secondsFromFrames(frames: number, fps: number): number
	assert(fps > 0, "fps must be positive")
	return frames / fps
end

function Units.framesFromSeconds(seconds: number, fps: number): number
	assert(fps > 0, "fps must be positive")
	return seconds * fps
end

export type JumpSolution = {
	takeoffSpeed: number,
	riseGravity: number,
	fallGravity: number,
	fallMultiplier: number,
	airtime: number,
}

-- Solve a jump from its apex height and rise time (and optional fall time).
-- Returns the takeoff speed and the gravities that reproduce it exactly.
function Units.solveJump(apex: number, riseTime: number, fallTime: number?): JumpSolution
	assert(apex > 0 and riseTime > 0, "apex and riseTime must be positive")
	local fall = fallTime or riseTime
	assert(fall > 0, "fallTime must be positive")
	local riseGravity = 2 * apex / (riseTime * riseTime)
	local fallGravity = 2 * apex / (fall * fall)
	return {
		takeoffSpeed = 2 * apex / riseTime,
		riseGravity = riseGravity,
		fallGravity = fallGravity,
		fallMultiplier = fallGravity / riseGravity,
		airtime = riseTime + fall,
	}
end

-- Height reached by a takeoff speed under a gravity (h = v^2 / 2g).
function Units.jumpHeightFromSpeed(speed: number, gravity: number): number
	return speed * speed / (2 * gravity)
end

-- Takeoff speed needed for a height under a gravity (v = sqrt(2gh)).
function Units.jumpSpeedFromHeight(height: number, gravity: number): number
	return math.sqrt(2 * gravity * height)
end

return Units
