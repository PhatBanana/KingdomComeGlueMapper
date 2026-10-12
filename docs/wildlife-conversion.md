# Native wildlife in the imported KCD1 world

The converter uses KCD2 animal souls, models, animations and brains. It does not
replace native character assets or import KCD1 animal rigs.

`tools/wildlife.py` is called by the normal `region_travel.py` world build and by
`tools/build_wildlife_probe.py` for isolated staging. The latter defaults to one
site; `--limit 0` stages all supported sites. Install only while the game is closed.
The output report identifies every source site, native template and deferred link.
Repeated application to an already converted level is rejected.

## Converted population

| KCD1 source | KCD2 animal | Sites |
|---|---|---:|
| Boar | Boar | 39 |
| RedDeer | RedDeerStag | 47 |
| DeerDoe | RedDeerDoe | 72 |
| RoeBuck | RoeDeerBuck | 56 |
| Forest/dynamic areas | Hare | 15 |

These 229 registrations configure 752 animals in total. This is the configured
population, not a claim that all animals stay loaded simultaneously.

KCD1 proximity holders have self-linked `animalSpawn[...]` definitions. Regional
ecosystem links can refer to the same holders with different counts. The converter
uses the self-linked contract searched by `final/so_animal_proximity.xml`; it does
not add a second regional population. Non-self-only links and livestock are
reported as deferred, not silently interpreted or enabled.

Native per-species activity networks are selected from Trosky's shipped compiled
scheduler. The converter remaps all selected entity identities, scheduler targets,
positioning delegates and waiting links. Optimized-away scheduler hubs are
materialized as destination-owned SchedulerHub entities. Networks with unresolved
dependencies, multiple areas, other spawners or unrelated entity classes are
rejected. No Trosky habitat coordinates are retained.

Boar/deer spawn radii become inscribed 24-sided polygons at the authored locations.
They are spawn/normal activity areas, not barriers preventing fleeing animals from
leaving. Their vertical clearance is ten metres around the authored position.
No new paths or navigation mesh are fabricated; the imported level's existing
navigation is used. Native activity selection governs movement.

## Hares

KCD1 `sa_forest` and `sa_dynamicSpawnAnimals` reference `final/dynamic.xml`. Its
default population is eight, with `Script Misc="hares:N"` overrides. All 15 source
area polygons and heights are transformed from local XML coordinates to world
coordinates once and written into the target trigger-area format. Zero overrides
are respected. A terrain-grounded interior point is selected for the spawner.

KCD2 manages these populations over the source region polygons. This deliberately
replaces KCD1's player-centred 45-metre dynamic spawning, so local hare density is
not guaranteed to match KCD1. It is not a port of the old dynamic behaviour tree.

## Validation and outstanding checks

Three regression tests cover duplicate population avoidance, identity/delegate
remapping, repeat-install rejection, source polygon transforms and hare overrides.
Staging verifies that unrelated archive entries retain their CRC and size.
Shared-builder output was compared against the installed staged payloads.

Local evidence: `outputs/WildlifeAudit/Boar03` contains the pre-wildlife level
backup and two runtime boar position samples; `AllSites03` is the installed full
build and `AllSites04` confirms the refactored shared converter reproduces it.
The initial boar pilot spawned two native Boar actors; both changed position
between samples. Full-build runtime checks confirmed 229 AnimalSpawner entities
and native Hare, Boar, RedDeerDoe, RedDeerStag and RoeDeerBuck actors near visited
habitats. Four roe bucks were observed at the final test location.

Respawn hours are converted to fractional `RespawnDays`, but the runtime's exact
fractional-day handling is unverified. Hunting, loot, save/load, timed population
replenishment and navigation at every individual habitat remain acceptance tests.
No global runtime-parity claim is made from the sampled habitats.
