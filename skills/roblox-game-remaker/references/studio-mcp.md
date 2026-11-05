# Driving Roblox Studio (MCP, and the path without it)

Read this before any Studio operation. Studio has a **built-in MCP server**. When it is
connected, run the remake loop (inspect → build → playtest → capture → compare) through its
tools. When it is not, use Rojo plus the manual and CLI paths at the end.

## 1. Setup (built-in server)

In Studio: **Assistant ⟩ ⋯ ⟩ Manage MCP Servers ⟩ Enable Studio as MCP server**. The panel then
offers **Quick connect** for Antigravity, Codex CLI, Claude Code, Claude Desktop, Cursor, Gemini
CLI and Visual Studio Code. A green indicator shows connected clients.

Manual configuration uses stdio:

```json
{ "mcpServers": { "Roblox_Studio": {
    "command": "/Applications/RobloxStudio.app/Contents/MacOS/StudioMCP" } } }
```

On Windows: `"command": "cmd.exe", "args": ["/c", "%LOCALAPPDATA%\\Roblox\\mcp.bat"]`.

For Claude Code, run the same command through `claude mcp add`:

```bash
claude mcp add --transport stdio Roblox_Studio -- /Applications/RobloxStudio.app/Contents/MacOS/StudioMCP
```

On Windows, use `cmd.exe /c %LOCALAPPDATA%\Roblox\mcp.bat` as the command. Restart the client
afterwards. MCP clients can read and modify open places, so connect only trusted clients.

The older standalone `Roblox/studio-rust-mcp-server` (tools `run_code`, `insert_model`,
`get_console_output`, `start_stop_play`, `run_script_in_play_mode`, `get_studio_mode`) was archived on
2026-04-03. Use the built-in server. If a user still has the old one connected, map the
operations to whatever tools you actually have.

## 2. Tools (built-in server)

Every call takes `studio_id`. Get it from `list_roblox_studios`, and pick by place name when
several windows are open.

| Group | Tools |
|---|---|
| Session | `list_roblox_studios` |
| Explore | `search_game_tree` (flat JSON with path, class and keyword filters, depth limit), `inspect_instance` (properties, attributes, children summary), `subagent` (`explore` or `playtest` types) |
| Scripts | `script_read` (dot paths like `game.ServerScriptService.X`, line ranges), `multi_edit` (creates the script if the path is new; `datamodel_type` Edit), `script_search` (fuzzy, up to 10), `script_grep` (up to 50 matches) |
| Execute | `execute_luau` (`datamodel_type`: Edit, Client or Server) |
| Playtest | `get_studio_state`, `start_stop_play`, `get_console_output`, `screen_capture` (optional camera position and look-at) |
| Input simulation | `character_navigation` (to a position or instance, with a speed multiplier), `user_keyboard_input`, `user_mouse_input` |
| Assets | `search_asset`, `insert_asset`, `upload_image`, `store_image`, `generate_mesh`, `generate_material`, `generate_procedural_model`, `wait_job_finished` |
| Docs | `http_get` (allowed Roblox documentation URLs), `skill` (Roblox-authored guidance) |

Tool lists change. Use the tools your client actually lists, and do not call names you do not
have.

## 3. The remake loop over MCP

1. **Inventory:** `search_game_tree` from `game` with depth 2, then `script_search` and
   `script_grep` for existing systems. Never duplicate an existing controller.
2. **Write code:** `multi_edit` into the paths from the template layout. If the project uses Rojo,
   edit the files on disk instead, because Rojo overwrites Studio-side edits of synced scripts.
3. **Build geometry deterministically:** write the level's metric layout as JSON and generate the
   build script with `scripts/studio_snippets.py greybox layout.json --studs-per-meter X --out greybox.luau`.
   Run it with `execute_luau` (Edit). It rebuilds `Workspace.Level_Greybox` each time, so builds are
   repeatable and reviewable.
4. **Playtest:** `start_stop_play` → `get_studio_state` (wait for play) → reproduce the reference
   test with `character_navigation`, `user_keyboard_input` (for example hold `W` for 1 s, then
   press `Space`) → `get_console_output` for harness lines → `start_stop_play` to stop.
5. **Measure:** save the console output, clean it with
   `scripts/studio_snippets.py extract-log console.txt --out remake/logs/run-NN.log` (it also
   summarizes `REMAKE_SMOKE` results), and run `scripts/measure_compare.py` on it.
6. **Capture shots:** `screen_capture` with the shot's camera position and look-at. For an exact
   FOV and hidden UI, first run the snippet from `studio_snippets.py apply-shot remake/shots.json --id SHOT-03`
   with `execute_luau` (Client, during play), then capture. `studio_snippets.py shots` generates the
   `Shots` module for the F7/F8 hotkeys.
7. **Compare:** save the capture as `remake/captures/<shot>.png`, then run `scripts/visual_compare.py`.
8. **Assets:** `search_asset` and `insert_asset` only for assets the user has rights to use
   (their own inventory, or Creator Store assets whose terms permit it). Inspect inserted models'
   descendants for scripts before keeping them. AI-generated meshes and materials are placeholders
   until approved, so record them in the asset manifest.

`screen_capture` returns image data. If your client cannot view images, report that and rely on
`visual_compare.py` numbers from saved captures.

## 4. Safety rules

- Confirm before destructive operations (deleting instances, overwriting scripts, mass edits).
- Keep experiments in a `RemakeScratch` folder and delete it at the end.
- Never run code from inserted third-party models without reading it first.
- `execute_luau` runs with plugin-level permissions; keep it to the task.

## 5. Without MCP

| Need | Path |
|---|---|
| Code sync | Rojo: `rojo serve` plus the Rojo Studio plugin, or `rojo build -o remake.rbxlx` and open the file |
| Run a script headlessly | Studio CLI: `RobloxStudio --task RunScript --localPlaceFile <abs path to remake.rbxlx> --runScriptFile <abs path to smoke.luau> --outputFile out.log --quitAfterExecution` (Windows and macOS) |
| Open a place or script | `--task EditFile --localPlaceFile <path>`; `--task EditPlace --placeId N --universeId M` |
| Dump the API | `--api out.json`, `--fullApi out.json` |
| Playtests | Manual Test / Server & Clients; ask the user to run the scenario and paste the Output |
| Captures | Ask the user for screenshots from `ShotCamera` shots (hotkeys in the template), at the reference resolution |

Tell the user exactly what to click and what to paste back. Label results from these runs as
"Executed by user", together with the evidence they pasted.
