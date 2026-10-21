# Native fence-repair phase

The next bounded schedule task converts one hammer-repair position per source
housework fence. Selection uses the source `housework` gender branch and
`repair_home_fence` query. No NPC names, coordinates, faction changes or runtime
initialization hooks select the work.

Only source-linked `Fence` objects with a supported `repairFence` template and
an authored hammer-repair helper are eligible. The first authored helper supplies
the contact transform, including parent placement, rotation and scale. Other
helpers are retained in the report as unfinished traversal, not silently marked
as converted. An NPC without an eligible linked fence keeps its existing work.

KCD2's native `so_fence.use` supplies `repairFenceHammer` and its 15-second game-time
wait. The converter validates its single-occupant contract, local animation
collection, scheduler role and soil effect against Trosky's data. It copies local
animation references with imported world transforms and runtime validation. It
does not copy Trosky collision results or projected world positions.

The source schedule's work hours remain on both the actor-to-pool and pool-to-work
edges. The activity identity is derived from the source fence, so multiple
workers share one exclusive repair object. Existing quest or modified schedules
are not replaced. Setup recipe 45 handles clean conversions and older owned
housework arrivals; reapplication does not duplicate a completed pool.

This is not the complete housework controller. Cooking/fire tending, water work,
chopping wood, rest, phase rotation, the unarmed repair variant and traversal of
the remaining fence helpers are still reported as pending. It does not reproduce
the source's random hammer/unarmed choice. Runtime tool appearance, contact
alignment and interruption cleanup must be observed before accepting the phase.

## Validation

Seven focused tests cover source query/reservation checks, authored helper
placement, linked-only selection, shared fence identity, source work hours,
rejection of changed owners and female schedules, conflicting geometry, repeat
upgrade and explicit pending-phase reporting. The related setup, population and
schedule regression selection passes 94 tests.

The real-data setup-path stage converts three eligible workers in the selected
Skalitz profile: `ska_beranMr`, `ska_enemyOfHenry` and `ska_farmer27`. These are test
subjects, not converter selectors. It emits six shared fence objects and validates
archive CRCs, scheduler targets and mounted resource aliases. It is staged
on top of the user-confirmed bench update. The test was installed in retail on
22 October 2026 with verified archive hashes and a rollback copy. All 62 NPC
entities retained their properties; only the selected owned work graphs and
their animation resources changed. The fence behavior is not runtime verified.

## Next retail check

1. Install the staged level/travel pair with a verified baseline and rollback.
2. Observe a worker walk to the authored fence and visibly repair it with a hammer.
3. Check hand contact, ground height, facing and tool removal when leaving.
4. Interrupt with dialogue, then verify clean exit and resumption.
5. Check two eligible workers cannot use the same repair position simultaneously.
6. Check schedule-end, leaving/returning to the area, and save/reload behavior.
7. Inspect movement/animation errors and confirm bench, embroidery and shop-guard
   activities still work.

Structural checks alone do not establish these runtime outcomes.
