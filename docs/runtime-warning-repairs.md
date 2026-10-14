# Runtime warning and placeholder repairs

## 15 October 2026: vegetation streaming comparison

The reported forest traversal session recorded one `StreamOnComplete` state
check failure (state 6), followed by 594 merged-render-node error messages.
It also recorded 91 Henry idle/run facial animation queue overflows, 231
water-emitter particle-limit warnings and 20 empty brush bounding boxes.
These are separate symptoms; the log does not establish a texture-memory
exhaustion cause. Missing material textures are present as well.

Compared the installed vegetation-GI bake with the previous complete lighting
set using two fresh development-client processes, the same direct map load,
1280x720 window, frozen playline and fixed 84-second flight route. Seven legs
crossed the area around (1777,1173), continued to the river around (2485,764),
then returned. Both runs acknowledged all seven legs and completion. Neither
run reproduced the streaming completion failure or merged-node errors; neither
reproduced the facial queue or water-emitter warnings during the route.

This is an **inconclusive reproduction**, not a fix or a performance benchmark.
Programmatic flight at fixed altitude and a fresh direct-map session do not
reproduce the original gameplay state, camera path, dwell times or animation
transitions. An attempted time-of-day command was unsupported, so explicit
time-of-day control was not established. No matched frame-time measurements
were collected. A longer normal-gameplay reproduction is still required.

All 83,431 installed merged-sector files passed structural record/coordinate
validation. Archive entry CRC/size comparison found no merged-sector changes
between the previous and current terrain packages; only `terrain/terrain.dat`
changed. The level archive has identical entry contents. This rules out removed
sector files in this update, not runtime format incompatibility or contention.

The current vegetation lighting was restored after testing. All ten installed
package SHA-256 hashes match its installation receipt, and exactly its eight
SVO shards are present. Local evidence, scripts, route logs and restoration
checks are under `outputs/StreamingAudit/2026-10-15/`. The streaming issue remains
open; do not treat a successful bake/install as runtime streaming acceptance.

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

Update: the world-wide supplemental rebuild described below supersedes that
installation limitation.

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
Before the world-wide LOD rebuild, doorway samples showed
roughly 6-7 ms GBuffer and 3 ms shadow maps, with only a small change when the
fireplace light or GI application was disabled. These sampled diagnostics are
not a performance acceptance test for either repair.

## World-wide external LOD dependency rebuild

`tools/rebuild_world_lods.py` compares installed imported models with the retained
converted-data build and computes external LOD dependency closure. Existing
installed assets take precedence and are never overwritten. It writes additive
ZIP32 shards, checks archive integrity and SHA-256 payloads, and records every
added asset in `receipt.json`. This preserves subsequent gameplay/material fixes
instead of reinstalling an older complete world package.

The 13 October 2026 build scanned 4,684 installed base models. Of those, 3,404 had
authored external LODs in the converted build: 5,714 LOD meshes in total, including
the six previously restored hop meshes. It restored 5,708 missing meshes and one
additional material (393,161,766 payload bytes) in
`gluemapper_world_lods_000.pak`. All discovered dependencies resolved. Coverage
is against the retained converted build; this does not invent LODs for models
without authored companions or rebuild native HLOD group proxies.

The supplemental package is installed in the development client. The source
package and installed copy have matching hashes. Tests cover transitive LOD
materials/streams, preservation of newer installed materials, exclusion of
unplaced models and a repeat build producing no additions. Whole-map visual
LOD transitions remain a separate acceptance check.

An independent post-install rebuild found all 5,714 authored LOD meshes present,
zero missing dependencies and no further assets to package. The game log confirms
that the supplemental archive mounted and the level reached `RUNNING`.
The user confirmed that the performance issues were fixed after this installation.
This is gameplay acceptance; no matched before/after FPS benchmark was recorded.

## Player facial animation queue overflow (15 October 2026)

The reported overflow resolves to `Dude`, native `male.chr`, and native facial
idle/run/sprint clips. A short test with `ForceCharacterUpdate(0,true)` initially
showed zero new warnings, but the user reproduced them by sprinting and returning
to walking: 70 warnings accumulated after that first marker and another 46 after
reapplying the setting. That first diagnostic is not a successful repair.

The engine-wide `ca_ForceUpdateSkeletons=1` diagnostic stopped new warnings during
the user's repeated sprint transitions. It has been restored to its original 0.
The narrower `CharacterUpdateAlways(0,true)` flag is now under live test on the
player. The related engine implementation distinguishes a character instance
update flag from `ForceCharacterUpdate`, which modifies currently queued clips:
https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryEntitySystem/ScriptBind_Entity.cpp
This related implementation is explanatory evidence, not KCD2 source code.

`player_animation_updates.py` appends idempotent Player-only lifecycle wrappers
after the existing travel/horse hooks. It reapplies the character flag after
initialization, reset, AI load and model replacement, forwarding callback arguments
and all return values. NPC classes and animation data remain unchanged. Executable
Lua tests cover model replacement, lifecycle callbacks, nil return values,
idempotence and preservation of NPC methods. Cold-start and dialogue regressions
still require runtime verification; staging alone is not installation.

The separate empty OSH preset dictionary and homeless NPC warnings predate these
diagnostics and are not repaired by the animation update change.

The player-only live diagnostic subsequently retained zero new overflows with
the global override at zero. The persistent package is installed; its receipt
and recoverable previous archive are in
`outputs/AnimationOverflow/PlayerAlways01/`. Every other archive entry was
verified unchanged. Restart persistence remains a separate runtime check.

The user also reports white smoke, sweeping dust and eyelids. Investigate the
particle lighting/material conversion and compare the eyelid material separately.
A shared lighting cause is a hypothesis, not established by their similar colour;
this animation change does not repair those materials.
