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

Required for the analysis scripts. First resolve `SKILL_ROOT` to the installed folder
containing `SKILL.md` (not the repository or project), and `PROJECT_ROOT` to your project:

| Layout | `SKILL_ROOT` |
|---|---|
| Working in this repo | `<checkout>/skills/roblox-game-remaker` |
| Manual `.agents` or skills CLI project install | `<project>/.agents/skills/roblox-game-remaker` (follow any client-created link) |
| Manual Claude | `<project>/.claude/skills/roblox-game-remaker` |
| Claude plugin | Client-reported plugin skill directory under its versioned cache, ending in `skills/roblox-game-remaker` |
| Global CLI/manual | Client-reported user-wide skills folder, ending in `roblox-game-remaker` |

Never assume plugin/cache version paths. Ask the agent to report the loaded `SKILL.md` path,
then use its parent directory. Check `SKILL_ROOT/scripts/requirements.txt` exists. Bootstrap
from the user's project, not from the installation:

```bash
export SKILL_ROOT="/absolute/path/to/installed/roblox-game-remaker"
export PROJECT_ROOT="/absolute/path/to/your/project"
cd "$PROJECT_ROOT"
python -m venv "$PROJECT_ROOT/.venv"
. "$PROJECT_ROOT/.venv/bin/activate"
python -m pip install -r "$SKILL_ROOT/scripts/requirements.txt"
python "$SKILL_ROOT/scripts/remake_status.py" "$PROJECT_ROOT/remake" --init --game "My Game" --write
```

On Windows PowerShell set `$env:SKILL_ROOT` and `$env:PROJECT_ROOT`, and activate
`& "$env:PROJECT_ROOT/.venv/Scripts/Activate.ps1"` instead. Subsequent `python` commands use
that environment. Re-running session start preserves existing files.

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
python "$SKILL_ROOT/scripts/doctor.py" "$PROJECT_ROOT"
```

When validating a build, prefer the explicit project configuration:

```bash
python "$SKILL_ROOT/scripts/config_check.py" "$PROJECT_ROOT/remake" --config "$PROJECT_ROOT/src/shared/Remake/Config.luau"
```

Automatic discovery ignores installed/bundled skills, templates, samples and dependencies.
It requires exactly one project candidate; multiple candidates produce a usage error listing
paths, not a guessed selection. `--config` always selects the file you give it.

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
bash "$SKILL_ROOT/examples/demo/run_demo.sh" "$PROJECT_ROOT/remake-demo"
```

The demo generates synthetic footage with known answers and runs the whole measurement pipeline.
The measured jump should come out at about 8 studs with a 0.40 s rise, and the run at about
20 studs/s.

## Updating

- Plugin: `claude plugin marketplace update roblox-game-remaker`, then
  `claude plugin update roblox-game-remaker@roblox-game-remaker`.
- `skills` CLI: `npx skills update`.
- Manual: pull the repository and copy the folder again.
