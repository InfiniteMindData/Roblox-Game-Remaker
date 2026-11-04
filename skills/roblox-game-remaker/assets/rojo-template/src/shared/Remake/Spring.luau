--!strict
--[[
	Spring: closed-form damped harmonic oscillator.

	Exact for any dt, so it behaves the same at 30, 60 or 240 fps. Works with numbers and with
	vector types that support +, - and * number (Vector2, Vector3). Get the parameters from
	measured footage with: remake_calc.py spring --overshoot <fraction> --settle-time <s>

	local s = Spring.new(0, 16.67, 1.0)  -- angular frequency (rad/s), damping ratio
	s.target = 10
	local position = s:step(dt)
]]

local Spring = {}
Spring.__index = Spring

type Value = any

export type Spring = {
	position: Value,
	velocity: Value,
	target: Value,
	angularFrequency: number,
	dampingRatio: number,
	step: (self: Spring, dt: number) -> Value,
	snap: (self: Spring, value: Value) -> (),
	impulse: (self: Spring, deltaVelocity: Value) -> (),
}

function Spring.new(initial: Value, angularFrequency: number, dampingRatio: number): Spring
	assert(angularFrequency > 0, "angularFrequency must be positive")
	assert(dampingRatio >= 0, "dampingRatio must be >= 0")
	local self = {
		position = initial,
		velocity = initial * 0,
		target = initial,
		angularFrequency = angularFrequency,
		dampingRatio = dampingRatio,
	}
	return (setmetatable(self, Spring) :: any) :: Spring
end

function Spring.step(self: Spring, dt: number): Value
	if dt <= 0 then
		return self.position
	end
	local w = self.angularFrequency
	local z = self.dampingRatio
	local x0 = self.position - self.target
	local v0 = self.velocity
	local x, v
	if math.abs(z - 1) < 1e-4 then
		-- critically damped
		local e = math.exp(-w * dt)
		local b = v0 + x0 * w
		x = (x0 + b * dt) * e
		v = (v0 - b * (w * dt)) * e
	elseif z < 1 then
		-- underdamped (z = 0 is undamped)
		local wd = w * math.sqrt(1 - z * z)
		local e = math.exp(-z * w * dt)
		local c, s = math.cos(wd * dt), math.sin(wd * dt)
		x = (x0 * c + (v0 + x0 * (z * w)) * (s / wd)) * e
		v = (v0 * c - (x0 * (w * w) + v0 * (z * w)) * (s / wd)) * e
	else
		-- overdamped
		local root = math.sqrt(z * z - 1)
		local r1 = -w * (z - root)
		local r2 = -w * (z + root)
		local c2 = (v0 - x0 * r1) * (1 / (r2 - r1))
		local c1 = x0 - c2
		local e1, e2 = math.exp(r1 * dt), math.exp(r2 * dt)
		x = c1 * e1 + c2 * e2
		v = c1 * (r1 * e1) + c2 * (r2 * e2)
	end
	self.position = self.target + x
	self.velocity = v
	return self.position
end

function Spring.snap(self: Spring, value: Value)
	self.position = value
	self.target = value
	self.velocity = value * 0
end

function Spring.impulse(self: Spring, deltaVelocity: Value)
	self.velocity = self.velocity + deltaVelocity
end

return Spring
