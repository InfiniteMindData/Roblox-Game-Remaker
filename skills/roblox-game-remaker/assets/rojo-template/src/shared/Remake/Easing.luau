--!strict
--[[
	Easing: standard (Penner) easing curves named after Enum.EasingStyle, plus cubic-bezier for
	curves that TweenService does not offer (for example CSS-style UI curves measured from footage).

	local f = Easing.get("Quad", "Out")
	local y = f(0.5)
	local css = Easing.cubicBezier(0.25, 0.1, 0.25, 1.0) -- CSS "ease"

	These are the textbook formulas. When exact TweenService equivalence matters, compare a few
	sampled values against TweenService:GetValue() in Studio.
]]

local Easing = {}

export type Curve = (t: number) -> number
type Direction = "In" | "Out" | "InOut"

local PI = math.pi
local C1 = 1.70158
local C2 = C1 * 1.525
local C3 = C1 + 1

local function bounceOut(t: number): number
	local n1, d1 = 7.5625, 2.75
	if t < 1 / d1 then
		return n1 * t * t
	elseif t < 2 / d1 then
		t -= 1.5 / d1
		return n1 * t * t + 0.75
	elseif t < 2.5 / d1 then
		t -= 2.25 / d1
		return n1 * t * t + 0.9375
	end
	t -= 2.625 / d1
	return n1 * t * t + 0.984375
end

-- "In" variants; Out and InOut are derived from them.
local IN: { [string]: Curve } = {
	Linear = function(t)
		return t
	end,
	Sine = function(t)
		return 1 - math.cos(t * PI / 2)
	end,
	Quad = function(t)
		return t * t
	end,
	Cubic = function(t)
		return t * t * t
	end,
	Quart = function(t)
		return t ^ 4
	end,
	Quint = function(t)
		return t ^ 5
	end,
	Exponential = function(t)
		return if t == 0 then 0 else 2 ^ (10 * t - 10)
	end,
	Circular = function(t)
		return 1 - math.sqrt(1 - t * t)
	end,
	Back = function(t)
		return C3 * t * t * t - C1 * t * t
	end,
	Elastic = function(t)
		if t == 0 or t == 1 then
			return t
		end
		return -(2 ^ (10 * t - 10)) * math.sin((t * 10 - 10.75) * (2 * PI) / 3)
	end,
	Bounce = function(t)
		return 1 - bounceOut(1 - t)
	end,
}

function Easing.get(style: string, direction: Direction?): Curve
	local base = IN[style]
	assert(base, `unknown easing style {style}`)
	local dir = direction or "Out"
	if style == "Back" and dir == "InOut" then
		return function(t: number): number
			if t < 0.5 then
				return ((2 * t) ^ 2 * ((C2 + 1) * 2 * t - C2)) / 2
			end
			return ((2 * t - 2) ^ 2 * ((C2 + 1) * (t * 2 - 2) + C2) + 2) / 2
		end
	end
	if dir == "In" then
		return base
	elseif dir == "Out" then
		return function(t: number): number
			return 1 - base(1 - t)
		end
	end
	return function(t: number): number
		if t < 0.5 then
			return base(2 * t) / 2
		end
		return 1 - base(2 - 2 * t) / 2
	end
end

-- CSS-style cubic-bezier(x1, y1, x2, y2) easing, solved per call with Newton steps plus bisection.
function Easing.cubicBezier(x1: number, y1: number, x2: number, y2: number): Curve
	assert(x1 >= 0 and x1 <= 1 and x2 >= 0 and x2 <= 1, "bezier x control points must be within [0, 1]")
	local function sample(a1: number, a2: number, s: number): number
		local u = 1 - s
		return 3 * u * u * s * a1 + 3 * u * s * s * a2 + s * s * s
	end
	local function slope(a1: number, a2: number, s: number): number
		local u = 1 - s
		return 3 * u * u * a1 + 6 * u * s * (a2 - a1) + 3 * s * s * (1 - a2)
	end
	return function(x: number): number
		if x <= 0 then
			return 0
		elseif x >= 1 then
			return 1
		end
		local s = x
		for _ = 1, 8 do
			local err = sample(x1, x2, s) - x
			if math.abs(err) < 1e-7 then
				return sample(y1, y2, s)
			end
			local d = slope(x1, x2, s)
			if math.abs(d) < 1e-6 then
				break
			end
			s -= err / d
		end
		local lo, hi = 0, 1
		s = x
		for _ = 1, 40 do
			local v = sample(x1, x2, s)
			if math.abs(v - x) < 1e-7 then
				break
			end
			if v < x then
				lo = s
			else
				hi = s
			end
			s = (lo + hi) / 2
		end
		return sample(y1, y2, s)
	end
end

-- Interpolate a number with a curve: Easing.lerp(a, b, t, curve)
function Easing.lerp(a: number, b: number, t: number, curve: Curve?): number
	local k = if curve then curve(math.clamp(t, 0, 1)) else math.clamp(t, 0, 1)
	return a + (b - a) * k
end

return Easing
