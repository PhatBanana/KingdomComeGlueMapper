# Runtime warning and placeholder repairs

## 13 October 2026

The converter now rejects native item definitions whose models point to the
retired `preproduction/traffic_cone/` placeholder. Matching source items are
imported with distinct item IDs and their original KCD1 models; subsequent
conversion runs reuse those replacements. The installed sample repairs one
smoked-sausage placement and 20 large-meal-tray placements. An optional asset
namespace keeps incremental dependency packages separate from existing assets.
The user confirmed the items now appear. Their original NPCTool classification
is retained; pickup/food behaviour and the reported candle rendering issue are
not established as fixed by this change.

Wildlife conversion now moves compiled scheduler positions with their entities.
The installed repair updated 190 scheduler rows. A reviewed anchor for
`prib_forest_w` moves its five linked entities onto nearby navigable ground,
preserving the original habitat, population and identities. Conversion rejects
that anchor if it falls outside the source habitat. The previously repeated
`SpawnedAnimal_Hare_5A92FD1D_5` out-of-navmesh error did not recur in sampled
restarts. A separate long-distance hare pathfinding fallback remains unresolved.

Two legacy Vranik fire effects now cap CountScale at 0.25 after observed particle
helper-array overflows. This affects four installed emitters and preserves their
effect names, scale and activity. Close-view appearance at those emitters still
needs validation; this is not a general particle-parity claim.

The development client's missing `Data/Facials` directory was linked locally to
the installed retail KCD2 `Data/Facials` directory. After restart, the sampled
log contained no invalid facial-animation references or facial archive opening
errors. This is a local installation repair, not a redistributed asset package.

Validation: 18 focused unit tests pass (wildlife: 4, environment: 8, world items:
6). They cover scheduler position remapping, habitat-boundary checks, targeted
and idempotent particle limits, and distinct reusable placeholder item IDs.
UI Hub, SqcbLoad and other unrelated development-client diagnostics are not
claimed resolved.

## Hop-garden rendering investigation

The hop structures around (736.57, 3432.09) retain their original KCD1 mesh and
physics chunks byte-for-byte, apart from material path remapping. Their foliage
proxy surface, `mat_vegetation_seethrough`, has `no_collide=1` in both games.
Separate vine meshes sampled nearby have no dedicated physics chunks.

The asset packager omitted external `_lod1.cgf` through `_lod6.cgf` companions:
they are loaded by convention rather than explicit references inside the base
mesh. Dependency closure now includes available companions and recursively
includes their materials and streamed files. A regression test checks that
unrelated meshes are not included. All nine packaging tests pass.

A local supplemental package restores LOD1 and LOD2 for all three imported
`pk_garden_hops_a/b/c` models using their installed material paths (six files).
The broader installed world has not been rebuilt with the corrected packager.

Diagnostic snapshots before the repair showed approximately 108 FPS looking
upward and 46 FPS looking into the plants and surrounding scene. At the same
slow camera view, disabling particles gave 47 FPS, disabling all shadows gave
65 FPS, and changing e_LodRatio from 300 to 40 gave 47 FPS. These are individual
samples, not benchmark averages; time of day continued advancing. They establish
view-dependent rendering cost, not that the missing hop LODs explain the entire
near-camera slowdown. All diagnostic rendering settings were restored. A
performance improvement from the LOD repair remains unverified.

## Native wall-vine motion

KCD2 retains the matching `Objects/natural/vegetation/vines/vine_*.cgf` family.
Its `vine.mtl` reduces WaveX amplitude from 0.025 to 0.0015 and frequency from
0.25 to 0.006, with different phase, level, divider and noise settings. The
static-asset converter now reads that native material and copies its complete
VertexDeform element, vertex modification type and detail-bending parameters
for the exact KCD1 `objects/vegetation/vines/vine` material. Source textures,
geometry and appearance parameters remain intact; this is motion adaptation,
not a wholesale native material replacement.

The local `gluemapper_native_vines.pak` applies that motion to both installed
copies, `gluebuild/setup_buildings/m784.mtl` and `gluebuild/setup_props/m485.mtl`.
A regression test covers exact deformation copying, idempotence and preservation
of textures/appearance. Visual acceptance of the motion remains pending.

The user subsequently reported that motion appears tied to frame rate. Matching
native deformation settings does not establish frame-rate independence. A
side-by-side native/imported vine test at fixed frame caps remains required.
The house rendering slowdown also remains unresolved: doorway samples showed
roughly 6-7 ms GBuffer and 3 ms shadow maps, with only a small change when the
fireplace light or GI application was disabled. These sampled diagnostics are
not a performance acceptance test for either repair.
