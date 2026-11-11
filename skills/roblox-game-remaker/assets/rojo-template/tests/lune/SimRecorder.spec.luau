local serde = require("@lune/serde")
local T = require("./T")
local SimRecorder = require("../../src/shared/Remake/SimRecorder")

local function encode(value: any): string
	return serde.encode("json", value)
end

local function recorder(extra: { [string]: any }?)
	local lines: { string } = {}
	local opts: { [string]: any } = {
		id = "p1",
		hz = 60,
		grounded = { "idle", "walkF" },
		enabled = true,
		batch = 4,
		encode = encode,
		emit = function(line: string)
			table.insert(lines, line)
		end,
	}
	for k, v in extra or {} do
		opts[k] = v
	end
	return SimRecorder.new(opts :: any), lines
end

local function decode(line: string): { [string]: any }
	local tag = "REMAKE_MEASURE "
	T.eq(string.sub(line, 1, #tag), tag, "line tag")
	return serde.decode("json", string.sub(line, #tag + 1))
end

T.describe("SimRecorder", function()
	T.it("writes a simulation header with the tick rate and grounded states", function()
		local _, lines = recorder()
		local head = decode(lines[1])
		T.eq(head.k, "sim")
		T.eq(head.id, "p1")
		T.eq(head.hz, 60)
		T.eq(head.grounded[2], "walkF")
	end)
	T.it("batches samples with tick / hz times and string states", function()
		local rec, lines = recorder()
		for tick = 0, 3 do
			rec:sample(tick, tick * 0.5, 0, nil, 30, 0, nil, "walkF", 1)
		end
		T.eq(#lines, 2, "header + one full batch")
		local b = decode(lines[2])
		T.eq(b.k, "b")
		T.eq(b.id, "p1")
		T.eq(#b.s, 4)
		T.near(b.s[4][1], 3 / 60, 1e-5, "time of tick 3")
		T.eq(b.s[4][8], "walkF")
		T.eq(b.s[4][9], 1)
	end)
	T.it("flushes pending samples before an event so the order is kept", function()
		local rec, lines = recorder()
		rec:sample(10, 0, 0)
		rec:event(11, "attack")
		T.eq(decode(lines[2]).k, "b")
		local e = decode(lines[3])
		T.eq(e.k, "e")
		T.eq(e.n, "attack")
		T.near(e.t, 11 / 60, 1e-5)
	end)
	T.it("ignores a repeated tick (render-rate callers)", function()
		local rec, lines = recorder()
		rec:sample(5, 1, 0)
		rec:sample(5, 2, 0)
		rec:flush()
		T.eq(#decode(lines[2]).s, 1)
	end)
	T.it("converts per-tick velocity and scales units", function()
		local rec, lines = recorder({ scale = 2, velocityPerTick = true })
		rec:sample(0, 1, 0, 0, 0.1, 0, 0)
		rec:flush()
		local row = decode(lines[2]).s[1]
		T.eq(row[2], 2, "x scaled")
		T.near(row[5], 0.1 * 60 * 2, 1e-4, "vx per second, scaled")
	end)
	T.it("prints nothing when disabled", function()
		local rec, lines = recorder({ enabled = false })
		rec:sample(0, 0, 0)
		rec:event(1, "attack")
		rec:flush()
		T.eq(#lines, 0)
	end)
end)
