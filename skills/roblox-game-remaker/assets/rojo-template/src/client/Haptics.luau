--!strict
--[[
	Haptics (client): HapticEffect presets and custom waveforms from Config.Haptics.

	Haptics.play("Hit")                       -- preset Type = GameplayCollision
	Haptics.play("Heartbeat", { side = "Left" }) -- custom waveform, aimed at the left controller
	Haptics.stop("Heartbeat")

	HapticEffect supports Quest Touch controllers, Xbox and PlayStation gamepads, and supported
	phones (creator docs). HapticService is deprecated; it is used only when HapticEffect cannot be
	created and Config.Haptics.AllowLegacyMotorFallback is true.
	The Position mapping for left/right Quest controllers is not stated in the docs: calibrate
	Config.Haptics.SidePositions on a device (vr-quest.md).
]]

local HapticService = game:GetService("HapticService") -- api-check: allow-deprecated (opt-in legacy fallback only)
local Workspace = game:GetService("Workspace")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared"):WaitForChild("Remake")
local Config = require(Shared:WaitForChild("Config"))

local Haptics = {}

export type PlayOptions = { side: string?, radius: number?, looped: boolean? }

local folder: Folder? = nil
local cache: { [string]: HapticEffect } = {}

local function container(): Folder
	if folder and folder.Parent then
		return folder
	end
	local f = Instance.new("Folder")
	f.Name = "RemakeHaptics"
	f.Parent = Workspace
	folder = f
	return f
end

local function legacyPulse(side: string?, intensity: number, duration: number)
	if not Config.Haptics.AllowLegacyMotorFallback then
		return
	end
	local motor = if side == "Left"
		then Enum.VibrationMotor.LeftHand
		elseif side == "Right" then Enum.VibrationMotor.RightHand
		else Enum.VibrationMotor.Large
	local input = Enum.UserInputType.Gamepad1
	if HapticService:IsVibrationSupported(input) and HapticService:IsMotorSupported(input, motor) then
		HapticService:SetMotor(input, motor, intensity)
		task.delay(duration, function()
			HapticService:SetMotor(input, motor, 0)
		end)
	end
end

function Haptics.play(name: string, options: PlayOptions?): HapticEffect?
	local preset = Config.Haptics.Presets[name]
	if not preset then
		warn(`Haptics: unknown preset {name}`)
		return nil
	end
	local opts: PlayOptions = options or {}
	local key = `{name}:{opts.side or "both"}`
	local effect = cache[key]
	if not effect or not effect.Parent then
		local ok, created = pcall(Instance.new, "HapticEffect")
		if not ok then
			legacyPulse(opts.side, 1, 0.15)
			return nil
		end
		local e = created :: HapticEffect
		e.Name = key
		e.Type = (Enum.HapticEffectType :: any)[preset.Type]
		if preset.Type == "Custom" and preset.Keys then
			local keys = {}
			for _, k in preset.Keys do
				table.insert(keys, FloatCurveKey.new(k[1], k[2], Enum.KeyInterpolationMode.Linear))
			end
			e:SetWaveformKeys(keys)
		end
		if opts.side then
			local pos = Config.Haptics.SidePositions[opts.side]
			if pos then
				e.Position = pos
				e.Radius = opts.radius or 0.5
			end
		end
		e.Parent = container()
		cache[key] = e
		effect = e
	end
	local e = effect :: HapticEffect
	e.Looped = opts.looped == true
	e:Play()
	return e
end

function Haptics.stop(name: string)
	for key, effect in cache do
		if string.sub(key, 1, #name + 1) == name .. ":" then
			effect:Stop()
		end
	end
end

function Haptics.clear()
	for _, effect in cache do
		effect:Destroy()
	end
	table.clear(cache)
end

return Haptics
