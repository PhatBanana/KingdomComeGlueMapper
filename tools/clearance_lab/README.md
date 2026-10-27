# Clearance Check — developer tool

An **offline, developer-only** check of physics-blocking designer volumes
against interactions and the playable edge. It reads a finished package (and the
user's KCD2 install for native rules) in place, never extracts or modifies
anything, and is never imported by consumer Setup or bundled in its payload.
Standard library only.

Regression classes it is built for:

- horse-only blockers duplicated at the origins of registered doors (`ef8f35a`, 939 doors);
- player-only blockers enclosing cooking interactions (`cadcf08`);
- map-edge gaps and roads leading off the map (#29, #38).

## Run

```powershell
.venv/Scripts/python.exe tools/clearance_lab_test.py inventory <job>/package/map --target <KCD2> --output outputs/clearance/inventory.json
.venv/Scripts/python.exe tools/clearance_lab_test.py audit <job>/package/map --target <KCD2> [--kcd1 <KCD1>] --output outputs/clearance/audit
.venv/Scripts/python.exe tools/clearance_lab_test.py run scenario.json ... --output outputs/clearance/run
```

`audit` writes `audit.json` (all evidence, source hashes, assumptions),
`report.html` (searchable) and `junit.xml`. Exit code: 0 only when every check
passes; 1 for FAIL, UNSUPPORTED or ERROR (and REVIEW with `--strict`); 2 when
the package could not be read. `--kcd1` adds an informational
`source_reconstruction` section: every KCD1 designer collision volume placed
as-is, which reproduces the pre-`ef8f35a`/`cadcf08` classes. It never affects
the package verdict.

## Inputs (all from level data; nothing is hand-placed)

| Input | Where | Notes |
| --- | --- | --- |
| Designer volumes | `Levels/kcd1_travel/level.pak` `terrain/hlods.dat` kind-1 brushes whose mesh is a designer brush (`/setup_designer/`, `brush/designer_`) or whose material is `materials/special/collision_proxy*` | Mesh path from `terrain.pak` `terrain/terrain.dat` resource table |
| Volume shape | CGF mesh chunk local AABB (float3 vertex stream when present) × brush 3×4 matrix | Oriented box; plan footprint is the hull of its 8 corners |
| Surface type | Brush material, else the CGF material name → `.mtl` (package first, then target) `SurfaceType` | Unresolved or mixed → UNSUPPORTED |
| Surface semantics | Target `IPL_GameData.pak` `Libs/MaterialEffects/SurfaceTypes.xml` | `player_only`, `horse_only`, `<Barrier>`, `AI movementSpeedMult` |
| Interactions | `objects_mission0.xml` entities of the classes in `source.INTERACTION_CLASSES` | Pos/Rotate (w,x,y,z), ladder `height` |
| Roads | `terrain.pak` `terrain/terrain.dat` road records (kind 11) | Paired world-space edge points → centreline and width |
| Map extent | `terrain.dat` header grid × unit | 4096 m for kcd1_travel |

## Checks and verdicts

| Check | Defect (FAIL) | Inspect (REVIEW) |
| --- | --- | --- |
| `interaction_clearance` | penetration ≥ 0.5 m, or volume origin within 2 mm of the interaction origin | any shallower overlap |
| `duplicate_volumes` | same origin and full bounds (2 mm), same surface | same placement, different surface |
| `boundary_closure` | open ring end with gap ≥ 2 m, or no barrier at all | open end with a narrower gap; disconnected ring |
| `road_crossings` | road centreline inside a non-barrier blocker by ≥ 0.5 m | road meets the outer barrier; road ends within 15 m of the terrain edge |

Blocking agents per volume come from the native flags: `player_only` → player,
`horse_only` → horse, a speed-modifier ground surface → none, otherwise all.
The outer ring is every package volume whose surface `<Barrier>` uses the
map-exit monologue `HRAC_NEMUZE_Z_MAPY`. A ring end is attached when another
ring panel touches the half of the panel nearest that end, or the end reaches
the terrain edge. Road findings are also grouped into `sites` (40 m).

## Assumptions (all in `audit.ASSUMPTIONS`, recorded in every report)

Player capsule radius 0.4 m; body band −0.3…+1.8 m around the interaction
position; door passage box ±1.25 m × ±1.0 m × 0…2.2 m in door space (covers a
left or right hinge and the swing); ladders sampled every 0.25 m along their
up axis (3 m when no height); deep = 0.5 m; contact 0.05 m; ring gap passable
by the player above 0.8 m and by a horse above 1.2 m. These are not native
helper shapes, so most findings are `inspect`.

## Not modelled (never a pass)

Physics traversal, steps, slopes and terrain height (including barrier top vs
terrain); barrier slowdown/monologue; native door/smart-object/ladder helper
geometry; any obstacle other than designer collision volumes (buildings, props,
entities, vegetation, navmesh); runtime meaning of `player_only`/`horse_only`
(in game, horse-only door blockers were reported blocking Henry); walking past
the heightmap edge; road surface triangles. `native_runtime_verified` is always
false.

## Scenarios

```json
{"name": "door blocker", "world": {"surfaces": {...}, "extent": [0,0,100,100],
  "volumes": [{"id": "b", "surface": "mat_horse_only", "matrix": [1,0,0,50, 0,1,0,50, 0,0,1,0],
               "local_min": [-0.5,-0.1,0], "local_max": [0.5,0.1,2.5]}],
  "interactions": [{"name": "gm_door_7", "kind": "door", "cls": "AnimDoor", "pos": [50,50,0]}]},
 "assertions": [{"check": "interaction_clearance", "status": "FAIL"},
                {"category": "interaction_overlap", "near": [50,50], "within": 1, "expect": "present"}]}
```

Scenarios may name a `package`/`target`/`kcd1` instead of an inline world.
Package scenarios answer for every check; inline worlds only for the checks
(or finding categories) they assert on. An asserted check that is UNSUPPORTED
makes the scenario UNSUPPORTED, and a scenario without assertions never passes.
Game data and machine-specific scenario paths are kept out of version control.
