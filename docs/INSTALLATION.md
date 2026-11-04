# Installation

The skill is the folder `skills/roblox-game-remaker/`. It follows the open
[Agent Skills](https://agentskills.io/specification) format (`SKILL.md` plus `references/`,
`scripts/`, `assets/`, `examples/`), so the same folder works in every client that supports
Agent Skills. Install the whole folder: the references, scripts and templates are part of the
skill.

## 1. Install the skill

### Claude Code: plugin marketplace (recommended)

```bash
claude plugin marketplace add InfiniteMindData/Roblox-Game-Remaker
```

```bash
claude plugin install roblox-game-remaker@roblox-game-remaker
```

Check it with `/plugin` or `/skills` inside Claude Code. Claude loads the skill automatically when
a request matches its description, and you can also invoke it with
`/roblox-game-remaker:roblox-game-remaker`. Add `--scope project` to both commands to share the
install with your team through the project's settings.

### Any agent: the `skills` CLI

The [`skills`](https://www.npmjs.com/package/skills) CLI detects your agents and installs into
each one's skills directory (Node.js 22.20 or later):

```bash
npx skills add InfiniteMindData/Roblox-Game-Remaker
```

Add `-a <agent>` to target one agent (for example `-a cursor`, `-a codex`, `-a gemini-cli`) or
`-g` to install globally.

### Manual copy

```bash
git clone https://github.com/InfiniteMindData/Roblox-Game-Remaker
```

Then copy the folder into the agent's skills directory:

| Agent | Project directory | User-wide directory |
|---|---|---|
| Claude Code, Claude Agent SDK | `.claude/skills/` | `~/.claude/skills/` |
| OpenAI Codex, Gemini CLI, Antigravity, and other `.agents` readers | `.agents/skills/` | `~/.agents/skills/` |
| Cursor | `.cursor/skills/` or `.agents/skills/` | see Cursor docs |
| GitHub Copilot | `.github/skills/` | see Copilot docs |
| Windsurf / Devin Desktop | `.devin/skills/` or `.windsurf/skills/` | see Windsurf docs |
| Kiro | `.kiro/skills/` | `~/.kiro/skills/` |
| OpenCode | `.opencode/skills/` | see OpenCode docs |

For example, for Claude Code in the current project:

```bash
mkdir -p .claude/skills && cp -R Roblox-Game-Remaker/skills/roblox-game-remaker .claude/skills/
```

Agent paths change over time; the `skills` CLI tracks them for you.

### Claude.ai

1. Settings ⟩ Capabilities: turn on code execution and file creation.
2. Zip the folder so that `roblox-game-remaker/` is the zip root:

```bash
cd Roblox-Game-Remaker/skills && zip -r roblox-game-remaker.zip roblox-game-remaker
```

3. Customize ⟩ Skills: upload the zip and turn the skill on.

The claude.ai sandbox cannot reach Roblox Studio, so use it for research, breakdowns, footage
analysis and code generation.

## 2. Install the tools the scripts use

Required for the analysis scripts:

```bash
pip install -r skills/roblox-game-remaker/scripts/requirements.txt
```

- **Python 3.10+** with numpy and Pillow (from the requirements file above).
- **ffmpeg and ffprobe** for the video scripts (`probe_video`, `extract_frames`, `audio_onsets`):
  install from your package manager or https://ffmpeg.org.

Optional:

| Tool | Used for | Install |
|---|---|---|
| Roblox Studio | Building and testing the remake | https://create.roblox.com |
| Studio MCP server | Letting the agent inspect, edit, playtest and capture Studio | Built into Studio, see below |
| Rojo | File-based sync and `rojo build` of the template | https://rojo.space, or `cargo install rojo` |
| Lune | Running the template's Luau unit tests | `cargo install lune` |
| StyLua | Luau formatting and syntax checks | `cargo install stylua --features luau` |
| Selene | Luau linting with the Roblox standard library | `cargo install selene` |
| Blender 4.x | Modeling, rigging, animation, `blender_roblox_export.py` | https://www.blender.org |

Check what the agent will see:

```bash
python skills/roblox-game-remaker/scripts/doctor.py
```

## 3. Connect Roblox Studio over MCP (optional, recommended)

In Studio, open **Assistant ⟩ ⋯ ⟩ Manage MCP Servers** and turn on **Enable Studio as MCP
server**. Use **Quick connect** for Claude Code, Claude Desktop, Cursor, Codex CLI, Gemini CLI,
Antigravity or VS Code. For other clients, add the server by hand.

macOS:

```bash
claude mcp add --transport stdio Roblox_Studio -- /Applications/RobloxStudio.app/Contents/MacOS/StudioMCP
```

Windows (JSON configuration):

```json
{ "mcpServers": { "Roblox_Studio": { "command": "cmd.exe", "args": ["/c", "%LOCALAPPDATA%\\Roblox\\mcp.bat"] } } }
```

Restart the client afterwards; a green indicator in Studio's MCP settings confirms the
connection. MCP clients can read and modify your open places, so connect only clients you trust.
Details: `skills/roblox-game-remaker/references/studio-mcp.md`.

## 4. Check the install

```bash
cd skills/roblox-game-remaker
bash examples/demo/run_demo.sh /tmp/remake-demo
```

The demo generates synthetic footage with known answers and runs the whole measurement pipeline.
The measured jump should come out at about 8 studs with a 0.40 s rise, and the run at about
20 studs/s.

## Updating

- Plugin: `claude plugin marketplace update roblox-game-remaker`, then
  `claude plugin update roblox-game-remaker@roblox-game-remaker`.
- `skills` CLI: `npx skills update`.
- Manual: pull the repository and copy the folder again.
