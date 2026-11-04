local roblox = require("@lune/roblox")
local T = require("./T")
local Spring = require("../../src/shared/Remake/Spring")

local function settleTime(omega: number, zeta: number): number
	local s = Spring.new(1, omega, zeta)
	s.target = 0
	local dt, t, last = 1 / 2000, 0, 0
	while t < 3 do
		s:step(dt)
		t += dt
		if math.abs(s.position) > 0.02 then
			last = t
		end
	end
	return last
end

T.describe("Spring", function()
	T.it("is exact regardless of step size", function()
		local a, b = Spring.new(0, 12, 0.5), Spring.new(0, 12, 0.5)
		a.target, b.target = 10, 10
		a:step(1)
		for _ = 1, 600 do
			b:step(1 / 600)
		end
		T.near(a.position, b.position, 1e-9)
		T.near(a.velocity, b.velocity, 1e-9)
	end)
	T.it("critically damped spring does not overshoot", function()
		local s = Spring.new(0, 16.6657, 1)
		s.target = 1
		local maxv = 0
		for _ = 1, 600 do
			maxv = math.max(maxv, s:step(1 / 240))
		end
		T.truthy(maxv <= 1 + 1e-9, `overshoot {maxv}`)
		T.near(s.position, 1, 1e-6)
	end)
	T.it("matches remake_calc spring settle times", function()
		T.near(settleTime(16.6657, 1.0), 0.35, 0.002, "critical")
		T.near(settleTime(17.0997, 0.6266), 0.35, 0.002, "underdamped")
	end)
	T.it("reproduces the overshoot implied by the damping ratio", function()
		local zeta = 0.6266
		local s = Spring.new(0, 10, zeta)
		s.target = 1
		local peak = 0
		for _ = 1, 4000 do
			peak = math.max(peak, s:step(1 / 2000))
		end
		local expected = math.exp(-zeta * math.pi / math.sqrt(1 - zeta * zeta))
		T.near(peak - 1, expected, 1e-4)
	end)
	T.it("overdamped spring converges without overshoot", function()
		local s = Spring.new(5, 8, 2.5)
		s.target = 0
		local minv = math.huge
		for _ = 1, 2000 do
			minv = math.min(minv, s:step(1 / 200))
		end
		T.truthy(minv >= -1e-9, `crossed target: {minv}`)
		T.near(s.position, 0, 1e-3)
	end)
	T.it("works with Vector3 values", function()
		local s = Spring.new(roblox.Vector3.new(0, 0, 0), 10, 1)
		s.target = roblox.Vector3.new(4, 2, -6)
		for _ = 1, 240 do
			s:step(1 / 60)
		end
		local p = s.position
		T.near(p.X, 4, 1e-4)
		T.near(p.Y, 2, 1e-4)
		T.near(p.Z, -6, 1e-4)
	end)
	T.it("snap and impulse", function()
		local s = Spring.new(0, 10, 1)
		s:snap(3)
		T.eq(s.position, 3)
		T.eq(s.velocity, 0)
		s:impulse(5)
		T.eq(s.velocity, 5)
		T.eq(s:step(0), 3, "zero dt keeps position")
	end)
	T.it("validates parameters", function()
		T.throws(function()
			Spring.new(0, 0, 1)
		end)
		T.throws(function()
			Spring.new(0, 1, -1)
		end)
	end)
end)

return nil
