local T = require("./T")
local FixedStep = require("../../src/shared/Remake/FixedStep")

T.describe("FixedStep", function()
	T.it("runs one tick per 1/60 s frame at 60 Hz", function()
		local fs = FixedStep.new(60)
		local ticks = 0
		for _ = 1, 600 do
			fs:advance(1 / 60, function()
				ticks += 1
			end)
		end
		T.eq(ticks, 600)
	end)
	T.it("keeps the tick count exact at a 144 fps render rate", function()
		local fs = FixedStep.new(60)
		local ticks = 0
		for _ = 1, 144 * 10 do
			local _, alpha = fs:advance(1 / 144, function()
				ticks += 1
			end)
			T.truthy(alpha >= 0 and alpha < 1, `alpha {alpha}`)
		end
		T.truthy(ticks == 600 or ticks == 599, `ticks {ticks}`)
	end)
	T.it("drops backlog beyond maxSteps instead of spiralling", function()
		local fs = FixedStep.new(60, 8)
		local steps = fs:advance(1.0, function() end)
		T.eq(steps, 8)
		T.eq(fs.droppedTicks, 52)
		T.truthy(fs.accumulator < fs.dt)
	end)
	T.it("passes the tick number and dt", function()
		local fs = FixedStep.new(30)
		local seen = {}
		fs:advance(0.1, function(dt, tick)
			T.near(dt, 1 / 30, 1e-12)
			table.insert(seen, tick)
		end)
		T.eq(#seen, 3)
		T.eq(seen[3], 3)
		fs:reset()
		T.eq(fs.tick, 0)
	end)
end)

return nil
