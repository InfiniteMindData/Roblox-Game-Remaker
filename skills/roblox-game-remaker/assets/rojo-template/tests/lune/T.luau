--!strict
-- Minimal test helpers for Lune (no dependencies).
local T = {}

local results = { passed = 0, failed = 0, failures = {} :: { string } }
local prefix = ""

function T.describe(name: string, fn: () -> ())
	local previous = prefix
	prefix = if previous == "" then name else `{previous} > {name}`
	fn()
	prefix = previous
end

function T.it(name: string, fn: () -> ())
	local ok, err = pcall(fn)
	if ok then
		results.passed += 1
	else
		results.failed += 1
		table.insert(results.failures, `{prefix} > {name}: {err}`)
	end
end

function T.eq(actual: any, expected: any, message: string?)
	if actual ~= expected then
		error(`{message or "values differ"}: expected {tostring(expected)}, got {tostring(actual)}`, 2)
	end
end

function T.near(actual: number, expected: number, tolerance: number, message: string?)
	if math.abs(actual - expected) > tolerance then
		error(`{message or "not within tolerance"}: expected {expected} ± {tolerance}, got {actual}`, 2)
	end
end

function T.truthy(value: any, message: string?)
	if not value then
		error(message or "expected a truthy value", 2)
	end
end

function T.throws(fn: () -> (), message: string?)
	local ok = pcall(fn)
	if ok then
		error(message or "expected an error", 2)
	end
end

function T.results()
	return results
end

return T
