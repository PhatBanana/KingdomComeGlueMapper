# Clearance emulator validation

Date: 2026-10-27. Developer tool: [Clearance Check](../tools/clearance_lab/README.md).
Everything below is offline emulation of level data. It is **not native-runtime
verification**: no traversal, physics or barrier behaviour was observed in game.

## Verified implementation

- [x] Standard-library command line tool (`inventory`, `audit`, `run`); never imported by Setup.
- [x] Reads the package's `level.pak`/`terrain.pak` and `Data/*.pak` in place; no extraction or writes.
- [x] Walks every `terrain/hlods.dat` record with fixed strides; an unknown kind or block overrun is UNSUPPORTED.
- [x] Designer volume = oriented box from the CGF local bounds and the brush matrix; float3 vertex bounds preferred.
- [x] Surface type from the brush or CGF material `.mtl` (package, then KCD2 install); unresolved or mixed → UNSUPPORTED.
- [x] Blocking semantics read from native `SurfaceTypes.xml` (`player_only`, `horse_only`, `Barrier`, ground speed modifiers); unknown surface → UNSUPPORTED.
- [x] Interaction clearance for doors (box), use points (capsule disc) and ladders (sampled axis), with z-band filtering.
- [x] Origin-coincident volumes at interactions (the `ef8f35a` signature) are always defects.
- [x] Duplicate placements (origin and full bounds within 2 mm).
- [x] Outer ring closure: panel-end attachment, open-end gap width, player/horse passability, component count.
- [x] Road centrelines from KCD2 road records against the ring, other blockers and the terrain edge, grouped into sites.
- [x] KCD1 every-source-volume reconstruction (`--kcd1`) reported separately and never in the package verdict.
- [x] JSON/HTML/JUnit reports with source hashes, assumptions and the not-modelled list; UNSUPPORTED is a JUnit error.

## Tests run

| Check | Result | Meaning |
| --- | --- | --- |
| `tests/test_clearance_lab.py` | 24 passed | Synthetic blobs: hlods/terrain/CGF/mtl/SurfaceTypes/mission readers, unresolved inputs, geometry, door/pot/ladder clearance, z band, ground proxies, duplicates, ring closure and gaps, road crossings, runner and CLI exit codes |
| Full repository suite | see commit message | No production code changed |

Installed-data checks (local only, not in version control):

| Check | Result |
| --- | --- |
| `audit` on `jobs/20261022-160453-a9a40cd-main-fresh/package/map` | 58 designer volumes, all layer-0 `mat_level_barrier`; 0 unsupported; ~11 s |
| Ring mutation: drop one panel at a time (9 of 58 sampled) | every drop reported as a `boundary_gap` defect at that panel's two ends |
| `--kcd1` reconstruction | 940 horse-only volumes origin-coincident with doors: 939 `gm_door_*` (= the 939 removed by `ef8f35a`) plus `gm_rental_door`; 280 cooking triggers enclosed by player-only volumes (the `cadcf08` class) |

## 10-22 package outcome

| Check | Status | Notes |
| --- | --- | --- |
| `interaction_clearance` | FAIL | 2 KCD1 containers sit inside the north level barrier slab (also so in the KCD1 source placement) |
| `duplicate_volumes` | PASS | |
| `boundary_closure` | PASS | 58 panels, one component, every end attached |
| `road_crossings` | REVIEW | 12 barrier-crossing sites and 5 map-edge sites, including the #29 east road at about x 3937, y 1829 |

Details and in-game spots: `issues/emulators/clearance-findings.md` (outside the repository).

## Remaining boundaries

- [ ] Native helper shapes (door passage, smart-object use positions, ladder entry/exit) are not read.
- [ ] Only designer collision volumes are obstacles; building/prop/entity collision and navmesh are not modelled.
- [ ] Terrain height versus barrier top, slopes and steps are not checked.
- [ ] `player_only`/`horse_only` runtime filtering is not confirmed (in game, horse-only door blockers were reported blocking Henry).
- [ ] Barrier slowdown, warning distance and monologue are native behaviour.
- [ ] `mat_counterfeiters_barrier` and `mat_skalitz_barrier` (KCD1 quest barriers, not in the package) are absent from the KCD2 surface table and stay unknown in the reconstruction.
