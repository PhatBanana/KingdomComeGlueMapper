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
