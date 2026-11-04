local T = require("./T")
local Easing = require("../../src/shared/Remake/Easing")

local STYLES =
	{ "Linear", "Sine", "Quad", "Cubic", "Quart", "Quint", "Exponential", "Circular", "Back", "Elastic", "Bounce" }

T.describe("Easing", function()
	T.it("every style starts at 0 and ends at 1", function()
		for _, style in STYLES do
			for _, dir in { "In", "Out", "InOut" } do
				local f = Easing.get(style, dir :: any)
				T.near(f(0), 0, 1e-9, `{style} {dir} at 0`)
				T.near(f(1), 1, 1e-9, `{style} {dir} at 1`)
			end
		end
	end)
	T.it("known midpoints", function()
		T.near(Easing.get("Quad", "Out")(0.5), 0.75, 1e-12)
		T.near(Easing.get("Quad", "In")(0.5), 0.25, 1e-12)
		T.near(Easing.get("Sine", "InOut")(0.5), 0.5, 1e-12)
		T.near(Easing.get("Linear", "Out")(0.3), 0.3, 1e-12)
	end)
	T.it("cubic-bezier matches CSS ease and linear", function()
		local linear = Easing.cubicBezier(0, 0, 1, 1)
		T.near(linear(0.37), 0.37, 1e-6)
		local ease = Easing.cubicBezier(0.25, 0.1, 0.25, 1)
		T.near(ease(0.5), 0.8024034, 1e-5)
		T.eq(ease(0), 0)
		T.eq(ease(1), 1)
	end)
	T.it("lerp applies a curve", function()
		T.near(Easing.lerp(10, 20, 0.5, Easing.get("Quad", "Out")), 17.5, 1e-12)
		T.near(Easing.lerp(10, 20, 2), 20, 1e-12)
	end)
	T.it("rejects unknown styles", function()
		T.throws(function()
			Easing.get("Wobble")
		end)
	end)
end)

return nil
