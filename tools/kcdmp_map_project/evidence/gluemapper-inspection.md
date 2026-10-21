# GlueMapper integration basis

Repository: https://github.com/SamG-Coder/KingdomComeGlueMapper

Commit inspected: `80afe68572c2d0690c97b4ea0ae0e6dc5f87a301` (20 October 2026).

## Identity and packaging

`tools/setup_campaign.py` defines the installed combined mod ID as
`kingdomcomegluemapper`. `tools/region_travel.py` defines `kcd1_travel`,
LevelId `1001`. `tools/desktop_setup.py` builds the static converted world,
then packages the region-travel additions under the combined identity.

`tools/campaign_package.py::package_world` packages level geometry plus its
transitive imported asset dependencies. `write_asset_shards` preserves
streamed texture slices and external model LODs. The bridge retains complete
render archives instead of trying to replace those dependencies with one
level file.

`mounted_level_tables` documents retail's alias requirement:
`Mods/<modid>/Data/Levels/<level>/tables/...`. `region_travel.build` uses the
same contract for the travel destination. The bridge regenerates aliases
from the final cleaned tables for `gluemapperkcdmp`.

## Startup conflict

`tools/travel_bridge_package.py` validates the shipped
`Scripts/Entities/actor/player.lua` hook in `Data/gluemappertravel.pak`.
`region_travel.build` also writes coach dialogue, level switches, actor
registrations and quest resources into mixed archives. Copying that entire
archive into a map-only mod would preserve those global behaviors.

`tools/region_travel_entry.py` installs a LevelHolder, player services,
GameProfile handling and destination graphs. The supplied KCDMP client's
story-off mode vetoes LevelHolder; an independent native SpawnPoint and local
player bootstrap must carry the first-load test. The native player SoulList
record is retained if it exists. The exporter does not invent a player GUID.

## Scene transform

`tools/upgrade_map.py` provides the static map-probe structure, including
`UseLayersActivation=0`. `tools/campaign_package.py::campaign_spawn_objects`
supplies native SpawnPoint property names. `tools/entity_visuals.py` supplies
the initial state-layer convention. `tools/campaign_trigger_areas.py` supplies
the converted v3 trigger-area layout. `tools/world_environment.py` documents
the reserved local-player entity ID `0x7777` and the converted ambient classes.

This project applies a new explicit scenery export policy to the completed
travel map: retained visual entities are flattened to world transforms;
campaign entities, profile records, gameplay trigger records and local-table
rows are removed. Opaque render payloads are copied unchanged. Class/layer
exclusions, retained player metadata and every changed scene entry are audited.

The authored spawn is read from `gmtravel_arrival_kcd1`. Upstream
`region_travel.station` creates it from the KCD1 epilogue departure marker,
grounds its height using the converted terrain, and places the cart beside
it. No absolute coordinate was guessed in this project.

## Verification boundary

The source describes real format contracts, but it does not establish that
this new combination has completed a KCDMP boot. Source/metadata inspection,
synthetic conversion tests and archive hash checks were possible. The user's
converted PAKs and supported running game were not attached, so real render,
actor initialization, handshake and two-player acceptance remain pending.
