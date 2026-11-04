--!strict
--[[
	MovementMath: pure helpers for movement feel (no Roblox APIs; unit tested in Lune).

	- approach / approachPlanar: move a value toward a target by at most a maximum delta
	- rampRate: acceleration from a top speed and a ramp duration
	- expApproach: exponential approach with a time constant
	- JumpAssist: coyote time and jump buffering as a deterministic state machine
]]

local MovementMath = {}

function MovementMath.approach(current: number, target: number, maxDelta: number): number
	if current < target then
		return math.min(current + maxDelta, target)
	end
	return math.max(current - maxDelta, target)
end

-- Planar (x, z) approach: moves the vector toward the target by at most maxDelta in length.
function MovementMath.approachPlanar(cx: number, cz: number, tx: number, tz: number, maxDelta: number): (number, number)
	local dx, dz = tx - cx, tz - cz
	local dist = math.sqrt(dx * dx + dz * dz)
	if dist <= maxDelta or dist < 1e-9 then
		return tx, tz
	end
	local k = maxDelta / dist
	return cx + dx * k, cz + dz * k
end

-- Linear ramp rate (units/s^2) to reach topSpeed in rampTime seconds; 0 means instant.
function MovementMath.rampRate(topSpeed: number, rampTime: number): number
	if rampTime <= 0 then
		return math.huge
	end
	return topSpeed / rampTime
end

function MovementMath.expApproach(current: number, target: number, tau: number, dt: number): number
	if tau <= 0 then
		return target
	end
	return target + (current - target) * math.exp(-dt / tau)
end

export type JumpReason = "ground" | "coyote" | "buffer"

export type JumpAssist = {
	coyoteTime: number,
	bufferTime: number,
	sinceGrounded: number,
	sincePressed: number,
	pressedWhileGrounded: boolean,
	jumpedSinceGrounded: boolean,
	update: (self: JumpAssist, dt: number, grounded: boolean, pressedThisFrame: boolean) -> JumpReason?,
	notifyJumped: (self: JumpAssist) -> (),
}

local JumpAssist = {}
JumpAssist.__index = JumpAssist
MovementMath.JumpAssist = JumpAssist

function JumpAssist.new(coyoteTime: number, bufferTime: number): JumpAssist
	local self = {
		coyoteTime = math.max(0, coyoteTime),
		bufferTime = math.max(0, bufferTime),
		sinceGrounded = 0,
		sincePressed = math.huge,
		pressedWhileGrounded = false,
		jumpedSinceGrounded = false,
	}
	return (setmetatable(self, JumpAssist) :: any) :: JumpAssist
end

--[[
	Call once per frame. Returns why a jump should start now, or nil:
	  "ground"  pressed while grounded (the default Humanoid jump handles this)
	  "coyote"  pressed shortly after walking off a ledge
	  "buffer"  pressed shortly before landing
]]
function JumpAssist.update(self: JumpAssist, dt: number, grounded: boolean, pressedThisFrame: boolean): JumpReason?
	if grounded then
		self.sinceGrounded = 0
		self.jumpedSinceGrounded = false
	else
		self.sinceGrounded += dt
	end
	if pressedThisFrame then
		self.sincePressed = 0
		self.pressedWhileGrounded = grounded
	else
		self.sincePressed += dt
	end
	if self.sincePressed > self.bufferTime and not pressedThisFrame then
		return nil
	end
	local reason: JumpReason? = nil
	if grounded then
		reason = if self.pressedWhileGrounded then "ground" else "buffer"
	elseif not self.jumpedSinceGrounded and self.sinceGrounded <= self.coyoteTime and pressedThisFrame then
		reason = "coyote"
	end
	if reason then
		self.sincePressed = math.huge
		self.jumpedSinceGrounded = true
	end
	return reason
end

-- Call when a jump actually starts (for example on Humanoid state Jumping).
function JumpAssist.notifyJumped(self: JumpAssist)
	self.jumpedSinceGrounded = true
	self.sincePressed = math.huge
end

return MovementMath
