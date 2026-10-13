# World bed conversion

`tools/world_beds.py` maps authored KCD1 `Bed` entities in the selected initial
world to KCD2 `StanceSmartObject` and sleep-trigger contracts. It runs in the
normal region builder after the rental and miller conversions. For an existing
combined development mod, `tools/build_world_beds.py` creates an incremental
staging package without installing it.

## Coverage

The 13 October 2026 source audit found 1,387 active beds. The development build
adds 1,385 contracts and preserves the two existing contracts: the Rattay rental
bed (source 53331) and miller bed (source 38157). Another 438 beds belong to
inactive source layers and are not activated by this conversion.

| Source family | Active count | Native family |
| --- | ---: | --- |
| Bed | 255 | Bed_1Place_High; includes the two preserved beds |
| CampBed | 591 | Bed_1Place_Low |
| Bed_StrictLeft | 3 | Bed_1Place_Low_Right, rotated to the source approach side |
| ShelterBed | 140 | Bed_1Place_Tent |
| TentBed | 41 | Bed_1Place_Tent |
| SleepingBench_Left | 310 | Bed_1Place_Bench |
| SleepingBench_Right | 40 | Bed_1Place_Bench |
| SleepingBench | 7 | Bed_1Place_Bench |

## Native contract

- Keep the imported KCD1 furniture geometry and collision unchanged.
- Add native stance and interaction entities with deterministic GUIDs, closed
  entity links and exported AI waiting links.
- Clone independent native scheduler hubs with their sleeper healing effects;
  reject donors with external activity or equipment dependencies.
- Register native helper animation collections and request animation validation
  at the imported location instead of copying baked Trosky projections.
- Preserve source sleep and reading quality.
- Make newly converted beds temporarily usable without ownership checks, as
  requested. Do not change existing rental or miller ownership/schedules.
- Package identical scheduler and animation tables in the level and the
  mod-qualified travel archive paths.

Raised-bed alignment uses both source sitting helpers, matching the previously
accepted rental correction. Low beds use the same source-X/native-Y axis
conversion. Benches match the sitting helper; shelters and tents match their
authored entry transform. These latter mappings still require representative
animation/clearance acceptance in game. Native bench animations do not yet
reproduce every source left/right restriction.

## Validation

Six focused tests cover all eight families, local links and scheduler records,
source visual preservation, temporary access, inactive-layer exclusion,
existing owned contracts, scaled-bed rejection and duplicate installation.
The local full suite passed 567 tests, including pre-existing local experiment
tests; this count is not a claim that all beds have passed gameplay testing.

The staged build preserved 1,007 unrelated level entries and 2,654 unrelated
travel-archive entries. Both existing bed contracts were retained. Backups
were made before installation into the development client; the retail mod
was not changed.

In-game checks on 13 October 2026:

- Raised bed 101843 in Skalitz exposed Sit and Sleep. Invoking its native
  trigger opened the sleep menu at 60% comfort. Starting one hour through the
  game UI completed the sleep timer and returned to the room.
- Ground bed 59728 exposed Sleep and opened the native menu at 40% comfort,
  consistent with its lower source quality. The native trigger reported usable
  and legal. Screenshots are retained in `outputs/WorldBeds/build01/`.
- Sleeping bench 102671 could not start its lying animation. The user identified
  that placement as too close to the wall and explicitly asked to ignore it.
  Its furniture placement and collision are unchanged; this is not counted as
  a successful sleeping-bench test.
- No `Hub must be actual scheduler hub` error was observed during these tests.
  Existing unrelated wildlife navigation and other world warnings remain in
  the development log.

The tests used native trigger dispatch through the development console and the
native sleep UI; they are sampled development-client evidence, not full-map or
retail acceptance. Remaining checks include sitting/getting up and animation
clearance for each family, shelter/tent alignment, unrestricted bench samples,
save/load, and original NPC/home ownership as those systems are converted.
