local T = require("./T")
local MovementMath = require("../../src/shared/Remake/MovementMath")
local JumpAssist = MovementMath.JumpAssist

local DT = 1 / 60

T.describe("MovementMath", function()
	T.it("approach clamps to the target", function()
		T.eq(MovementMath.approach(0, 10, 3), 3)
		T.eq(MovementMath.approach(9, 10, 3), 10)
		T.eq(MovementMath.approach(10, 0, 4), 6)
	end)
	T.it("approachPlanar moves at most maxDelta", function()
		local x, z = MovementMath.approachPlanar(0, 0, 3, 4, 2)
		T.near(math.sqrt(x * x + z * z), 2, 1e-12)
		T.near(x / z, 0.75, 1e-12)
		local x2, z2 = MovementMath.approachPlanar(0, 0, 3, 4, 10)
		T.eq(x2, 3)
		T.eq(z2, 4)
	end)
	T.it("a linear ramp reaches top speed after the ramp time", function()
		local rate = MovementMath.rampRate(20, 0.2)
		T.eq(rate, 100)
		local speed, t = 0, 0
		while speed < 20 do
			speed = MovementMath.approach(speed, 20, rate * DT)
			t += DT
		end
		T.near(t, 0.2, DT + 1e-9)
		T.eq(MovementMath.rampRate(20, 0), math.huge)
	end)
	T.it("expApproach reaches 90% after tau * ln(10)", function()
		local tau = 0.0782
		local v = MovementMath.expApproach(0, 20, tau, tau * math.log(10))
		T.near(v, 18, 1e-9)
	end)
end)

T.describe("JumpAssist", function()
	T.it("reports a grounded press as 'ground'", function()
		local a = JumpAssist.new(0.1, 0.1)
		T.eq(a:update(DT, true, true), "ground")
	end)
	T.it("allows a coyote jump inside the window only", function()
		local a = JumpAssist.new(0.1, 0)
		a:update(DT, true, false)
		for _ = 1, 4 do -- 4 frames (66 ms) after leaving the ledge
			a:update(DT, false, false)
		end
		T.eq(a:update(DT, false, true), "coyote")
		local b = JumpAssist.new(0.1, 0)
		b:update(DT, true, false)
		for _ = 1, 9 do -- 150 ms
			b:update(DT, false, false)
		end
		T.eq(b:update(DT, false, true), nil)
	end)
	T.it("gives no coyote jump after a real jump", function()
		local a = JumpAssist.new(0.2, 0)
		a:update(DT, true, false)
		a:notifyJumped()
		a:update(DT, false, false)
		T.eq(a:update(DT, false, true), nil)
	end)
	T.it("buffers a press made shortly before landing", function()
		local a = JumpAssist.new(0, 0.1)
		a:update(DT, false, false)
		a:update(DT, false, true) -- pressed in the air
		a:update(DT, false, false)
		a:update(DT, false, false) -- 50 ms later
		T.eq(a:update(DT, true, false), "buffer")
	end)
	T.it("forgets a press made too early", function()
		local a = JumpAssist.new(0, 0.1)
		a:update(DT, false, true)
		for _ = 1, 12 do -- 200 ms
			a:update(DT, false, false)
		end
		T.eq(a:update(DT, true, false), nil)
	end)
	T.it("does not double-fire a buffered jump", function()
		local a = JumpAssist.new(0, 0.1)
		a:update(DT, false, true)
		T.eq(a:update(DT, true, false), "buffer")
		T.eq(a:update(DT, true, false), nil)
	end)
end)

return nil
