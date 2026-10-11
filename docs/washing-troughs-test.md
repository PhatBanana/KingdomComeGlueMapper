# Native washing trough conversion

The normal Python world builder and `tools/build_washing_test.py` convert
KCD1 SequenceTriggers with the authored `@ui_use_wash` interaction. They follow
the trigger's explicit link to its tub rather than guessing from nearby meshes.

The installed test is `outputs/Washing/Build01`. It converts 274 troughs in
the currently active source layers. The report lists another 25 triggers in
inactive quest/alternate-state layers. Those are not force-enabled or counted
as converted; their owning world layers still require activation/conversion.

## Native contracts

- `WaterTubeActionTrigger` and its original dirt/blood eligibility checks,
  action distance, animation action and already-clean message.
- `SmartObjectHolder` with native `watertube` helper family and smart entity type.
- Native compiled scheduler effects, including `EffectClean` for `washFace`.
- Native animation collection plus runtime validation at each imported location.
- Native tub geometry `Objects/manmade/common_furniture/tubs/water_tub_a.cgf`.
  Its embedded `water_tub_clean` material includes the `Waterfall_layer2`
  submaterial using the `Waterfall` shader. The existing KCD1 visual is replaced
  in place, avoiding overlapping old/new water surfaces and collision.

Placement derives from the source `water_tube_1/washPoint` and native
`watertube/Place0` helper transforms. The trigger keeps its native transform
relative to that aligned owner. No native world-space animation bake is copied.

The shared KCD2 `AI/world/so_waterTube.xml` remains in control of the wash:
equipment removal/restoration, animation, save-lock cleanup, washing limits,
perk-dependent cleaning and associated effects. No substitute Lua cleaning
command or animation timer was added. Trosky household refill reservations
are not transplanted into Rattay's player wash stations.

Both the level archive and mod-qualified travel archive contain identical
scheduler and smart-object-animation tables. Existing bed, chair, bench and
leaning animation registrations are preserved.

## Validation and live test

Two washing regression tests cover complete local links, cleaning registration,
visual replacement, helper placement, preservation of existing records,
inactive-layer handling, duplicate rejection and missing dependency failures.
Existing activity-contract and region-travel tests also pass (17 tests total).
The actual package audit verified all 274 owner/effect records, local GUID links,
compiled scheduler targets and matching table copies. Installed PAK hashes
match the staged PAKs; backups are under `outputs/Washing/Build01/backup`.

The developer client is launched beside the inn-area tub at approximately
`2921.17,754.27,109.2`, source tub 53661. On 2026-10-12 the user confirmed
the installed washing conversion works and requested commit/push. This is a
live test of the installed build, not an individual test of all 274 troughs.
Approach the tub and use Wash when dirty. A fresh clean character may receive
the native already-clean response; the converter deliberately retains that
eligibility check. Verify the full animation finishes, dirt/blood decreases,
equipment returns, water looks correct, and movement/combat remains available.
