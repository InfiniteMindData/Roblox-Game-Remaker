--!strict
--[[
	LightingPreset: apply a measured lighting and post-processing preset from one table.

	LightingPreset.apply(Config.Lighting)

	Creates or updates effect instances under Lighting named Remake_<Class>, so applying twice is
	harmless. Keys that are nil are left unchanged. Run on the server (Bootstrap) so every client
	sees the same lighting; ShotCamera may also call it on the client for comparison shots.
	Lighting.Technology is deprecated: use LightingStyle and PrioritizeLightingQuality.
]]

local Lighting = game:GetService("Lighting")

local LightingPreset = {}

local SCALAR_KEYS = {
	"PrioritizeLightingQuality",
	"ClockTime",
	"GeographicLatitude",
	"Brightness",
	"ExposureCompensation",
	"Ambient",
	"OutdoorAmbient",
	"EnvironmentDiffuseScale",
	"EnvironmentSpecularScale",
	"ShadowSoftness",
	"GlobalShadows",
	"FogStart",
	"FogEnd",
	"FogColor",
}

local EFFECTS: { [string]: string } = {
	Atmosphere = "Atmosphere",
	ColorCorrection = "ColorCorrectionEffect",
	Bloom = "BloomEffect",
	ColorGrading = "ColorGradingEffect",
	DepthOfField = "DepthOfFieldEffect",
	SunRays = "SunRaysEffect",
}

local function setProperty(target: Instance, key: string, value: any)
	local ok, err = pcall(function()
		(target :: any)[key] = value
	end)
	if not ok then
		warn(`LightingPreset: could not set {target.ClassName}.{key}: {err}`)
	end
end

local function toEnum(enumType: any, value: any): any
	if typeof(value) == "string" then
		return enumType[value]
	end
	return value
end

function LightingPreset.apply(preset: { [string]: any })
	if preset.LightingStyle ~= nil then
		setProperty(Lighting, "LightingStyle", toEnum(Enum.LightingStyle, preset.LightingStyle))
	end
	for _, key in SCALAR_KEYS do
		if preset[key] ~= nil then
			setProperty(Lighting, key, preset[key])
		end
	end
	for key, className in EFFECTS do
		local props = preset[key]
		if props == nil then
			continue
		end
		local name = `Remake_{className}`
		local effect = Lighting:FindFirstChild(name)
		if effect == nil then
			effect = Instance.new(className)
			effect.Name = name
		end
		local inst = effect :: Instance
		for prop, value in props :: { [string]: any } do
			if prop == "TonemapperPreset" then
				value = toEnum(Enum.TonemapperPreset, value)
			end
			setProperty(inst, prop, value)
		end
		inst.Parent = Lighting
	end
end

-- Remove every effect this module created.
function LightingPreset.clear()
	for _, child in Lighting:GetChildren() do
		if string.sub(child.Name, 1, 7) == "Remake_" then
			child:Destroy()
		end
	end
end

return LightingPreset
