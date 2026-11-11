--!strict
--[[
	SimRecorder: measurement log for games whose motion comes from their own simulation instead of a
	Humanoid (fighting games, custom character controllers, vehicles, deterministic fixed-tick sims).
	MeasurementHarness only follows the local player's Humanoid; this module is called from the game's
	simulation step, on the client or the server, and writes the same REMAKE_MEASURE lines that
	measure_compare.py and clip_compare.py read.

	local rec = SimRecorder.new({ id = "p1", hz = 60, grounded = { "idle", "walkF", "walkB", "crouch" } })
	-- inside the fixed-tick step, after the state is advanced:
	rec:sample(state.tick, f.x, f.y, 0, f.vx, f.vy, 0, f.st, inputMagnitude)
	if f.st == "attack" and f.sf == 0 then rec:event(state.tick, "attack") end
	-- when the round or the test ends:
	rec:flush()

	Times are tick / hz, so frame counts are exact. Output lines:
	  REMAKE_MEASURE {"k":"sim","id":"p1","hz":60,"grounded":["idle","walkF"]}
	  REMAKE_MEASURE {"k":"b","id":"p1","s":[[t,x,y,z,vx,vy,vz,state,mv], ...]}
	  REMAKE_MEASURE {"k":"e","id":"p1","t":1.25,"n":"attack"}
	Then:
	  python scripts/measure_compare.py run.log --subject p1 --interval startup=attack..active

	Options:
	  id        subject name; one recorder per fighter or body (required)
	  hz        simulation tick rate (required)
	  grounded  states that count as standing on the ground (for ground_speed, accel and jumps)
	  scale     multiply positions and velocities (sim units -> studs); default 1
	  velocityPerTick  true when the sim stores velocity per tick; it is converted to per second
	  batch     samples per printed line; default 30
	  enabled   default: Studio and Workspace attribute RemakeMeasure = true (no output otherwise)
	  emit, encode  output sink and JSON encoder; default print and HttpService:JSONEncode
	A disabled recorder accepts every call and prints nothing, so game code needs no branches.
]]

local SimRecorder = {}
SimRecorder.__index = SimRecorder

local TAG = "REMAKE_MEASURE"

export type Options = {
	id: string,
	hz: number,
	grounded: { string }?,
	scale: number?,
	velocityPerTick: boolean?,
	batch: number?,
	enabled: boolean?,
	emit: ((string) -> ())?,
	encode: ((any) -> string)?,
}

export type SimRecorder = {
	id: string,
	hz: number,
	enabled: boolean,
	scale: number,
	velScale: number,
	batchSize: number,
	batch: { { any } },
	emit: (string) -> (),
	encode: (any) -> string,
	lastTick: number?,
	sample: (
		self: SimRecorder,
		tick: number,
		x: number,
		y: number,
		z: number?,
		vx: number?,
		vy: number?,
		vz: number?,
		state: string?,
		input: number?
	) -> (),
	event: (self: SimRecorder, tick: number, name: string) -> (),
	flush: (self: SimRecorder) -> (),
	_line: (self: SimRecorder, obj: { [string]: any }) -> (),
}

local function round(v: number, digits: number): number
	local m = 10 ^ digits
	return math.round(v * m) / m
end

local function defaultEnabled(): boolean
	local RunService = game:GetService("RunService")
	return RunService:IsStudio() and game:GetService("Workspace"):GetAttribute("RemakeMeasure") == true
end

function SimRecorder.new(opts: Options): SimRecorder
	assert(type(opts.id) == "string" and opts.id ~= "", "SimRecorder.new: id is required")
	assert(type(opts.hz) == "number" and opts.hz > 0, "SimRecorder.new: hz must be a positive tick rate")
	local enabled = if opts.enabled ~= nil then opts.enabled else defaultEnabled()
	local encode = opts.encode
	if encode == nil then
		local HttpService = game:GetService("HttpService")
		encode = function(value: any): string
			return HttpService:JSONEncode(value)
		end
	end
	local scale = opts.scale or 1
	local self = (setmetatable({
		id = opts.id,
		hz = opts.hz,
		enabled = enabled,
		scale = scale,
		velScale = scale * (if opts.velocityPerTick then opts.hz else 1),
		batchSize = math.max(1, opts.batch or 30),
		batch = {},
		emit = opts.emit or print,
		encode = encode :: (any) -> string,
		lastTick = nil,
	}, SimRecorder) :: any) :: SimRecorder
	if enabled then
		self:_line({ k = "sim", id = opts.id, hz = opts.hz, grounded = opts.grounded or {} })
	end
	return self
end

function SimRecorder._line(self: SimRecorder, obj: { [string]: any })
	self.emit(`{TAG} {self.encode(obj)}`)
end

-- One row per simulation tick. z, velocities, state and input default to 0, 0, "" and 0.
function SimRecorder.sample(
	self: SimRecorder,
	tick: number,
	x: number,
	y: number,
	z: number?,
	vx: number?,
	vy: number?,
	vz: number?,
	state: string?,
	input: number?
)
	if not self.enabled or tick == self.lastTick then
		return
	end
	self.lastTick = tick
	local s, v = self.scale, self.velScale
	table.insert(self.batch, {
		round(tick / self.hz, 5),
		round(x * s, 4),
		round(y * s, 4),
		round((z or 0) * s, 4),
		round((vx or 0) * v, 4),
		round((vy or 0) * v, 4),
		round((vz or 0) * v, 4),
		state or "",
		round(input or 0, 3),
	})
	if #self.batch >= self.batchSize then
		self:flush()
	end
end

-- A named moment (attack, active, hit, jump, land, move_start, move_stop) at a simulation tick.
function SimRecorder.event(self: SimRecorder, tick: number, name: string)
	if not self.enabled then
		return
	end
	self:flush() -- keep samples and events in order in the Output
	self:_line({ k = "e", id = self.id, t = round(tick / self.hz, 5), n = name })
end

function SimRecorder.flush(self: SimRecorder)
	if not self.enabled or #self.batch == 0 then
		return
	end
	self:_line({ k = "b", id = self.id, s = self.batch })
	self.batch = {}
end

return SimRecorder
