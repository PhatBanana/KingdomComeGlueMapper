# Native animal population upgrader

Status, 20 October 2026: the user confirmed the repaired animal test works in
retail. Version 2 preserves the compiled scheduler registrations missing from
the first test, which crashed during loading. The supported ambient conversion
is now included in clean setup and resume through build recipe 35. This acceptance
does not establish completion of the 35 deferred source contracts, long-term
respawning, ownership/crime parity or save/load stress tests.

## Retail load crash and repair

The 13:23:29 retail crash dump records an access violation reading address `0x20`
in `WHGame.dll`, RVA `0x644f5d` (BugSplat reports the code-relative offset
`WHGame!00643f5d`). The instruction is `test byte ptr [rax + 0x20], 8`, with
`rax = 0`. Its caller is at RVA `0x64345b`; the code traverses activity records
and calls the singleton identified by native RTTI as `C_SchedulerManager`.
This is evidence of a null scheduler dependency, not a rendering/GPU failure.
The small dump does not retain the failing heap record, so it cannot identify
the particular animal that triggered it.

Two converter defects match that failure:

- `horse_activity()` selected a native grazing entity and incoming activity but
  discarded the destination's compiled `C_SmartHub` record. `place_horses()`
  therefore emitted 56 activity targets with entities but no scheduler nodes.
  Native Trosky includes an empty `C_SmartHub` even for these terminal activities.
  The converter now carries that native registration with the selected activity,
  remaps its identity and any compiled position, and writes it for every work point.
- `habitat()` intentionally excluded foreign household activities, but also
  dropped the home hub's scheduler registration. This affected 176 destination
  home hubs. It now retains the native registration attributes while removing
  the unrelated household's outgoing activities.

The original validator checked only entity GUIDs, waiting links and delegates.
It now also requires scheduler registration for managed animal actors, hubs,
smart-object holders and trigger areas, rejects duplicate registrations, and
requires each compiled activity target to have a compiled node. It rejects the
actual version-1 package that crashed. These are general graph checks, with no
animal names, quest IDs or location-specific exceptions.

The repaired package adds exactly 232 scheduler records compared with the failed
test. All previous scheduler rows are identical; only the scheduler, its mounted
alias and the animal manifest change. Entities, geometry, navigation, quests,
materials and placements are unchanged. Regression tests remove leaf/home
registrations while retaining the entities and verify rejection. Native template
selection also rejects a missing leaf registration.

The failed test and dump are preserved under
`outputs/animal-population-20261020/native-stage/retail-install-20261020T022052Z/`.
The repaired test is under `outputs/animal-population-20261020/scheduler-repair-stage/`.
Its installation journal is `retail-install-20261020T023949Z/installation.json`;
both retail archives and the launcher's junction-backed paths were hash-verified.
The user subsequently confirmed this repaired retail test works.

## What was missing

The normal world builder's `wildlife.py` path imports forest wildlife and hares.
Its proximity importer accepts only self-linked spawners and five wildlife
species. It omits livestock and directly placed animal/flock entities.

KCD1 `Scripts.pak:Libs/AI/final/so_animal_proximity.xml` searches its outgoing
`animalSpawn` edges and sets `spawnCenterEntity = this.id`. The target of the
edge can be a regional controller. A self-link is not required. `GetRandomPos`
uses the authored radius directly, without multiplying by the holder's scale.
Thus a cow holder linked to a regional controller still spawns at the holder,
not at the controller's coordinates.

Some existing wildlife holders have both self and regional instructions with
different counts. This change preserves their established self-edge population
and records the alternatives; it does not claim to resolve KCD1's runtime
ordering of those alternatives or sum them into duplicate populations.

## General conversion

- `tools/animal_population_sources.py` selects base/state0 entities and explicitly
  requested source profiles. It composes parent transforms once, resolves source
  references and distinguishes actual proximity holders from regional references.
  Later quest layers are not indiscriminately activated.
- `tools/animal_native_templates.py` finds bounded native activity networks in
  Trosky (`trosecko`) and Kuttenberg (`kutnohorsko`). The sheep/cow/dog networks
  used by the test come from Trosky; the pig network comes from Kuttenberg.
  Native home links are rebound through a destination home hub and `home_area`
  edge. Native household schedulers, owners, doors and world positions are not
  copied into the converted map.
- `tools/animal_population.py` adds missing populations, dogs with authored
  territories, ambient horses and flocks. It preserves source identities for
  placed actors, registers native shared souls, remaps scheduler targets and
  positioning delegates, writes waiting links and matching trigger geometry.
  Existing actors with the same persistent identity retain their service data.
- Livestock use native species souls, classes and activity networks. Models,
  animation databases and brains are provided by KCD2. No KCD1 animal rig or
  behaviour script is copied. The pre-existing wildlife circle-to-polygon
  conversion is reused, including its ten-metre vertical clearance.
- Territorial dogs retain their authored source polygon. Ambient horses use
  the unrestricted native horse `grazing` activity at their authored placement
  or home/standing points. This does not convert horse sale controllers,
  campaign actions, individual breed statistics or ownership/crime systems.
- Chicken variants and fish retain source position, orientation, scale, count,
  radius and activation area. Old serialized models/smart-object properties are
  dropped so native KCD2 classes supply models, animations, sounds and movement.
  Fish retain their authored depth. Chicken household ownership remains an
  in-game acceptance check; adding a flock does not prove crime ownership parity.

The managed manifest fingerprints generated entities, schedules, area geometry,
soul registrations and waiting links. A repeat conversion validates these records
and returns identical output. Changed source profiles, placements or referenced
territories require a fresh stage. Damaged managed records and missing references
are errors, rather than reasons to add another copy of the animals.

## Staged coverage

The test used the installed retail mod as its baseline and selected
`q_skalitz_normal`, matching the current static world layout.

| Added content | Source sites / actors | Configured population |
| --- | ---: | ---: |
| Cattle | 38 sites | 126 |
| Sheep | 24 sites | 196 |
| Pigs | 55 sites | 102 |
| Additional deer/roe/boar | 13 sites | 36 |
| Territorial dogs | 59 actors | 59 |
| Ambient horses | 55 actors | 55 |
| Chickens | 162 flock placements | Source flock counts |
| Fish | 41 flock placements | Source flock counts |

These are authored/configured counts, not simultaneous runtime actor counts.
The existing 214 self-linked wildlife populations and 15 hare regions remain.
Skalitz placements include the source cow/sheep sites and six source horses.

Thirty-five active source records remain unsupported and are listed in the report:

- 18 dogs with master/home contracts requiring their owning actor adapter.
- 11 horses with stable, sales, flee or quest/service bindings.
- 4 zero-radius population sites requiring a native point-spawn conversion.
- 2 malformed source instructions, including a comma inside a radius value.

No active base/state0/selected-profile bird flock was found. Inactive quest birds
are left inactive. The output must not be described as all animal systems complete.

## Running the general upgrader

`tools/build_animal_population_upgrade.py` stages an overlay for the existing mod.
Its `plan()` API accepts an assembled clean package or an existing package without
rebuilding terrain, models, lighting, navigation or quests. It updates both the
level scheduler and its mounted alias inside `gluemappertravel.pak`.

The default is strict: unsupported contracts produce a report and an error before
writing installable archives. `--allow-partial` explicitly permits a bounded test
of the supported content. It does not conceal the remaining dependencies.

### Clean setup and existing packages

`tools/setup_animal_population.py` runs the same converter from the shared
`setup_package_upgrade.finalize()` path used by clean `build_recipe.run()` builds
and resumed packages. It runs after the static navigation profile conversion,
using `STATIC_WORLD_PROFILES` for the same active source layout. Setup explicitly
selects the tested `supported_native_ambient` scope; it records all unsupported
contracts in both the level manifest and installation receipt. Missing dependencies
within a selected native contract still fail conversion.

Both scheduler aliases are updated before the result is validated. The receipt
records converter version, source profiles, source signature, counts and scheduler
validation. Installation rejects a current-recipe package lacking that validation;
recipe 34 packages remain eligible for migration. Completion is stamped only after
the shared finalizer succeeds. Resume validates existing managed records and
returns identical bytes rather than spawning duplicates. Archive replacements
break staging hardlinks, preserving the previous package if an update fails.
All five converter modules are included in the frozen setup imports and self-test.

The setup adapter was also run against the saved pre-animal retail package.
All 1,014 level archive members and 1,706 travel archive members match the
accepted repaired installation byte-for-byte. Reapplying setup leaves both PAK
hashes unchanged, and the hardlinked baseline retains its original hashes.
Local evidence: `outputs/animal-population-20261020/setup-integration-proof/validation.json`.

```powershell
.venv\Scripts\python.exe tools/build_animal_population_upgrade.py `
  --source D:\SteamLibrary\steamapps\common\KingdomComeDeliverance `
  --target D:\SteamLibrary\steamapps\common\KingdomComeDeliverance2 `
  --mod D:\SteamLibrary\steamapps\common\KingdomComeDeliverance2\Mods\kingdomcomegluemapper `
  --output outputs\animal-population-test `
  --profile q_skalitz_normal --allow-partial
```

The corrected test lives under
`outputs/animal-population-20261020/scheduler-repair-stage/`. `report.json` records every
addition, omission, generated identity, baseline hash and staged archive hash.
`package/` contains only the two replacement archives for the same mod. It is
not a standalone mod and does not install itself. Installation must check the
baseline hashes, preserve backups and take place with the game closed.

## Validation

Automated tests cover source/profile selection, non-self-linked population
placement, source transforms, missing dependencies, duplicate prevention, native
home isolation, direct actor identities, native horse work points, native flock
properties, managed resume, damaged geometry/links, existing service horses,
mounted scheduler consistency and archive preservation.

Actual-archive checks on the staged package confirmed:

- All 33,225 pre-existing entities, 2,668 scheduler rows and 30 soul registrations
  retain their canonical XML records.
- 1,008 unrelated level archive members and 1,705 unrelated travel archive members
  retain CRC and size; both resulting archives pass full CRC validation.
- Trigger polygons match destination `TriggerArea` identities. Existing
  smart-area geometry is not duplicated in the trigger registry.
- Reapplying the converter to the actual staged files is byte-identical.
- The installed baseline archives retain their hashes.
- The sampled native pig, dog, horse, chicken and fish model paths are not
  overridden by the current mod's data archives.

Setup regression tests additionally cover fresh package conversion, resume
idempotence, hardlink isolation, stale mounted scheduler aliases, missing native
registrations, cancellation and receipt installation guards. Clean builds and
recipe 34 migration both route through the shared finalizer.

The user has confirmed the repaired installed test works in retail. Broader
acceptance still needs approach/leave/revisit, ownership/crime, save/load,
population respawn intervals and performance across the world. Native fractional
`RespawnDays` behaviour remains unverified, as in the previous wildlife converter.
Per-build receipts retain `runtime_verified: false`: a successful build does not
itself perform an in-game test.
