local roblox = require("@lune/roblox")
local T = require("./T")
local UIScaler = require("../../src/client/UIScaler")

local Vector2 = roblox.Vector2
local REF = Vector2.new(1920, 1080)

T.describe("UIScaler.computeScale", function()
	T.it("height rule follows screen height", function()
		T.near(UIScaler.computeScale(Vector2.new(2560, 1440), REF, "height"), 1440 / 1080, 1e-12)
		T.near(UIScaler.computeScale(Vector2.new(3440, 1440), REF, "height"), 1440 / 1080, 1e-12)
	end)
	T.it("width rule follows screen width", function()
		T.near(UIScaler.computeScale(Vector2.new(1280, 1024), REF, "width"), 1280 / 1920, 1e-12)
	end)
	T.it("fit uses the smaller ratio", function()
		T.near(UIScaler.computeScale(Vector2.new(1280, 1024), REF, "fit"), 1280 / 1920, 1e-12)
		T.near(UIScaler.computeScale(Vector2.new(3840, 1080), REF, "fit"), 1, 1e-12)
	end)
	T.it("none keeps 1 and integer floors", function()
		T.eq(UIScaler.computeScale(Vector2.new(800, 600), REF, "none"), 1)
		T.eq(UIScaler.computeScale(Vector2.new(3000, 2000), Vector2.new(320, 180), "height", true), 11)
		T.eq(UIScaler.computeScale(Vector2.new(200, 100), Vector2.new(320, 180), "height", true), 1)
	end)
end)

return nil
