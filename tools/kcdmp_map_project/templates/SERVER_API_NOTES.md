# Server template evidence

These templates target the two KCD:MP **0.44.0** archives supplied with the
request. They do not modify or redistribute the KCD:MP server binaries.

## Configuration

All active TOML keys are documented in the supplied
`windows/server.toml.example` (identical text is shipped under `linux/`). Omitted
keys retain server defaults. There is no documented bind-address key. Empty
`[master] url` disables public announcements; it does not restrict listening to
localhost. Use a separate server directory for this test. Every player's game
must have the same generated map installed.

`[mods] allowed` contains **mod IDs**, matching `mod.manifest`'s `modid`, not
folder names. `gluemapperkcdmp` must match the generated manifest. A disallowed
mod causes a join rejection; the server does not silently disable it. This
allow-list does not require that a joining client actually has the map, so the
builder/client preflight must verify the installed map files separately.

`[world] map` names the server's placement/removal overlay, not level geometry.
The native geometry, terrain, textures and converted level are mounted by each
client. An initially empty `data/maps/kcd1_travel` overlay requires no map data
upload. The server's optional exported heightmap, navmesh and collision are
disabled for the first load so no native level's data can be used accidentally.
Enable them only after generating exports from the actual converted level.

## Isolated runtime directory

Launch the original server executable by its absolute path, with the generated
`server-profile` directory as the **process working directory** and pass the
generated configuration's absolute path after `--config`. The 0.44.0 server
reads that path directly. Paths inside the configuration resolve against the
process working directory, not the executable's directory and not implicitly
against the configuration's directory. This puts the mode, map overlays,
`data/server.db` and log under the isolated profile.

The server does not change its working directory or rebase paths against
`AppContext.BaseDirectory`. Static CIL confirms direct `File.Exists` /
`File.ReadAllText` for config loading and direct relative paths /
`Path.GetFullPath` for the Lua mode, database and log.

For deterministic private startup, remove these inherited environment overrides
from the child process environment: `KCDMP_MASTER_URL`, `KCDMP_MASTER_ADDRESS`,
`KCDMP_DB_DRIVER`, `KCDMP_DB_URL` and `KCDMP_AUDIT_MODE`. They override TOML
values after parsing. In particular, an inherited master URL can announce a
server even when `[master] url` is empty in its file.

The supplied server targets `net10.0` / `Microsoft.NETCore.App 10.0.0` according
to `windows/KcdMp.Server.runtimeconfig.json`. The Windows executable requires the
matching installed .NET runtime; the ZIP is framework-dependent.

## Lua callback sequence and signatures

The supplied `windows/sdk/KcdMp.d.lua` documents:

- `OnGameModeInit()`: set the mode's initial rules here.
- `SetStoryQuests(false)`: keep the game's own story quests asleep. Call before
  clients join. It is **not a guarantee that arbitrary GlueMapper Lua stops**;
  custom campaign modules/schedulers are excluded separately by the builder.
- `OnPlayerConnect(pid)`: the handshake has completed but the level is loading.
- `OnPlayerRequestSpawn(pid)`: the client's level is ready. Call
  `SetSpawnInfo(pid, x, y, z, yaw)` and return `true`. Returning `false` holds the
  player until `SpawnPlayer(pid)`. This callback is not called for death respawns.
- `OnPlayerSpawn(pid)`: called on first spawn, death respawns and `SpawnPlayer`.
- `GetPlayerPos(pid)`: returns `x, y, z`; query when `IsPlayerInWorld(pid)`.
- `GetPlayerYaw(pid)`: heading in degrees; 0 faces +Y, 90 faces -X.
- `SetPlayerPos(pid, x, y, z, yaw)`: updates client position and server movement
  state; a negative Z requests terrain height. It moves a mounted player with
  their horse.
- `OnPlayerCommandText(pid, cmd, args)`: `cmd` excludes the slash. Return `true`
  for handled commands; `false` passes to built-ins.
- `SendClientMessage(pid, COLOR_SERVER, text)`, `Log(text)`,
  `IsPlayerDead(pid)` and `SpawnPlayer(pid)` are supplied API functions.

The shipped `freeroam.lua` uses the same spawn callback ordering and explicitly
calls `SetStoryQuests(false)` in `OnGameModeInit`.

## Static binary findings

These are method-token/RVA references for the supplied Windows DLLs, found by
reading managed metadata and CIL without executing the assemblies. They are
evidence, **not offsets to patch**.

| Assembly and method | Token / RVA | Finding |
| --- | --- | --- |
| `KcdMp.Server.dll`, `ServerOptions.Validate` | `0x06000242` / `0xAF6C` | The level validation only rejects an empty string. No native-level enum restriction. |
| `KcdMp.Server.dll`, `World.get_Level` | `0x060010F7` / `0x91DB9` | Returns the configured level string. |
| `KcdMp.Api.dll`, `Levels.DisplayName` | `0x06000860` / `0xD700` | Maps native level names to display labels; otherwise returns the input. |
| `KcdMp.Server.dll`, `World.get_DefaultSpawn` | `0x060010FC` / `0x91DF8` | Reads configured spawn X/Y/Z/Yaw and presets directly. |
| `KcdMp.Server.dll`, `World.OnHello` | `0x0600119E` / `0x98670` | Compares client and server level strings case-insensitively; rejects mismatches. Also rejects disallowed mods. |
| `KcdMp.Server.dll`, `World.OnReady` | `0x060011A6` / `0x9946C` | Marks the loaded player ready and calls `RequestSpawn`. |
| `KcdMp.Server.dll`, `World.RefusedMods` | `0x0600150C` / `0xCFAF4` | `allow_list` checks mod IDs; `refused` overrides every policy. |

Together these establish that the server does not need a binary patch to use
`kcd1_travel`. They do not establish that the converted level will finish
loading in a real KCD2 client. That requires an in-game test with the generated
map and matching client assets.

## First-run evidence to collect

The server log should name the absolute profile config and then show the
mode's own line `GlueMapper map-only: kcd1_travel, spawn ...`. A successful
client level-ready/first-spawn sequence adds `<player> spawned on kcd1_travel
at ...` from `OnPlayerSpawn`. If that final line never appears, the mode has
not observed the player reach the spawned state; a listening server alone is
not a successful map-load test. The in-game `/where` command should then report
`kcd1_travel` and the expected spawn coordinates.

The TOML template was parsed after numeric placeholder substitution with a
standard TOML parser. The Lua template was compiled and run against mocked
server API functions using the system Lua 5.4 runtime, checking initialization,
spawn callback ordering, exact coordinates, own-player teleport, death respawn,
diagnostics and unknown-command forwarding. This validates the template's
logic, not KCD:MP integration. No supplied server or client binary was executed
for this inspection.

Public reference: <https://docs.kcd-mp.com/getting-started/server-config/>.
For reproduction, prefer the exact SDK/example files in the uploaded 0.44.0
archive if the live website has since changed.
