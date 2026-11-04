local T = require("./T")
local StateMachine = require("../../src/shared/Remake/StateMachine")

T.describe("StateMachine", function()
	T.it("calls enter and exit in order and records history", function()
		local log = {}
		local sm = StateMachine.new({
			Idle = {
				enter = function(_, from)
					table.insert(log, `enter Idle from {from}`)
				end,
				exit = function(_, to)
					table.insert(log, `exit Idle to {to}`)
				end,
			},
			Run = {
				enter = function(_, from, data)
					table.insert(log, `enter Run from {from} {data}`)
				end,
			},
		}, "Idle")
		sm:update(0.5)
		T.truthy(sm:transition("Run", "fast"))
		T.eq(log[1], "enter Idle from nil")
		T.eq(log[2], "exit Idle to Run")
		T.eq(log[3], "enter Run from Idle fast")
		T.eq(sm.history[2].at, 0.5)
		T.eq(sm.timeInState, 0)
	end)
	T.it("ignores same-state transitions unless forced", function()
		local entered = 0
		local sm = StateMachine.new({
			A = {
				enter = function()
					entered += 1
				end,
			},
		}, "A")
		T.eq(sm:transition("A"), false)
		T.eq(sm:transition("A", nil, true), true)
		T.eq(entered, 2)
	end)
	T.it("tracks time in state and runs update hooks", function()
		local updates = 0
		local sm = StateMachine.new({
			A = {
				update = function(_, dt)
					updates += dt
				end,
			},
		}, "A")
		sm:update(0.25)
		sm:update(0.25)
		T.near(sm.timeInState, 0.5, 1e-12)
		T.near(updates, 0.5, 1e-12)
		T.truthy(sm:is("A"))
	end)
	T.it("rejects unknown states", function()
		T.throws(function()
			StateMachine.new({ A = {} }, "B")
		end)
		local sm = StateMachine.new({ A = {} }, "A")
		T.throws(function()
			sm:transition("Nope")
		end)
	end)
end)

return nil
