# Skalitz job conversion and verification

## Acceptance sequence

Work through one job at a time: source-data audit, generic setup conversion,
native exported-data checks, package validation, live modding-bridge observations,
then commit and push before starting the next job. An emitted scheduler or a
successful test suite does not establish visible work or schedule transitions.
Do not force an animation and record it as autonomous scheduling.

## Installed-town inventory — 22 October 2026

Read the 54 `ska_` NPCs in the installed level and resolve their original KCD1
person records and daycycles. This covers installed residents, not every actor
in every historical source profile. Private evidence is in
`reports/skalitz-job-inventory.json`.

| Source work routine | Residents | Audit disposition |
| --- | ---: | --- |
| Housework | 12 | Partial adapters exist; inspect per-person source branches and available resources |
| City walking | 8 | Existing walking/bench adapter; retain and regress |
| Farming | 6 | Native hoeing with source-derived rows; partial live verification |
| Garrison guard | 5 | Fixed-post adapter exists; dynamic assignment remains separate |
| Merchant | 5 | Existing shop conversion; retain service and routine checks |
| Seated embroidery | 2 | Existing native bench adapter; retain and regress |
| Shop guard | 2 | Existing native adapter; retain and regress |
| Blacksmith | 1 | Heating/forging adapter; source tempering/cooperation still separate |
| Bartender | 1 | Sweeping is partial; orders, wiping and closing still require conversion |
| Coal seller controller | 1 | Existing source station adapter |
| Horse handler | 1 | Hay unloading adapter; animation correction awaiting playtest |
| Dice controller | 1 | Source controller needs its own dependency/interaction audit |
| Missing ordinary source activity links | 9 | Trace quest-controlled activities before assigning invented work |

The nine unresolved daycycle records are `ska_fricek`, `ska_matus`, `ska_matej`,
`ska_ales`, `ska_zbysek`, `ska_bailiff`, `ska_havel`, `ska_masterSmelter` and
`ska_pipek`. Their names select audit subjects, never conversion behavior.

Housework phases must be evaluated from the source gender branch. Female source
work contains cooking, sweeping, embroidery, bucket filling and hanging out;
male source work contains fire tending, fence repair, bucket filling, hanging
out and chopping. Some bounded phases already have adapters. Do not count every
houseworker as fully converted merely because one supported phase runs.

## Household extension and repeat-upgrade audit — 22 October 2026

The population builder now includes existing native sweeping jobs when finding
household routines to extend. Previously those women were excluded by a filter
which accepted only pending arrivals and scheduler hubs.

`character_household_work.py` adds source-linked native choices through the
reusable `character_work_pool.py` binder:

- Cooking uses the converted fireplace belonging to the source home's furnace.
  The exclusive native cooking resource, completion action and remapped native
  fireplace scheduler effects remain intact.
- Needlework uses the source home's table-free benches and the native embroidery
  override. The underlying seat remains a shared, exclusive resource.
- Home rest extends existing work pools with the source's indoor bench choices.
  Outdoor-priority homes still require the weather dispatcher; the upgrader does
  not silently substitute indoor rest for that policy.

The installed-town input produces seven cooking choices, seven needlework
choices and ten home-rest choices. These counts describe emitted assignments,
not observed animations. Selection follows source programs, gender branches and
area links; there are no resident-name or world-coordinate exceptions.

The extension preserves existing work and quest activities and inherits the
actor's current work clock. Sleep remains authoritative. The city-walk, fence,
rest and wood-chopping adapters now accept a source work window shortened by a
validated generated sleep pool. Other clock changes still fail validation.
City and chopping alternatives retain their original windows behind the clipped
actor edge, avoiding duplicate overlapping choices on repeat upgrades.

This is integrated in the population setup path and desktop module inventory.
It is **not full source-controller equivalence**: native scheduler choices do
not yet implement the original ordered chore cycle or its phase durations.
Bucket carrying, the full fireplace-refill cycle, dynamic guard allocation,
bartender orders/cleaning/closing, dice-controller interactions, remaining stable
phases, blacksmith cooperation/tempering and weather-dependent branches remain
unfinished. Quest-controlled actors with no ordinary activity link must retain
their quest controller rather than receive an invented occupation.

Private offline evidence is under `reports/jobs-completion/`. No game bridge or
computer controls were used for this pass. Runtime verification remains false;
the candidate must not be described as a completed town or a tested retail install.

Validation: the 55-person population setup path completed, its mounted and level
schedulers matched, and every scheduler target resolved. A second complete pass
left the mission, scheduler and waiting-link graphs semantically unchanged.
The regression suite ran 1,813 tests successfully with 17 skipped; the source
desktop process-pool self-test also passed. The work report remains incomplete
with nine top-level pending records, in addition to the partial phase reports.

## First candidate: field hoeing

`character_farmer_work.py` recognizes `final/sa_farm.xml:Farmer`. It resolves the
authored field endpoints and the actor's linked home hoe slots. Native KCD2
`so_field.hoeing` owns the hand-content decision, exact approach, hoeing movement
and cleanup. Native reservation links retain the authored tools. Workers sharing
the same field share exclusive row activities and their tool pool.

The current candidate derives six rows per field from the source geometry and
row-count definition. Rain-shelter selection remains explicitly pending. It is not a completed farming
controller or proof that every Skalitz job works.

The shared population setup path and desktop converter inventory include the
adapter. Existing non-baseline schedules cannot be replaced. The bounded test
builder preserves existing sleep windows when replacing an idle routine.

Candidate subjects: `ska_hans`, `ska_tonka_husband`, `ska_farmer1`, `ska_adam`,
`ska_woman24`, `ska_woman2`. They resolve to 24 shared row resources across four fields.

## Required live acceptance

1. Load the installed Skalitz save and inspect each worker through the modding
   bridge; record game time, position, activity/animation and tool state.
2. Observe autonomous hoe pickup, field approach and visible hoeing along the row.
3. Observe competing workers respecting the exclusive field/tool reservation.
4. Check dialogue interruption, tool cleanup and resumption.
5. Observe the work-to-sleep transition; check departure without a forced job.
6. Save/reload and check the same behavior again.
7. Record the tested package hashes and evidence, then commit and push the job.

The candidate was installed with rollback copies and launched through setup.
A protected native New Game entered `kcd1_travel`; all 270 snapshotted save files
were unchanged. Four workers acquired their reserved hoes and entered the native
forced-hoeing context. Workers traversed their authored first rows; the two other
workers sharing an occupied field remained idle. A controlled clock jump to
23:30 made the active workers leave their fields, while the two idle workers
entered `Lying`. This is partial diagnostic evidence, not full acceptance:
visible hoeing, tool return, all-worker rotation, interruption and reload remain
unverified. Henry was in the opening conversation menu; this is not evidence of a movement
regression. The game exited
during the subsequent diagnostic check; the cause is not established.
Private snapshots are in `reports/farmer-live-observations.json`.

A subsequent six-row candidate still showed four of six farmers working and two
idle. The user requested moving to the next job. Source changes are committed at
the user's request; that does not mark these partial observations as full runtime
verification.
The separately documented loft NPC navigation defect remains unresolved.
