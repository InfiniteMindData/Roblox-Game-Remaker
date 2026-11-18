--!strict
-- Conservative, action-consistent response gates, not proof of input causality.
local Probe = {}
local ACTIONS: { [string]: string } = {
	Space = "jump",
	ButtonA = "jump",
	W = "forward",
	A = "left",
	S = "back",
	D = "right",
}
function Probe.action(key: string): string?
	return ACTIONS[key]
end
function Probe.ready(stillTime: number, speed: number, moveMagnitude: number, grounded: boolean): boolean
	return stillTime >= 0.15 and speed <= 0.1 and moveMagnitude <= 0.05 and grounded
end
function Probe.responded(
	action: string,
	displacement: number,
	velocity: number,
	verticalVelocity: number,
	jumping: boolean,
	grounded: boolean
): boolean
	if action == "jump" then
		return jumping and verticalVelocity > 0.5
	end
	return grounded and not jumping and displacement > 0.01 and velocity > 0.5
end
return Probe
