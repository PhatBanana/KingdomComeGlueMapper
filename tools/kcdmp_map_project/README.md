# GlueMapper → KCDMP: map loading patch project

This project exports the **already converted KCD1 world** as a separate scenery
mod for **KCD:MP 0.44.0**. It creates a matching server profile and launchers.
It is an experimental first-load integration: **the real game has not been
run or confirmed working by this project’s tests**.

The key finding is that KCDMP already accepts `kcd1_travel` as a level name.
The necessary work is packaging the converted world without GlueMapper’s
single-player startup and using the same level and spawn on both sides.
There is no map-name whitelist that needs hex-patching in the supplied build.

## Quick start on your Windows gaming PC

You need:

- Python **3.11 or newer**. The project uses only the standard library; no pip
  install, C++ compilation or new lighting bake is needed.
- Your supported **retail KCD2 1.5.6 Steam or Microsoft Store installation**.
  The exact engine DLL is checked against the supplied client’s build table.
  For Steam, use the game root. For Microsoft Store, use its `Content` root
  containing `MicrosoftGame.Config` and `KingdomCome.exe`.
- Your complete, current **`kingdomcomegluemapper` combined mod/package**, with
  `Data/Levels/kcd1_travel/level.pak`, `terrain.pak`, and its root asset PAKs.
  A Git checkout contains conversion code, not the converted game assets.
- The original `KcdMp-0.44.0-win-x64.zip` and `KcdMp-server-0.44.0.zip`, or their
  extracted distributions. Put both ZIPs beside `SETUP.cmd` for the defaults.
- The **.NET 10 x64 runtime** to run the supplied Windows server. Its
  `KcdMp.Server.runtimeconfig.json` targets `Microsoft.NETCore.App 10.0.0`.
  [Microsoft’s runtime download](https://dotnet.microsoft.com/en-us/download/dotnet/10.0).

1. Extract this project outside the game folder and run **`SETUP.cmd`**.
2. Supply the game root, converted mod, client/server ZIPs or folders, and a
   fresh output directory. This builds a separate snapshot and does not
   activate it yet. Copying the world may take time and substantial disk space.
3. Close KCD2. In the generated output, run **`1_ACTIVATE_MAP.cmd`**.
4. Run **`2_START_SERVER.cmd`** and leave that window open.
5. Run **`3_JOIN_LOCAL_SERVER.cmd`**. Steam must be running for the Steam game.
6. Look for a server log line like **`SamGCoder spawned on kcd1_travel at ...`**.
   Once in game, `/where` reports the level/coordinates and `/spawn` returns
   your player to the selected start.
7. When finished, close KCD2 and run **`RESTORE_MODS.cmd`**.

`OFFLINE_MAP_TEST.cmd` launches this map through the KCDMP client without a
server. Use it to separate a map/actor-loading failure from a network failure.
It does not invoke GlueMapper’s coach or New Game campaign path.

## What this patches

| Component | Result |
| --- | --- |
| Mod identity | A new `gluemapperkcdmp` package; original `kingdomcomegluemapper` files remain intact. |
| Level identity | Keeps `kcd1_travel`, LevelId `1001`, and its original world coordinates. |
| Render resources | Retains converted terrain, meshes, materials, textures, HLOD, collision render meshes, and baked SVO/probe data from the source package. Pure asset PAKs and auxiliary render PAKs are copied byte-for-byte. |
| Scene metadata | Removes quest controllers, NPC/animal spawners, schedulers, profile startup and gameplay rows. Keeps native level-table schemas and the existing native player soul record. |
| Furnishings | Known direct-model furnishings become inert visual objects. Their doors, inventories, ladders and interaction logic are outside this first-load export. Unsupported classes/models are listed in the audit. |
| Environmental entities | Retains supported lights, fog, particles and audio entities. Embedded flowgraph/script actions are removed with other runtime hooks. |
| Global overrides | Excludes campaign Lua, the global Player override, coach/quest graphs, campaign tables and menu replacements from mixed PAKs. Retains rendering assets stored alongside them. |
| Retail level registration | Regenerates the custom level row and cleaned level-table aliases under `Mods/gluemapperkcdmp/Data/Levels/kcd1_travel/tables/...`. |
| Spawn | Reads `gmtravel_arrival_kcd1` from the actual converted scene; writes the same XYZ/heading to the native SpawnPoint, server TOML, Lua mode and offline launcher. |
| Server | Selects `kcd1_travel`, turns native story quests off, accepts only the test mod ID, and runs a small player-spawn mode. |

The scene policy treats the main mission as the source’s compiled visual
baseline, flattens additional initial-state visual entity layers, and empties
other entity layers while retaining their definitions for compiled render
references. It is a new export policy, not a claim of complete visual parity.
`build-report.json` lists what was kept, converted, emptied or excluded.

**Copying only `level.pak` would be insufficient:** GlueMapper’s root asset
shards contain materials, textures and geometry required by that level.
Likewise, including `gluemappertravel.pak` unchanged would bring its global
Player hook and travel/quest code back into the session.

## Direct command line

Run this from the extracted project folder, changing the example paths:

```bat
py -3 patch.py build ^
  --game "D:\Games\KingdomComeDeliverance2" ^
  --source-mod "D:\Games\KingdomComeDeliverance2\Mods\kingdomcomegluemapper" ^
  --client "D:\Downloads\KcdMp-0.44.0-win-x64.zip" ^
  --server "D:\Downloads\KcdMp-server-0.44.0.zip" ^
  --output "D:\KCDMP-Map-Test" ^
  --name SamGCoder
```

Use `inspect` instead of `build` for a read-only compatibility/space report.
If the authored arrival marker is absent, provide a position you have verified
in the converted world:

```text
--spawn X Y Z --yaw DEGREES
```

The letters above are placeholders. The tool never substitutes a guessed
Trosky coordinate. Heading is in degrees: 0 faces +Y and 90 faces −X.
Use a real grounded Z for the generated native SpawnPoint. A negative Z is a
special client/server teleport convention, not a physical underground spawn
you should put into the map.

`--host 127.0.0.1:7777` is the default join endpoint. The port also configures
the generated server. Another computer can set `--host` to the host machine’s
address. Every player needs their own compatible converted map installed;
KCDMP’s server overlay is not a download of the terrain/assets.

## Add it to KingdomComeGlueMapper

The ZIP includes **`gluemapper-kcdmp.patch`**, containing additions under
`tools/kcdmp_map_project/`. It does not alter the existing conversion/setup
implementation. From a GlueMapper checkout:

```bat
git apply --check "D:\Downloads\project\gluemapper-kcdmp.patch"
git apply "D:\Downloads\project\gluemapper-kcdmp.patch"
py -3 tools\kcdmp_map_project\patch.py setup
```

The standalone project and repository patch contain the same implementation.
The inspected upstream commit is
[`80afe68572c2d0690c97b4ea0ae0e6dc5f87a301`](https://github.com/SamG-Coder/KingdomComeGlueMapper/tree/80afe68572c2d0690c97b4ea0ae0e6dc5f87a301).

## Activation and restoration

Building is separate from installation. Activation stages the generated map,
saves the exact old `Mods/mod_order.txt` bytes (including an absent file), and
enables only `gluemapperkcdmp` for this test. Other installed mods are not
rewritten. An existing folder with the new mod ID is never overwritten.

Where possible, installation hard-links large PAKs **from this project’s own
exported snapshot** to avoid another full copy. The original single-player
conversion is never hard-linked or edited. Different drives use ordinary
copies. Keep sufficient free space on the game drive if that applies.
Treat shared asset PAKs as read-only: editing an installed linked asset also
changes that exported snapshot. The cleaned core level/registration PAKs and
control files are ordinary copies. Restore and build a new snapshot to update
the map.

Restoration moves the generated map outside `Mods` and reinstates the exact
previous order. It preserves the generated map and any later changes to it.
If you changed `mod_order.txt` yourself after activation, restoration stops
instead of overwriting your edits. An interruption leaves a recovery journal.
Even if the output directory is lost, the source project can recover with:

```bat
py -3 patch.py restore --game "D:\Games\KingdomComeDeliverance2"
```

Keep the generated output folder while using its launchers. Its paths are
absolute; moving the game/runtime/output directories requires rebuilding the
profile. `VERIFY_PROFILE.cmd` checks the package inventory, file sizes and
core hashes. `verify --profile PATH --full` hashes every generated asset.

## Server scope

The first-load profile is unlisted, has four player slots, no PVP, no item
grants, and a fixed midday clock. Unlisted means no public master-server
announcement; the server still listens on network interfaces. The launcher
clears inherited `KCDMP_*` variables in the child process so they cannot
override the isolated profile’s master URL/database settings.

`[world] map` is KCDMP’s placed-object/removal overlay. It does not contain
the game world. Optional server terrain, navmesh and collision exports are
disabled for this initial test. Adding them later requires exports from
**this exact converted map**; a stock Trosky export has different coordinates.
The client retains its own map geometry/physics. Server validation disabled
here is not a substitute for building correct server data later.

The mod allow-list rejects foreign loaded mods but does not require the
listed mod to be present or compare asset hashes between players. Local
preflight checks the installed generated package. Do not describe this
as a completed custom-world multiplayer implementation.

## If it does not reach the map

| Symptom | What to inspect |
| --- | --- |
| Build says the game DLL does not match | Use the supported retail 1.5.6 executable selected by the launcher. A development engine is not supported by the supplied native hooks. |
| `kcd1_travel` or registration is missing | Select the complete combined GlueMapper output, not source code, an old world-only package, or a loose developer Data folder. |
| Server says another mod is prohibited | Close the game and activate the generated profile. Its allow-list uses manifest IDs. |
| Server runs but no player-spawn log appears | Test `OFFLINE_MAP_TEST.cmd`. The client needs both the actual `sv_map` and a local actor before its ready handshake. |
| Map loads but the player never becomes ready | Inspect the native debug-start/local-actor path and the generated native SpawnPoint. KCDMP’s story-off mode filters `LevelHolder`, so the former campaign entry graph cannot supply required initialization. |
| Missing textures, buildings or lighting | Check `build-report.json`, source asset completeness, and the game’s missing-resource messages. Do not copy only the level PAK. |
| Spawn is wrong | Supply verified XYZ/heading and rebuild a fresh profile. The default comes from the source marker and cannot account for a subsequently changed terrain. |
| Freeze or crash during loading | Keep the client/game log, `server-profile/server.kcd1-map-only.log` and `build-report.json`. A listening server alone is not a successful map load. |

Acceptance still needed on the real game: load the map, create the local
actor, complete the ready/spawn handshake, walk with collision, inspect baked
lighting/HLOD, then join with a second client and verify both players.

## Project contents and validation

`kcdmp_bridge/` contains the archive exporter, scene adapter, build/preflight,
activation/recovery and argv-only launch code. `templates/` contains the small
Lua mode, exact server configuration and API notes. `evidence/` records binary
fingerprints and the code-inspection basis. `tests/` uses synthetic assets;
the optional distribution checks read your original ZIPs without executing
their binaries. See **`VALIDATION.md`** for the performed checks and limits.

```bat
py -3 -m unittest discover -s tests -v
```

No retail game asset, KCDMP executable, or native binary patch is included in
this source ZIP. The exporter consumes your local files when you run it.

## Evidence

- [GlueMapper package/table mounting code](https://github.com/SamG-Coder/KingdomComeGlueMapper/blob/80afe68572c2d0690c97b4ea0ae0e6dc5f87a301/tools/campaign_package.py)
- [GlueMapper travel scene and authored arrival](https://github.com/SamG-Coder/KingdomComeGlueMapper/blob/80afe68572c2d0690c97b4ea0ae0e6dc5f87a301/tools/region_travel.py)
- [GlueMapper native destination lifecycle](https://github.com/SamG-Coder/KingdomComeGlueMapper/blob/80afe68572c2d0690c97b4ea0ae0e6dc5f87a301/tools/region_travel_entry.py)
- [KCDMP server configuration](https://docs.kcd-mp.com/getting-started/server-config/)
- `evidence/client-inspection.md`, `evidence/inspected-packages.json`, and
  `templates/SERVER_API_NOTES.md` document the exact attached 0.44.0 build.

The GlueMapper-derived format adapters retain its MIT notice in `LICENSE`.
