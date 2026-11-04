--!strict
--[[
	InputProbe (client): log every input with its KeyCode, UserInputType and analog Position,
	plus VR tracking availability. Use it to verify controller mappings (for example Meta Quest 3
	Touch controllers) before writing CTRL / VR breakdown entries; save the Output as evidence.

	Enable with Config.DevTools.InputProbe = true or Workspace attribute RemakeInputProbe = true.
	Works in Studio and in a private test place on a device (an on-screen overlay shows the last
	inputs, which is readable in a headset). Remove or disable it before publishing.

	Output lines: REMAKE_INPUT {"e":"began","kc":"ButtonR2","ut":"Gamepad1","pos":[0,0,0.62],"gp":false}
]]

local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local UserInputService = game:GetService("UserInputService")
local VRService = game:GetService("VRService")
local Workspace = game:GetService("Workspace")

local InputProbe = {}

local TAG = "REMAKE_INPUT"

local function r(v: number): number
	return math.round(v * 1000) / 1000
end

function InputProbe.start(config: { [string]: any }): () -> ()
	local dev = config.DevTools or {}
	if not (dev.InputProbe == true or Workspace:GetAttribute("RemakeInputProbe") == true) then
		return function() end
	end
	local lines: { string } = {}
	local gui = Instance.new("ScreenGui")
	gui.Name = "RemakeInputProbe"
	gui.ResetOnSpawn = false
	gui.DisplayOrder = 1000
	local label = Instance.new("TextLabel")
	label.Size = UDim2.new(0, 520, 0, 220)
	label.Position = UDim2.new(0, 20, 0.5, -110)
	label.BackgroundTransparency = 0.3
	label.BackgroundColor3 = Color3.new(0, 0, 0)
	label.TextColor3 = Color3.new(1, 1, 1)
	label.TextXAlignment = Enum.TextXAlignment.Left
	label.TextYAlignment = Enum.TextYAlignment.Top
	label.Font = Enum.Font.Code
	label.TextSize = 16
	label.Text = "InputProbe"
	label.Parent = gui
	gui.Parent = Players.LocalPlayer:WaitForChild("PlayerGui")

	local lastAnalog: { [string]: number } = {}
	local function log(kind: string, input: InputObject, processed: boolean)
		local key = input.KeyCode.Name .. input.UserInputType.Name
		if kind == "changed" then
			local now = os.clock()
			if lastAnalog[key] and now - lastAnalog[key] < 0.1 then
				return -- throttle analog spam to 10 Hz per control
			end
			lastAnalog[key] = now
		end
		local p = input.Position
		local entry = {
			e = kind,
			kc = input.KeyCode.Name,
			ut = input.UserInputType.Name,
			pos = { r(p.X), r(p.Y), r(p.Z) },
			gp = processed,
		}
		print(`{TAG} {HttpService:JSONEncode(entry)}`)
		table.insert(lines, 1, `{kind} {entry.kc} {entry.ut} ({entry.pos[1]}, {entry.pos[2]}, {entry.pos[3]})`)
		if #lines > 10 then
			table.remove(lines)
		end
		label.Text = table.concat(lines, "\n")
	end

	local vr = { vr = VRService.VREnabled }
	for _, kind in { Enum.UserCFrame.Head, Enum.UserCFrame.LeftHand, Enum.UserCFrame.RightHand, Enum.UserCFrame.Floor } do
		(vr :: any)[kind.Name] = VRService:GetUserCFrameEnabled(kind)
	end
	print(
		`{TAG} {HttpService:JSONEncode({ e = "session", device = vr, preferred = UserInputService.PreferredInput.Name })}`
	)

	local conns = {
		UserInputService.InputBegan:Connect(function(i, gp)
			log("began", i, gp)
		end),
		UserInputService.InputChanged:Connect(function(i, gp)
			if i.UserInputType ~= Enum.UserInputType.MouseMovement then
				log("changed", i, gp)
			end
		end),
		UserInputService.InputEnded:Connect(function(i, gp)
			log("ended", i, gp)
		end),
	}
	return function()
		for _, c in conns do
			c:Disconnect()
		end
		gui:Destroy()
	end
end

return InputProbe
