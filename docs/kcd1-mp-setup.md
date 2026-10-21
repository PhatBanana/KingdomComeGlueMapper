# KCD1:MP setup option

KCD1:MP is an experimental, separate scenery export for KCD:MP 0.44.0 and
Steam retail KCD2 1.5.6. It does not convert campaign quests into co-op quests.

## Build and reuse

Select **KCD1:MP → Multiplayer settings** in the setup library. Choose the
KCD:MP client and server distribution folders. Setup validates their version
fingerprints and copies them into the exported profile, so Downloads is not a
permanent runtime dependency. Hosting requires the .NET 10 x64 runtime.

For an existing world, use **Find completed builds** or browse to a finished
build, its package collection, or its map folder. An empty source falls back
to the installed KCD1 Map. This preserves the map's lighting and compiled
shaders without rebaking. A standalone lighting cache is not a world package.

To make a new world, select both **KCD1 Map** and **KCD1:MP**, leave the source
blank, and use the normal lighting/cache choices. The ordinary map build uses
the shared workspace cache and offers imported cache candidates as usual;
the multiplayer export consumes its completed output afterwards.

**Build packages** only creates the export. **Build & install** also activates
the multiplayer mod. The export resides in `<job>/package/mp`, including
`profile.json`, `client_mod`, `server-profile`, and copied `runtime` folders.
The immutable multiplayer snapshot requires additional disk space.

## Configure and launch

The Multiplayer screen groups map source, client, server settings and launch
controls. Server name, port, player limit, password, PvP, starting time and
time speed are configurable. Client name and join address are separate from
the hosting port. For a local host, the join address's port must match the
configured server port. Servers are unlisted but may listen beyond localhost.

Choose the exported profile to reload its saved settings. Use **Save settings**,
then **Start server**. **Activate map** is needed when the export was built
without installation or after restoring single-player. Use **Join server** or
**Offline test** to start the client. Setup prepares its canonical Data/Levels
and compiled-shader runtime before handing that root to KCD:MP. It supplies
Steam's app context and does not modify the native retail Engine archives.

Launcher output goes to `<profile>/client-launcher.log`,
`offline-launcher.log`, or `server-launcher.log`. The server's own log is in
`server-profile`. Setup keeps its hosting window open until **Stop server**;
it does not stop unrelated servers. Restart a hosted server after changing
its settings.

Activation saves the previous mod order and enables only KCD1:MP. Other
installed mods remain on disk. Close KCD2 and choose **Restore single-player**
to restore the exact previous order. A later manual mod-order edit is preserved
and reported rather than overwritten by restoration.

## Acceptance boundary

The exporter removes campaign startup, NPC schedules and animal spawners.
Model-backed furnishings and doors are inert. All clients need the matching
converted world; the server allow-list alone does not enforce map checksums.
Server terrain/navmesh/collision exports are disabled in this initial mode.

Tests cover scene filtering, unchanged lighting/terrain payloads, shader
packaging, runtime copying, settings serialization, setup routing, launch
arguments and activation/restoration. The setup UI has browser tests.
Real player initialization, map traversal and two-client synchronization still
require an in-game test. A process PID or listening server is not acceptance.
