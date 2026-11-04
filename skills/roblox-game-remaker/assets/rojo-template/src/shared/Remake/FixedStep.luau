--!strict
--[[
	FixedStep: run logic at the original game's fixed tick rate, independent of render rate.

	local stepper = FixedStep.new(60, 8)
	RunService.PreSimulation:Connect(function(dt)
		local steps, alpha = stepper:advance(dt, function(tickDt, tick) simulate(tickDt) end)
		render(alpha) -- interpolate between the last two simulated states
	end)

	Frame data such as "12 frames of startup at 60 Hz" stays exact. When a frame takes too long,
	at most maxSteps ticks run and the remaining backlog is dropped (counted in droppedTicks), so a
	slow frame cannot snowball.
]]

local FixedStep = {}
FixedStep.__index = FixedStep

local EPSILON = 1e-9

export type FixedStep = {
	rate: number,
	dt: number,
	maxSteps: number,
	accumulator: number,
	tick: number,
	droppedTicks: number,
	advance: (self: FixedStep, frameDt: number, stepFn: (dt: number, tick: number) -> ()) -> (number, number),
	reset: (self: FixedStep) -> (),
}

function FixedStep.new(rate: number, maxSteps: number?): FixedStep
	assert(rate > 0, "rate must be positive")
	local self = {
		rate = rate,
		dt = 1 / rate,
		maxSteps = maxSteps or 8,
		accumulator = 0,
		tick = 0,
		droppedTicks = 0,
	}
	return (setmetatable(self, FixedStep) :: any) :: FixedStep
end

-- Returns (ticks run this frame, interpolation alpha in [0, 1)).
function FixedStep.advance(self: FixedStep, frameDt: number, stepFn: (dt: number, tick: number) -> ()): (number, number)
	if frameDt > 0 then
		self.accumulator += frameDt
	end
	local steps = 0
	while self.accumulator + EPSILON >= self.dt and steps < self.maxSteps do
		self.tick += 1
		stepFn(self.dt, self.tick)
		self.accumulator -= self.dt
		steps += 1
	end
	if self.accumulator + EPSILON >= self.dt then
		local backlog = math.floor((self.accumulator + EPSILON) / self.dt)
		self.droppedTicks += backlog
		self.accumulator -= backlog * self.dt
	end
	if self.accumulator < 0 then
		self.accumulator = 0
	end
	return steps, self.accumulator / self.dt
end

function FixedStep.reset(self: FixedStep)
	self.accumulator = 0
	self.tick = 0
	self.droppedTicks = 0
end

return FixedStep
