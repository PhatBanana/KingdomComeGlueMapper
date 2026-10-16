# Kingdom Come Connect: KCD1 hosting investigation

Inspected 16 October 2026 against the user's downloaded KCDC 1.6.9 at
`C:/Users/samue/Downloads/KCDC-1.6.9/KCDC-1.6.9`.

## Result

A server.json change alone cannot host `kcd1_travel` on this release.
An isolated run of the supplied Windows server with that level exited with
code 1 before hosting. Its diagnostic explicitly permits only `kutnohorsko`,
`trosecko`, and `klaster`. Evidence is retained in
`outputs/kcdc-investigation/custom-level-test.log` and the matching JSON.
The top-level `map` setting is unused; the setting is `mod.level`.

The supplied native client/server are binaries. The included TypeScript is the
gamemode, not the native loader or config validator. The public organization
repository listing inspected for this investigation exposes documentation,
not the native implementation. Native source access or a supported custom-level
release is the clean prerequisite for completing this integration.

## Verified local facts

- The supplied server config defaults to `mod.level = kutnohorsko`.
- Its gamemode handles `playerSpawning` through `pickSpawnPoint()` in
  `src/server/spawns.ts`. The point list is empty, so it uses the level default.
- The KCDC launcher resolves the retail Steam installation
  `D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2`, not `KCD2Mod`.
- The retail engine log from the KCDC run at 21:42 reports GlueMapper enabled
  and opens its mod packages. This confirms mod mounting during that run;
  it does not prove that KCDC successfully loads our custom level.
- The KCDC client log reached a connected session on `kutnohorsko`, with zero
  resource scripts. A custom gamemode must be compiled before hosting.
- The development map includes level.pak, terrain.pak, levelinfo.xml, eight
  SVO archives and a 117,011,191-byte recast.pak. Existence is not proof that
  KCDC's navigation reader accepts that archive or covers the intended routes.
- The installed development map is newer than the retail build. Building this
  option must explicitly select the intended verified conversion package.
- No downloaded KCDC files, game files or active servers were modified.

## Proposed separate build profile

Add a Kingdom Come Connect profile after native custom-level support is
available, reusing the converted world rather than rerunning conversion:

1. Client world package: preserve terrain, geometry, collisions, materials,
   vegetation, interiors, lighting and ambient content. Audit the single-player
   coach/entry quests, NPC schedules and interactive entities against KCDC's
   Population and WorldContent behavior; do not assume independent client AI
   becomes shared multiplayer AI. Start with a world-exploration profile.
2. Native KCDC integration: accept and replicate `kcd1_travel`; resolve it in
   the client loader and world-editor level registry; supply a custom default
   start and avoid built-in level-specific catalogs at unrelated coordinates.
   Exact native patch locations require source inspection.
3. Client preinstallation: generate the world locally from each player's games,
   install before launching KCDC, and require the same build fingerprint on
   joining clients. This fingerprint check needs explicit implementation;
   the stock distribution does not establish it for our map.
4. Server profile: set `mod.level` to `kcd1_travel`, supply the matching
   recast.pak through `mod.navmesh`, and compile a gamemode with a known map
   spawn, initially (733.87537, 3421.9014, 63.908913). This is the source start
   used by the existing launch probe; validate it again inside KCDC.
5. Emit separate server and client instructions/receipts, label the result
   experimental until the runtime checks below pass. Preserve the normal
   single-player build profile.

KCDC resources cannot carry this whole map through the normal asset channel:
`replace/` excludes levels, libs, scripts and other game-data folders, while
`stream/` permits namespaced art assets. `mod.world_resources` is for World
Builder placements/routes, not compiled terrain and level archives.

## Possible stock-binary experiment

A separately installed map override under a supported level identity could
potentially get past the server whitelist. This has NOT been established to
work. It requires coherent level identity/path/registration changes, matching
client installations, correct spawns and navmesh, and an audit of KCDC's
built-in door/gate/area catalogs. A directory rename alone is not a complete
solution. It would also occupy a built-in map slot, so any experiment belongs
in an isolated installation/profile, with explicit install and restore steps.
Do not publish this as a working build option before client runtime validation.

## Acceptance boundary

- Server starts and reports the custom level in its status endpoint.
- Client joins that level and spawns on the correct ground without a coach trip.
- Two clients agree on positions, see each other and reconnect correctly.
- Both traverse representative interiors and terrain with matching collision.
- Server navigation returns routes on the KCD1 world, not a stock KCD2 region.
- Doors, inventory, beds and AI are tested individually for authority/sync;
  single-player support does not prove multiplayer synchronization.
- KCDC auto-update behavior cannot silently remove custom native support.

## Primary references

- https://docs.kingdomsconnected.com/guides/hosting-a-server/server-json/
- https://docs.kingdomsconnected.com/guides/core-concepts/custom-assets/
- https://docs.kingdomsconnected.com/guides/world/world-builder/
- https://github.com/orgs/kingdomsconnected/repositories
- Local KCDC README.txt, server/server.json, gamemode src/server/index.ts and spawns.ts
