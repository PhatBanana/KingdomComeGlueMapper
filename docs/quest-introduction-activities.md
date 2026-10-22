# Source introductory sitting and speech

The selected `q_tutorial_swordOne/vanek_idle` introduction now has a native
worker and compiled actor scheduler entry. Previously only Vanyek's initial
relocation was materialized; neither the sitting activity nor bark was installed.

`campaign_intro_activity.py` recognizes the selected source parallel activity,
resolves its actor/place roles, and preserves priority, halt urgency, proximity
hysteresis and the not-in-dialogue condition. Other actor names, place names,
bark aliases and distances use the same adapter. Unsupported branch shapes
fail conversion. Editor forest copies are excluded from executable-tree analysis.

`setup_quest_introductions.py` resolves source world transforms, supplies a native
ground-sit helper and its animation collection, creates a dedicated behavior host,
registers project assets and both authoring and compiled scheduler links, and
imports the original dialogue, voice and facial resources. It does not change
global NPC initialization or force animation clips. The worker preserves the
source's one-time relocation to its arrival marker, followed by native navigation
to the separate sitting spot.

For the selected introduction, the source relocation is at
`772.93317,3471.1392,52.499729`; the seat is at
`780.15918,3477.3896,51.2001`. Native stance navigation owns reaching the seat.
The activity uses priority 55 and Slow halt urgency. Its bark enters at 2 m and
leaves at 4 m, with the source infinite wait inside the gate. It has no polling
loop. Native `activity_disableSchedulerLooping` keeps `so_sitPlace/use` from
ending its routine after the normal 15-second scheduler interval.

The bounded introduction is available while the source parent quest and
`practiceFencing` objective are active. Request retirement follows the explicit
source removal callbacks: this source removes the request on Success only.
Recoverable failure must not permanently retire it. The invitation now supplies
the departure handoff described below. No complete combat-lesson conversion is
claimed here.

Clean setup includes the `quest-introductions` stage. Recipe 40 and transactional
package migration use the same builder; a completed introduction is validated
and reused on resume. A targeted retail installation retains the existing full
recipe version instead of falsely relabelling it as a complete recipe-39 build.

Validation performed on 2026-10-21:

- Campaign suite: 644 tests passed before the additional migration-order test.
- Intro suite: five tests, including generic roles/distances, native work
  delegation, no replay loop, editor-copy exclusion and changed-contract rejection.
- Package migration suite: 17 passed. Build recipe suite: nine passed.
- Actual source/native build: native operation schemas, monologue ABI, compiled
  scheduler targets, helper registration, archive CRC and duplicate paths checked.
- Archive comparison: no entries removed; changed level members are mission,
  scheduler, waiting links and the two animation-helper tables.
- Targeted package: `outputs/intro-activity-20261021-a`. Six files installed with
  backups under its `backup` directory; retail launched through `setup_launch.py`.

Runtime sitting, proximity speech and save/load continuation still require
observation. Successful loading or actor registration alone does not verify them.
The native lesson, invitation and walking handoff are separate stages.

## Failed playtest and destination registration repair

The following retail playtest left Vanyek standing near the arrival point, with
no Talk prompt. This disproves runtime completion of the introduction. His
initialization log succeeds, but does not establish that the worker started.

The compiled export registered the behavior host but omitted the called seat's
`C_SmartHub` destination. All 180 native Trosky ground-sitting placements have
that registration. The generic destination exporter now registers the seat too;
package validation rejects its absence. Existing introduction packages receive
the same bounded, idempotent repair through `upgrade`, without rebuilding speech
or changing actor initialization, transforms, or unrelated schedules.

`outputs/intro-seat-scheduler-20261021-b` contains the targeted correction and
installation backup. Only `tables/ai/scheduler.xml` changes in `level.pak`, adding
one leaf row. Seven introduction tests, four behavior-schedule tests and 17
package-migration tests pass. The real-package upgrade was applied twice to
verify idempotency and all unchanged archive members were compared byte for byte.

This corrects a confirmed structural omission; it is not yet runtime proof that
the activity starts or reaches the sitting position. The absent Talk interaction
also remains: importing an in-game bark does not import the invitation dialogue.

## Temporary faction integration

`campaign_intro_factions.py` now recognizes the source controller's profile-gated
faction assignment, the matching first-entry worker assignment and its persistent
protection against source player-combat clearing. Actor role, faction name,
profile and parent quest come from the source. Dynamic targets, extra faction
writers, explicit clears and different protection lifecycles are rejected rather
than silently flattened. The general `FactionBridge` remains available for those
more complex source programs.

The selected controller sets `Civilians`, resolved through the retail source
superfaction table to registered `gluemapper_kcd1_superfaction_3`. A native
`TemporaryFactionEffect` binds to the existing actor asset. Its contract is
verified against the shipped `klaster_hibernate_mode/npc_modifikace.xml` graph.
No permanent soul faction or faction relations are rewritten.

The current converted slice uses the parent quest's active lifetime for the
effect. It is therefore active before the `practiceFencing` activity is requested,
survives worker completion/failure and releases when the parent quest leaves
Active. Native effect removal exposes the current underlying faction instead of
restoring a potentially stale faction snapshot. Native quest persistence owns
save/load state. This is an explicit bounded mapping: the source controller has
a profile-loaded / parent-not-completed guard, and contains no explicit faction
clear. It is not a claim that the complete source controller/profile lifecycle
or its global combat-selection code has been translated.

Existing introduction packages are migrated by adding the effect to their entry
graph and updating the introduction receipt. Clean setup uses the same resolver
and emitter. No speech, meshes, navigation, placement or AI initialization is
changed by this migration. `outputs/intro-factions-20261021-a` records the exact
targeted archive difference and native/source provenance. Automated graph tests
cover generic names, scope release, worker/combat callback independence,
idempotency, conflict rejection and rejection of unconverted source lifecycles.
Runtime friendliness, sitting/bark execution and engine save/load still need an
in-game test; the change does not supply the invitation conversation.

Validation for the faction update: 652 campaign tests, 17 package migration tests
and nine recipe tests passed. A fresh introduction build from the pre-introduction
package and current retail source/native archives passed validation at
`outputs/intro-factions-clean-20261021-b`. Its emitted faction effect matches the
targeted migration exactly. The targeted update was installed in retail while
the game was closed, with backups and hashes in
`outputs/intro-factions-20261021-a/installation.json`. The full installed recipe
version is retained; this does not label an older package as a full recipe-39
build. No runtime result is claimed.

## Delayed startup: missing worker initializer

The subsequent retail observation first found Vanyek at approximately
`651.10,3492.43,63.74`, around 130 metres from the source seat. His faction was
already `gluemapper_kcd1_superfaction_3`, with no reported combat danger, but
dialogue was restricted. Later snapshots found him at the source seat with
`SittingIdle` and dialogue unrestricted. The user reports that movement began
when the inspection bridge/Lua calls were used, after Mother had already been
spoken to. These observations **do not establish the cause of the initial
stall**. Attaching a native inspection hook is not a controlled no-intervention
test, even though the dispatched scripts contained getters rather than movement
or behavior commands. The bridge source has no automatic activity-start command.

Code comparison nevertheless confirms a missing source operation: the generated
worker had no `OnInit`. `setup_quest_starts` moved the actor at world construction,
but the original `vanek_idle` also relocates him when that worker first starts,
inside the persistent `p_phase < 10` guard. Map placement cannot substitute for
that operation if an actor has moved before the quest activity is selected.

`campaign_intro_initialization.py` now recognizes this source operation sequence,
resolves the arrival role separately from the sitting role, and emits native
`GetSpatialInfo` / `SetSpatialInfo` with balanced perception disable/enable and
the source persistent phase. It resolves the destination before disabling
perception. The existing scoped faction effect still owns the faction; no
unsupported KCD1 faction API is emitted. The actor returns to the authored arrival
marker on first worker entry only, then the native sitting action navigates to
the seat. This is not a periodic position correction or a teleport to the seat.
Subsequent worker entries with the saved phase do not relocate the actor.

Clean build and package migration bind the same arrival marker/parameter and
validate the worker. Migration preserves unrelated archive members and refuses
conflicting marker placements. Two native `LogToConsole` Info messages record
worker entry and completion of first-entry placement, with no timer or polling
loop. They permit a fresh test without attaching the inspection bridge.

The staged correction is `outputs/intro-initialization-20261021-a/package`.
Automated validation passed: 656 campaign tests, 17 package migration tests and
nine build-recipe tests (682 total). A fresh introduction build also validated at
`outputs/intro-initialization-clean-20261021-a/package`. Applying the targeted
migration twice produces no changes on its second pass; both changed archives
pass CRC checks and retain their original member sets.
Its `validation.json` lists exact changed members and hashes. Runtime acceptance
requires a fresh launch through setup, no MCP attachment, then observing the
arrival and sitting sequence and these log messages. The gate detour, native
save/load behavior, and invitation conversation are not claimed fixed by the
structural correction.

### Initializer test regression: incorrect project asset type

The first initializer test was rejected by the user: quests did not initialize.
The startup log contains actor initialization but no introductory worker entry;
it does not provide an explicit quest-parser diagnostic. Inspection found that
the new project asset was emitted as `EntityAsset`, whereas the existing generic
binding registry and native KCD2 quest documents use `TagPointAsset` for TagPoint
entities (3,458 declarations in the inspected native Scripts.pak, no EntityAsset
declarations). This invalid shared-project declaration is a concrete regression;
runtime recovery must still be verified rather than inferred from its repair.

The initializer now uses `campaign_bindings.ENTITY_ASSETS` and validates that
type. Migration repairs the unreleased generic declaration only after checking
the arrival marker identity, class and pose. A regression test rejects the bad
declaration and verifies idempotent migration. The corrected staged package at
`outputs/intro-initialization-20261021-b/package` changes only that declaration
in `Quests/GlueTravel/GlueTravel_kcd1.xml` compared with the first test. All 17
introduction tests and 17 package-upgrade tests pass; archive CRC and repeated
migration checks pass. No runtime success is claimed here.

## Invitation and recoverable introduction repair — 23 October 2026

Recipe 51 adds the selected original invitation topic 20281 and the source
`vanek_walksToTiltyard` departure to clean setup and transactional upgrades.
The dialogue adapter imports the source lines, voices, conditions and objective
effects. Both invitation choices reach the source reply about waiting by the
sheepfold. The departure adapter derives actor/place roles, priority, movement
settings and the arrival objective from source XML. Unsupported changes fail
conversion rather than receiving a guessed actor, timer or position.

The trainer retains the source arrival and sitting locations above. The later
waiting point is `754.30408,3405.6086,61.858891`; native leaning alignment is
applied to that authored point. No two-hour delay is added or removed: this audit
has not established the runtime cause of the reported delay. The existing
source-scoped temporary faction remains in place.

The previous converted introduction permanently set its ended state on both
Success and Fail. The source has a removal callback only on Success. Existing
package graphs are migrated accordingly, so new recoverable failures do not
retire the request. An ended state already persisted by the old build cannot be
safely distinguished from legitimate completion and is not reset blindly.

Parent quest/objective state activates the child invitation quest. Its original
arrival objective switches availability from the introduction to departure.
The native Move's successful completion acknowledges arrival, followed by the
native destination's `use` behavior. Failure does not complete the objective.
The combat lesson, its later timer and rewards remain outside this slice.

Resource hashes and graph bindings are validated on repeat upgrades. Source and
native archive checks are offline evidence, not proof of an in-game Talk prompt,
movement, stance or save/load behavior. This change has not been live-tested.

The package audit also found metadata hardlinks being overwritten during
private staging. Introduction and start-placement receipts now use atomic
replacement. A separate setup failure compared city-walk XML indentation as
though it were a change to the native activity. That comparison now checks
structure and attributes while continuing to reject changed contracts/poses.

Validation on 23 October: 1,831 automated tests passed with 17 skips. A private
copy of the installed package passed gameplay content validation after the
source introduction, invitation and torch upgrades; repeating those stages
made no changes. The full transactional upgrade passed population, loft and
light stages but correctly rejected a pre-existing stale LOD encoding marker.
Its recorded HLOD hash differs from the installed data; the upgrade left those
HLOD bytes unchanged. This candidate is not certified for installation, and
no runtime behavior was verified. All 183 installed receipt entries remained
intact. The parents' separate navigation gap is recorded in parent-sleep-audit.md.
