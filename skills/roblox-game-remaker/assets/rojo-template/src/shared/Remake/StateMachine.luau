--!strict
--[[
	StateMachine: explicit states with enter, exit and update hooks and a transition history.

	local sm = StateMachine.new({
		Idle = { enter = function(sm, from) end },
		Run = { update = function(sm, dt) end },
	}, "Idle")
	sm:transition("Run")
	sm:update(dt)

	The history (bounded) makes it easy to compare state timings with reference footage.
]]

local StateMachine = {}
StateMachine.__index = StateMachine

export type StateDef = {
	enter: ((sm: any, from: string?, data: any?) -> ())?,
	exit: ((sm: any, to: string) -> ())?,
	update: ((sm: any, dt: number) -> ())?,
}

export type Transition = { from: string?, to: string, at: number }

export type StateMachine = {
	states: { [string]: StateDef },
	state: string,
	timeInState: number,
	clock: number,
	history: { Transition },
	maxHistory: number,
	onTransition: ((from: string?, to: string, at: number) -> ())?,
	transition: (self: StateMachine, to: string, data: any?, force: boolean?) -> boolean,
	update: (self: StateMachine, dt: number) -> (),
	is: (self: StateMachine, name: string) -> boolean,
}

function StateMachine.new(
	states: { [string]: StateDef },
	initial: string,
	onTransition: ((from: string?, to: string, at: number) -> ())?
): StateMachine
	assert(states[initial], `unknown initial state {initial}`)
	local self = {
		states = states,
		state = initial,
		timeInState = 0,
		clock = 0,
		history = { { from = nil, to = initial, at = 0 } },
		maxHistory = 256,
		onTransition = onTransition,
	}
	local sm = (setmetatable(self, StateMachine) :: any) :: StateMachine
	local def = states[initial]
	if def.enter then
		def.enter(sm, nil, nil)
	end
	return sm
end

-- Returns true when a transition happened. Same-state transitions are ignored unless force.
function StateMachine.transition(self: StateMachine, to: string, data: any?, force: boolean?): boolean
	local target = self.states[to]
	assert(target, `unknown state {to}`)
	if to == self.state and not force then
		return false
	end
	local from = self.state
	local current = self.states[from]
	if current.exit then
		current.exit(self, to)
	end
	self.state = to
	self.timeInState = 0
	table.insert(self.history, { from = from, to = to, at = self.clock })
	if #self.history > self.maxHistory then
		table.remove(self.history, 1)
	end
	if target.enter then
		target.enter(self, from, data)
	end
	if self.onTransition then
		self.onTransition(from, to, self.clock)
	end
	return true
end

function StateMachine.update(self: StateMachine, dt: number)
	self.clock += dt
	self.timeInState += dt
	local def = self.states[self.state]
	if def.update then
		def.update(self, dt)
	end
end

function StateMachine.is(self: StateMachine, name: string): boolean
	return self.state == name
end

return StateMachine
