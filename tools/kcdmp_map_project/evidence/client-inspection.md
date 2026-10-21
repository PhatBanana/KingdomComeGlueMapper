# KCD:MP 0.44.0 Windows client inspection

Inspected the user's original ZIP read-only. Extracted selected files for static analysis; no package binary was executed. Native address evidence below belongs to precisely these hashes, and is evidence, not a proposed binary patch.

## Fingerprints

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| KcdMp-0.44.0-win-x64.zip | 169526323 | 97fcd1926e8c20b78fbd76344f4e21b88ebcc6befccda2afaa32fde236a8a823 |
| KcdMp_client.dll | 14582208 | af571d1971fe3ea8cc76a3dd4f5f4c34127e9b6c87596f7195c4226c160a7fd6 |
| KcdMp_launcher.exe | 3340736 | 2183021b4e79b203c11c49fa3f64b35cdea840b85c2dbb18d155f05f912acb9c |
| builds.json | 139978 | 1cf020645f91900596047713e3905f13b3688741e3ec1af5fcd1d03aaa43e2ec |

The ZIP has 46 entries, 368822696 uncompressed bytes. It contains native x64 client and launcher, builds.json, servers.txt, launcher UI, in-game HTML/JS components and CEF 154.0.32. No KCD game world, level .pak, map geometry or server game data is included.

## Custom level names already pass the launcher

There is no need to patch a level whitelist in these binaries.

The launcher's UTF-16 command-line help at raw 0x25759e says:

    [--game <dir>] [--dll <path>] [--connect ip:port] [--name <player>] [--token <password>] [--map <level>] [--wait] [-- <game args>]

Its UTF-16 help at raw 0x257da0 calls --map a storyless level start using the game's +map debug start. The examples list the three stock map names, but the actual validation is syntax-based, not an enumeration:

- UTF-16 validator: preferred image VA 0x14000e660 (raw 0xda60). Length 1..64, charset `[A-Za-z0-9_]`.
- `--map` option calls it at 0x140004048.
- Final launch validates its level again at 0x14000673f.
- The server-query reply uses equivalent ASCII validation at 0x14000e0f0 (called at 0x140013310). The nearby error constructor misleadingly says the server named a level the game does not have; its actual gate is still syntax.
- Thus `kcd1_travel` and `gluemapperkcdmp` both pass the launcher gates.

The launcher combines its chosen name into UTF-16 ` +map `, string raw 0x259344, at native 0x14000772c. Its trosecko/kutnohorsko/klaster comparisons around 0x140138030 are human-readable name conversion, falling back to the input string. The same pattern in the client DLL around 0x1d9940910 is also just display-name conversion.

## Concrete command lines

Run these from the directory containing KcdMp_launcher.exe. Use quoted absolute paths for --game. Use a single word player name; the launcher rejects spaces/quotes/game switches in player names, tokens or endpoints.

Offline diagnostic (no server required):

    KcdMp_launcher.exe --game "D:\Games\KingdomComeDeliverance2" --map kcd1_travel --name SamGCoder -- -KcdMp_spawn 1000,1000,-1,0

The 1000/1000 coordinates above are syntax examples only. A deliverable must substitute a known authored spawn marker inside the converted world.

Private server query (does not launch game):

    KcdMp_launcher.exe --connect 127.0.0.1:7777 --query

Private server join:

    KcdMp_launcher.exe --game "D:\Games\KingdomComeDeliverance2" --connect 127.0.0.1:7777 --name SamGCoder

With a configured server password, add `--token <single-word-password>`.

Build check:

    KcdMp_launcher.exe --game "D:\Games\KingdomComeDeliverance2" --check-game

There is no observed `--server`, `--exe`, `--nickname`, `--config`, `--settings`, or `--no-update` launcher option. Use `--connect`, `--game`, and `--name` exactly. The Steam executable is fixed to Bin/Win64MasterMasterSteamPGO/KingdomCome.exe under the game root. Microsoft Store selection expects its installed Content root/KingdomCome.exe beside MicrosoftGame.Config. The launcher has `--dll` for its KCDMP DLL, not for choosing a different game executable.

`--connect` asks the server which map to run. It only copies the query result's map into the launch request if an explicit --map was not supplied (native 0x14000b548..0x14000b59d). Therefore combining --connect and --map is syntactically supported, but omitting --map is better: a manual mismatch will be rejected by the client after Welcome. The DLL message at raw 0xbf83b0 states the server level differs from the level booted, followed by `level mismatch`.

The game launch request includes an explicit game path; scripts should nevertheless set working directory to the launcher directory to keep auxiliary files predictable. Exact alternate launcher config-root override is not exposed. The UI documents `%LOCALAPPDATA%\KcdMp\launcher.json`; `--game` avoids editing the saved GUI game directory.

## Spawn and readiness

`-KcdMp_spawn` is a comma-separated sequence of up to four floating values (x,y,z,yaw). Native parser 0x1d918d08e..0x1d918d1fd reads the flag, searches comma bytes, converts each slice to float and stores four values. This is not a whitespace-separated four-argument option.

The client's embedded spawn Lua at raw 0xb63469:

- Requires `g_localActor`.
- If z < 0, calls System.GetTerrainElevation({x=x,y=y,z=0}) and adds 0.5.
- Moves the player using SetWorldPos, later snapping nearby ground using a physics ray and waking physics.
- For an online session, the server's spawn is authoritative. A known explicit terrain-grounded coordinate in server SpawnInfo is preferable to relying on offline terrain discovery.

The generic world probe at raw 0xbf0966 implements KcdMp.level() using `System.GetCVar("sv_map")`, not a stock-level switch. At raw 0xbf1e6d it waits for both an actual level and `g_localActor`, then emits `KcdMp_ready <level>`. This is the real boot condition to watch in client logs. If the custom level has no local actor, merely changing server.toml cannot make the session ready.

## Important storyless behavior: LevelHolder is filtered

When `-KcdMp_story_quests` is not `1`, engine_boot adds `LevelHolder` to the population/spawn-filter classes. This is concrete native evidence, not inferred just from a message:

- Caller branches at preferred VA 0x1d9193032..0x1d919303b / 0x1d91941c0.
- Helper 0x1d95234f0 constructs a vector containing the single string `LevelHolder`, assembled inline by machine instructions.
- Caller then appends that vector into the population class vector.
- The associated log is `off (the levels' quests stay asleep)` at raw 0xb425b8.

KCDMP also removes/filter-vetoes native population classes such as NPC, NPC_Female, Horse, Dog, Wolf and animals; the embedded strip logic at raw 0xbf0ef5 exempts `g_localActor` and entity names starting `KcdMp_`. Its removed-entity handling clears ENTITY_FLAG_UNREMOVABLE first. The strip repeats until three clean passes, then the spawn filter holds them off.

For GlueMapper this means a custom LevelHolder/Concept graph will not run in story=false mode. Keep an independent Player entity/native debug startup path; any custom Lua or bootstrap exclusively reached through the blocked LevelHolder will not initialize. Root/player/menu script overrides that auto-start GlueMapper travel or quests are poor fits for the MP map-only mod. Retaining required entity/level data without auto-run scripts is a sensible first staging design, but a real game run must confirm its local actor survives and becomes ready.

## Generic +exec cannot be assumed to work

The client hooks CSystem ExecuteCommandLine. Raw 0xbd9778 says command-line + switches are not run, with +map loading the level elsewhere. Do not depend on appending +exec gluemapper.cfg or +lua commands to the launcher. Use the client's own supported `-KcdMp_...` arguments, level content, and server APIs.

## Mods policy

Client raw 0xb45b08 reports `mods: ... loaded by the game`. It detects manifests and mounted paths, including `/data/` and `/data/levels/`, with Steam workshop app 1771300. Do not install KCDMP's own folder under the game's Mods directory: raw 0xb45b58 explicitly warns that the game then loads its folders as mods. Use a separate KCDMP directory.

There is no evidence of automatic disabling/stripping of a scenery mod. The client reports loaded mods; the server rejects admission when they violate its policy. The server-analysis agent confirmed:

- `[mods] policy="any"` is the example default; `refused` still wins.
- `allow_list` compares manifest `modid` values to `allowed`, with `refused` taking precedence.
- Disallowed mods cause Hello rejection reason 8, rather than modifying local installations.

A distinct scenery-only manifest modid `gluemapperkcdmp` is appropriate. Keep the physical map identifier `kcd1_travel` unless the level converter explicitly rewrites every internal reference, asset path and metadata item. There is no benefit in renaming the map simply to satisfy the launcher.

## Version pin and update behavior

builds.json schema 2 contains exactly two supported builds:

| ID | Game version | WHGame SHA-256 | File size | Timestamp | SizeOfImage |
| --- | --- | --- | ---: | ---: | ---: |
| steam-1.5.6-bdf8f9e4 | 1.5.6 | bdf8f9e4a11257a72b64c84700e284c29e4c4ccaf5b8d4bfa7d0b2a7294479f7 | 89180672 | 1781861920 | 95604736 |
| msstore-1.5.6-74126a4c | 1.5.6 | 74126a4c88e819a2a2d046a2011f69ede0335833fef25c28b660ef953abb2e8d | 89993216 | 1782128507 | 96411648 |

`--check-game` exit meanings are help-documented: 0 supported, 2 refused older/no WHGame, 3 newer, 4 could not tell, 1 no game folder. `--skip-build-check` exists but only bypasses the launcher's refusal; it does not resolve native ABI/hook incompatibility and should not appear in default scripts. GlueMapper dev-build use cannot be assumed compatible with this retail-hook client.

The build check must hash the DLL in the actual selected binary directory, not any matching backup under Bin. Native directory helper at 0x14009cdc0 calls Microsoft Store recognizer 0x14009b8d0. For the Store installation it returns the supplied Content root unchanged; otherwise it joins `Bin/Win64MasterMasterSteamPGO`. Build-check code calls the helper at 0x1400a8925, then appends `WHGame.dll` (wide string raw 0x26f2d0). The Store recognizer uses the root `KingdomCome.exe`, `MicrosoftGame.Config`, and identity text `DeepSilver.77536C3FE941` (raw 0x26acc0, 0x26ace0, 0x26ad10). Thus scanning only Bin incorrectly rejects the supported Microsoft Store layout, and scanning all Bin folders can incorrectly accept a supported backup beside an unsupported active executable.

`--builds <file>` reads another table besides the embedded one; it is not a supported way to invent anchors for an incompatible engine.

The GUI offers update checking and an explicit apply button, with settings `update_check`. CLI `--update-check` asks; `--update` fetches/verifies/extracts files over the KCDMP installation. Do not pass `--update` in generated scripts, and record/check package hashes before inspection or build. CEF engine syncing can write its own engine assets/current.json in runtime workflows; package staging itself need not run any KCDMP executable or touch client binaries. There is no exposed no-update CLI switch in this package, so do not invent one.

## Recommended map-only patch boundary and remaining runtime risks

Build a new asset/config project, not a DLL patch: use the already converted `kcd1_travel` level, a distinct mod manifest, clean map-only package selection, server level `kcd1_travel`, compatible mod allow list, and a minimal custom game mode using the actual authored spawn marker.

The server does not need the client's rendering assets just to let clients load a map. Without exports for server collision/heightmap/navmesh and world population, scope the first version to loading/players. Do not include a Trosky navmesh or default Trosky spawn just to satisfy a config field.

Unverified until the user's KCD2 installation is available: engine asset compatibility, all required conversion packages, LevelHolder-independent player bootstrap, terrain rendering, multiplayer handshake to actual sv_map, two-player synchronization, collisions and spawn height, GI/HLOD behavior. Static analysis confirms the selectable-name path and integration points, not end-to-end gameplay.
