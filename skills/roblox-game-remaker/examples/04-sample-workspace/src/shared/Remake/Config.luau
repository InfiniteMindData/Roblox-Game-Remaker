--!strict
--[[
	Sample Config for the fictional "Lantern Hop" workspace (examples/04-sample-workspace).
	Values come from remake/measurements.json and remake/evidence.json; check with
	  python scripts/config_check.py examples/04-sample-workspace/remake

	Config: the single source of every measured constant in the remake.

	Rules:
	  * Every value carries the evidence or measurement ID it came from (Config.Evidence below
	    and a trailing comment). Values without evidence are ASSUMED: list them in the breakdown.
	  * Change a value here and in remake/measurements.json together, then re-run
	    measure_compare.py / visual_compare.py.
	  * The defaults below are Roblox defaults (creator docs), so an untouched template behaves like
	    a stock Roblox place. Replace them with the reference game's measurements.
]]

local Config = {}

Config.Meta = {
	Game = "Lantern Hop (fictional sample)", -- EV-001
	Version = "1.4.2",
	RightsMode = "own-ip", -- EV-001
}

Config.World = {
	StudsPerMeter = 5.0 / 1.4, -- character-relative: hero 1.4 m (EV-002) = 5.0 studs
	Gravity = 100, -- rise gravity from MS-001/MS-002 via remake_calc.py jump
}

Config.Movement = {
	WalkSpeed = 20, -- MS-004 (19.996 ± 0.1)
	AccelerationTime = 0.25, -- MS-005 (linear model preferred)
	DecelerationTime = 0, -- s to stop from WalkSpeed; 0 = instant
	AirControl = 1, -- multiplier on ramp rates while airborne (0..1)
	JumpApex = 8.0, -- MS-001
	FallGravityMultiplier = 2.0, -- from MS-002/MS-003 via remake_calc.py jump
	ReleaseGravityMultiplier = 1, -- extra gravity after early jump release (variable jump height)
	MaxFallSpeed = 0, -- studs/s; 0 = no cap
	CoyoteTime = 0.1, -- EV-002 (design doc: 6 frames)
	JumpBuffer = 0.067, -- EV-002 (design doc: 4 frames)
	AirJumps = 0, -- extra jumps in the air
	AirJumpApex = 0, -- studs for each air jump; 0 = same as JumpApex
	TurnSpeedDegrees = 0, -- deg/s facing turn rate; 0 = Humanoid AutoRotate (instant)
	MaxSlopeAngle = 89, -- degrees (Roblox default)
}

Config.Camera = {
	Mode = "Follow", -- CAM-002
	FieldOfView = 58.7155, -- EV-002: 90 deg horizontal at 16:9, converted with remake_calc.py fov
	MinZoom = 0.5, -- Default mode zoom limits (studs)
	MaxZoom = 128,
	HumanoidCameraOffset = Vector3.zero, -- Default mode: Humanoid.CameraOffset
	-- Follow mode
	PivotOffset = Vector3.new(0, 2, 0), -- look-at point relative to the root (world up)
	ShoulderOffset = Vector3.new(0, 0, 0), -- camera-space offset (x = right, y = up)
	Distance = 12, -- studs from pivot
	PitchMinDeg = -70,
	PitchMaxDeg = 60,
	StartPitchDeg = -15,
	MouseSensitivity = 0.25, -- deg per pixel
	GamepadSpeedDeg = 220, -- deg/s at full stick
	TouchSensitivity = 0.3, -- deg per pixel
	FollowFrequency = 16.67, -- rad/s (remake_calc.py spring)
	FollowDamping = 1.0,
	CollisionRadius = 0.5,
	LockMouse = true, -- lock the cursor to the center while in Follow mode (like shift lock)
	-- Fixed mode
	FixedShot = { Position = Vector3.new(0, 20, 40), LookAt = Vector3.zero },
	ForceInVR = false, -- true: use Follow/Fixed/Orthographic even for VR players (comfort risk)
	-- Orthographic mode
	OrthographicSize = 60, -- studs spanned by the controlled axis
	OrthographicAxis = "Vertical", -- Enum.OrthographicMode name
	OrthographicPitchDeg = -35.264, -- true isometric pitch
	OrthographicYawDeg = 45,
}

Config.Animation = {
	-- Clips for AnimationDriver (custom rigs). Ids are placeholders until published.
	UseDefaultAnimate = true, -- true: keep Roblox's Animate script (replace its IDs on the server instead)
	Clips = {
		Idle = { Id = "rbxassetid://0", Priority = "Idle", FadeIn = 0.2, Looped = true },
		Walk = { Id = "rbxassetid://0", Priority = "Movement", FadeIn = 0.15, Looped = true, AuthoredSpeed = 16 },
		Run = { Id = "rbxassetid://0", Priority = "Movement", FadeIn = 0.15, Looped = true, AuthoredSpeed = 24 },
		Jump = { Id = "rbxassetid://0", Priority = "Movement", FadeIn = 0.05, Looped = false },
		Fall = { Id = "rbxassetid://0", Priority = "Movement", FadeIn = 0.2, Looped = true },
		Land = { Id = "rbxassetid://0", Priority = "Action", FadeIn = 0.03, Looped = false },
	},
	RunThreshold = 20, -- studs/s above which Run plays instead of Walk
}

-- Applied by LightingPreset on the server. Empty by default so the place's own lighting is kept;
-- fill it from matched-shot comparisons (graphics-lighting.md). Keys that are absent stay unchanged.
Config.Lighting = {
	-- LightingStyle = "Realistic", -- "Realistic" | "Soft" (Lighting.Technology is deprecated)
	-- PrioritizeLightingQuality = true,
	-- ClockTime = 14.5,
	-- GeographicLatitude = 41.7,
	-- Brightness = 2,
	-- ExposureCompensation = 0,
	-- Ambient = Color3.fromRGB(70, 70, 70),
	-- OutdoorAmbient = Color3.fromRGB(128, 128, 128),
	-- EnvironmentDiffuseScale = 1,
	-- EnvironmentSpecularScale = 1,
	-- ShadowSoftness = 0.2,
	-- Atmosphere = { Density = 0.3, Offset = 0.25, Color = Color3.fromRGB(199, 199, 199), Decay = Color3.fromRGB(106, 112, 125), Glare = 0, Haze = 0 },
	-- ColorCorrection = { Brightness = 0, Contrast = 0, Saturation = 0, TintColor = Color3.new(1, 1, 1) },
	-- Bloom = { Intensity = 1, Size = 24, Threshold = 2 },
	-- ColorGrading = { TonemapperPreset = "Default" }, -- "Default" | "Retro"
	-- DepthOfField = { FarIntensity = 0.1, FocusDistance = 50, InFocusRadius = 30, NearIntensity = 0.75 },
	-- SunRays = { Intensity = 0.1, Spread = 1 },
} :: { [string]: any }

Config.UI = {
	ReferenceResolution = Vector2.new(1920, 1080), -- resolution of the reference screenshots
	ScaleRule = "height", -- "height" | "width" | "fit" | "none" (how the original scales its UI)
}

Config.Haptics = {
	AllowLegacyMotorFallback = false, -- use deprecated HapticService only if HapticEffect is unavailable
	SidePositions = { -- calibrate on a Quest with DevTools/InputProbe; see vr-quest.md
		Left = Vector3.new(-1, 0, 0),
		Right = Vector3.new(1, 0, 0),
	},
	Presets = {
		UIClick = { Type = "UIClick" },
		Hit = { Type = "GameplayCollision" },
		Explosion = { Type = "GameplayExplosion" },
		-- Custom waveform: Keys = { {timeMs, intensity0to1}, ... }
		Heartbeat = { Type = "Custom", Keys = { { 0, 0 }, { 30, 0.8 }, { 90, 0 }, { 160, 0.5 }, { 220, 0 } } },
	},
}

Config.VR = {
	Enabled = true, -- support VR players when VRService.VREnabled
	AvatarGestures = true, -- server-side VRService.AvatarGestures
	HandModels = false, -- weld simple hand parts to tracked controllers (client, cosmetic)
	SnapTurnDegrees = 0, -- 0 = leave turning to Roblox's default VR controls
}

Config.DevTools = {
	Measure = false, -- MeasurementHarness logging (Studio only); also enabled by Workspace attribute RemakeMeasure
	MeasureBatch = 30, -- samples per log line
	InputProbe = false, -- InputProbe logging (Studio, or a private test place on device)
	ShotHotkeys = true, -- ShotCamera F-key cycling in Studio
}

-- Key path -> evidence/measurement IDs. Fill as values are measured; reviewers audit from here.
Config.Evidence = {
	["Meta.Game"] = "EV-001",
	["Meta.RightsMode"] = "EV-001",
	["World.StudsPerMeter"] = "derived: EV-002 (hero height 1.4 m = 5.0 studs)",
	["World.Gravity"] = "derived: MS-001, MS-002 (remake_calc.py jump)",
	["Movement.WalkSpeed"] = "MS-004",
	["Movement.AccelerationTime"] = "MS-005",
	["Movement.JumpApex"] = "MS-001",
	["Movement.FallGravityMultiplier"] = "derived: MS-002, MS-003 (remake_calc.py jump)",
	["Movement.CoyoteTime"] = "EV-002",
	["Movement.JumpBuffer"] = "EV-002",
	["Camera.Mode"] = "EV-004 (observed follow camera)",
	["Camera.FieldOfView"] = "derived: EV-002 (90 deg horizontal at 16:9)",
} :: { [string]: string }

return Config
