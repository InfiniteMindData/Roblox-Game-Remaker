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

1. **Inventory:** `search_game_tree` from each content container (`Workspace`,
   `ReplicatedStorage`, `ServerScriptService`, `ServerStorage`, `StarterPlayer`, `StarterGui`,
   `Lighting`) with depth 2-3, not from `game`: the root holds over 100 engine services, which
   fill the result limit before any of the place's own content. Then `script_search` and
   `script_grep` for existing systems. Never duplicate an existing controller. Note whether the
   player has a Humanoid character at all: many games (fighting games, top-down and vehicle games)
   drive their own rigs from a custom simulation, and need `SimRecorder` rather than the
   `MeasurementHarness` in step 5.
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
   summarizes `REMAKE_SMOKE` results), and run `scripts/measure_compare.py` on it. The
   `MeasurementHarness` follows the local player's Humanoid only. When motion comes from the game's
   own simulation, call the template's `Remake/SimRecorder` from the simulation step (client or
   server) and run `measure_compare.py run.log --subject p1 --interval startup=attack..active`;
   targets with `"unit": "frames"` are judged in simulation ticks. A log with no motion samples
   fails instead of passing.

   **`get_console_output` keeps only the most recent output** and marks the rest
   `[TRUNCATED DUE TO LENGTH LIMIT]`: a 60 Hz log of a few seconds already loses its start, and
   with it the `{"k":"sim"}` header. Either keep each run short (log one subject, read the console
   after each segment), or read the complete Output from Studio's own log file, which has no limit:
   `%LOCALAPPDATA%\Roblox\logs\*_Studio_*_last.log` on Windows, `~/Library/Logs/Roblox/` on macOS.
   Print a marker such as `REMAKE_RUN run-03 begin` / `end` with `execute_luau` around each run
   and cut the file between the markers. `extract-log` keeps the `REMAKE_*` lines. If a run starts
   after the recorder was created, copy its `{"k":"sim"}` header line into the run's log.

   Frame data: `--interval startup=attack..active` pairs each start with the first end before the
   next start, and reports starts without an end as unpaired, so `--interval contact=attack..hit`
   measures only the attacks that connected. On a hit, hitstop pauses the move's own frame
   counter, so `attack..neutral` grows by the hitstop length; compare whiffs with whiffs.
   Simulation logs report `ground_speed[STATE]` per grounded state (forward and backward walk
   separately); plain `ground_speed` is the median over all of them.
6. **Capture shots:** `screen_capture` with the shot's camera position and look-at. For an exact
   FOV and hidden UI, first run the snippet from `studio_snippets.py apply-shot remake/shots.json --id SHOT-03`
   with `execute_luau` (Client, during play), then capture. `studio_snippets.py shots` generates the
   `Shots` module for the F7/F8 hotkeys.
7. **Compare:** save the capture under `remake/captures/`, then run `scripts/visual_compare.py`.
   `screen_capture` returns a **JPEG at the viewport's size**, not a lossless frame at the reference
   resolution. Renaming it `.png` changes nothing. Two consequences:
   - **Aspect ratio:** a docked Studio viewport is rarely 16:9 (1581x615 is typical).
     `visual_compare.py` fails a pair whose aspect ratios differ by more than 1% instead of
     stretching it. Undock or resize the viewport, or use Studio's device emulator at the
     reference resolution, before capturing.
   - **Compression:** JPEG alone costs about 1-1.5 mean delta E (around 4 at the 95th percentile),
     so leave that headroom in `delta_e_mean` thresholds, or ask the user for lossless screenshots
     for color-critical shots.
   A pair with no thresholds reports `unchecked`, never `pass`.
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
