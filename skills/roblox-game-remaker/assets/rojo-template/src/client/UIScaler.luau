--!strict
--[[
	UIScaler (client): scale a ScreenGui authored in reference-resolution pixels the way the
	original game scales its UI.

	local stop = UIScaler.attach(screenGui, {
		reference = Vector2.new(1920, 1080), -- resolution of the reference screenshots
		rule = "height",                     -- "height" | "width" | "fit" | "none"
		integer = false,                     -- true for pixel art: whole-number scales only
	})

	Lay out elements with ui_measure.py output (AnchorPoint + scale-anchored offset Position +
	offset Size). The UIScale added here makes that layout match the original at any resolution.
	The ScreenGui's AbsoluteSize is used, so ScreenInsets are respected.
]]

local UIScaler = {}

export type Options = {
	reference: Vector2,
	rule: string?,
	integer: boolean?,
	min: number?,
	max: number?,
}

function UIScaler.computeScale(size: Vector2, reference: Vector2, rule: string?, integer: boolean?): number
	local sx, sy = size.X / reference.X, size.Y / reference.Y
	local r = rule or "height"
	local s = if r == "height" then sy elseif r == "width" then sx elseif r == "fit" then math.min(sx, sy) else 1
	if integer then
		s = math.max(1, math.floor(s + 1e-6))
	end
	return s
end

function UIScaler.attach(screenGui: ScreenGui, options: Options): () -> ()
	assert(options.reference.X > 0 and options.reference.Y > 0, "reference resolution must be positive")
	local scale = screenGui:FindFirstChild("RemakeUIScale")
	if not (scale and scale:IsA("UIScale")) then
		local created = Instance.new("UIScale")
		created.Name = "RemakeUIScale"
		created.Parent = screenGui
		scale = created
	end
	local uiScale = scale :: UIScale
	local function update()
		local size = screenGui.AbsoluteSize
		if size.X <= 0 or size.Y <= 0 then
			return
		end
		local s = UIScaler.computeScale(size, options.reference, options.rule, options.integer)
		if options.min then
			s = math.max(options.min, s)
		end
		if options.max then
			s = math.min(options.max, s)
		end
		uiScale.Scale = s
	end
	local conn = screenGui:GetPropertyChangedSignal("AbsoluteSize"):Connect(update)
	update()
	return function()
		conn:Disconnect()
	end
end

return UIScaler
