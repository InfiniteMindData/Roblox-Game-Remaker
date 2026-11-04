--!strict
-- Run from the template root:  lune run tests/lune/run.luau
local process = require("@lune/process")
local T = require("./T")

local specs = {
	"./Units.spec",
	"./Spring.spec",
	"./FixedStep.spec",
	"./StateMachine.spec",
	"./MovementMath.spec",
	"./Easing.spec",
	"./UIScaler.spec",
}

for _, spec in specs do
	local ok, err = pcall(require, spec)
	if not ok then
		print(`LOAD ERROR {spec}: {err}`)
		process.exit(1)
	end
end

local r = T.results()
for _, failure in r.failures do
	print(`FAIL {failure}`)
end
print(`{r.passed} passed, {r.failed} failed`)
process.exit(if r.failed == 0 then 0 else 1)
