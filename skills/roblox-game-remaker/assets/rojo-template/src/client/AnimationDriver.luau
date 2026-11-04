--!strict
--[[
	AnimationDriver (client): plays measured clips with measured fades and cadence matching.

	Locomotion (only when Config.Animation.UseDefaultAnimate = false):
	  Idle / Walk / Run from planar speed, Jump on takeoff, Fall while airborne, Land on landing.
	  Walk and Run play at AdjustSpeed(speed / AuthoredSpeed), which removes foot sliding when the
	  remake's speeds differ from the speed a clip was authored for.
	Actions (always available): handle.playAction("Attack1") with priorities and fades from Config.
	Markers: handle.onMarker("Attack1", "Hit", fn) wraps AnimationTrack:GetMarkerReachedSignal.

	With UseDefaultAnimate = true the Roblox Animate script keeps running (replace its IDs on the
	server as shown in the creator docs) and only actions are driven here.
]]

local Players = game:GetService("Players")
local RunService = game:GetService("RunService")

local AnimationDriver = {}

export type ClipSpec = {
	Id: string,
	Priority: string?,
	FadeIn: number?,
	FadeOut: number?,
	Looped: boolean?,
	AuthoredSpeed: number?,
	Weight: number?,
}

export type Handle = {
	playAction: (name: string, fadeTime: number?, weight: number?, speed: number?) -> AnimationTrack?,
	stopAction: (name: string, fadeTime: number?) -> (),
	onMarker: (clip: string, marker: string, fn: (param: string) -> ()) -> RBXScriptConnection?,
	getTrack: (name: string) -> AnimationTrack?,
	stop: () -> (),
}

local LOCOMOTION = { Idle = true, Walk = true, Run = true, Jump = true, Fall = true, Land = true }

function AnimationDriver.start(cfg: { [string]: any }): Handle
	local player = Players.LocalPlayer
	local clips: { [string]: ClipSpec } = cfg.Clips or {}
	local tracks: { [string]: AnimationTrack } = {}
	local charConns: { RBXScriptConnection } = {}
	local current: string? = nil
	local bindName = "RemakeAnimationDriver"

	local function clearCharacter()
		pcall(function()
			RunService:UnbindFromRenderStep(bindName)
		end)
		for _, c in charConns do
			c:Disconnect()
		end
		table.clear(charConns)
		for _, track in tracks do
			track:Stop(0)
		end
		table.clear(tracks)
		current = nil
	end

	local function play(name: string)
		if current == name then
			return
		end
		local spec = clips[name]
		local track = tracks[name]
		if not (spec and track) then
			return
		end
		local fade = spec.FadeIn or 0.1
		if current and tracks[current] then
			tracks[current]:Stop(fade)
		end
		track:Play(fade, spec.Weight or 1, 1)
		current = name
	end

	local function bind(character: Model)
		if player.Character ~= character then
			return
		end
		clearCharacter()
		local humanoid = character:WaitForChild("Humanoid", 10)
		local root = character:WaitForChild("HumanoidRootPart", 10)
		if not (humanoid and humanoid:IsA("Humanoid") and root and root:IsA("BasePart")) then
			return
		end
		local animator = humanoid:FindFirstChildOfClass("Animator") or humanoid:WaitForChild("Animator", 10)
		if not (animator and animator:IsA("Animator")) or player.Character ~= character then
			return
		end
		for name, spec in clips do
			if spec.Id and spec.Id ~= "" and spec.Id ~= "rbxassetid://0" then
				local animation = Instance.new("Animation")
				animation.AnimationId = spec.Id
				local ok, track = pcall(function()
					return animator:LoadAnimation(animation)
				end)
				if ok and track then
					track.Priority = (Enum.AnimationPriority :: any)[spec.Priority or "Action"]
					track.Looped = spec.Looped == true
					tracks[name] = track
				else
					warn(`AnimationDriver: could not load {name} ({spec.Id}): {track}`)
				end
			end
		end

		if cfg.UseDefaultAnimate ~= false then
			return
		end
		local animate = character:FindFirstChild("Animate")
		if animate and animate:IsA("LocalScript") then
			animate.Enabled = false
			for _, t in animator:GetPlayingAnimationTracks() do
				if not tracks[t.Name] then
					t:Stop(0)
				end
			end
		end

		table.insert(
			charConns,
			humanoid.StateChanged:Connect(function(_, new)
				if new == Enum.HumanoidStateType.Jumping then
					play("Jump")
				elseif new == Enum.HumanoidStateType.Freefall then
					if current ~= "Jump" or not (tracks.Jump and tracks.Jump.IsPlaying) then
						play("Fall")
					end
				elseif new == Enum.HumanoidStateType.Landed then
					local land = tracks.Land
					if land then
						land:Play((clips.Land :: ClipSpec).FadeIn or 0.05)
					end
				end
			end)
		)

		local runThreshold = cfg.RunThreshold or 20
		RunService:BindToRenderStep(bindName, Enum.RenderPriority.Character.Value, function()
			local state = humanoid:GetState()
			if state == Enum.HumanoidStateType.Freefall then
				if current == "Jump" and tracks.Jump and not tracks.Jump.IsPlaying then
					play("Fall")
				end
				return
			elseif state == Enum.HumanoidStateType.Jumping then
				return
			end
			local v = root.AssemblyLinearVelocity
			local speed = Vector3.new(v.X, 0, v.Z).Magnitude
			local name = if speed < 0.1 then "Idle" elseif speed < runThreshold or not tracks.Run then "Walk" else "Run"
			play(name)
			local spec = clips[name]
			local track = tracks[name]
			if track and spec and spec.AuthoredSpeed and spec.AuthoredSpeed > 0 then
				track:AdjustSpeed(math.max(speed, 0.01) / spec.AuthoredSpeed)
			end
		end)
	end

	local added = player.CharacterAdded:Connect(bind)
	local removing = player.CharacterRemoving:Connect(clearCharacter)
	if player.Character then
		task.spawn(bind, player.Character)
	end

	return {
		playAction = function(name: string, fadeTime: number?, weight: number?, speed: number?): AnimationTrack?
			local spec = clips[name]
			local track = tracks[name]
			if not (spec and track) then
				warn(`AnimationDriver: no loaded clip {name}`)
				return nil
			end
			if LOCOMOTION[name] then
				warn(`AnimationDriver: {name} is a locomotion clip; it is driven automatically`)
			end
			track:Play(fadeTime or spec.FadeIn or 0.1, weight or spec.Weight or 1, speed or 1)
			return track
		end,
		stopAction = function(name: string, fadeTime: number?)
			local track = tracks[name]
			if track then
				track:Stop(fadeTime or (clips[name] and clips[name].FadeOut) or 0.1)
			end
		end,
		onMarker = function(clip: string, marker: string, fn: (param: string) -> ()): RBXScriptConnection?
			local track = tracks[clip]
			if not track then
				return nil
			end
			local conn = track:GetMarkerReachedSignal(marker):Connect(fn)
			table.insert(charConns, conn)
			return conn
		end,
		getTrack = function(name: string): AnimationTrack?
			return tracks[name]
		end,
		stop = function()
			added:Disconnect()
			removing:Disconnect()
			clearCharacter()
		end,
	}
end

return AnimationDriver
