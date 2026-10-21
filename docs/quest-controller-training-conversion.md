# Generic quest-controlled routines and fencing integration

Status (2026-10-21): generic request-consumer implementation and structural
validation, **not a playable lesson**. No game files were installed or game
process launched for this stage.

Subsequent curriculum decision (2026-10-21): the user selected the complete
native KCD2 Basic lesson and deferred temporary factions. The source-faithful
exercise and faction limitations recorded below are historical audit findings,
not prerequisites for that selected curriculum. The native lesson assembly,
speech/facial resources and current remaining host integration are documented
in [native-training-upgrader.md](native-training-upgrader.md).

## Execution model

Convert the source quest controller together with its registered callbacks,
actor/place links, dialogue dependencies and scheduler requests. The unit of
conversion is a controller-owned routine, not an NPC name or a spawn coordinate.

For the fencing fixture, the source path is:

1. Opening quest starts `practiceFencing`; the child quest starts after its
   profile and reference gates are satisfied.
2. Its quest-start handler requests the tutor's introductory job, a lower
   priority waiting job and the companion's job.
3. The intro job resolves the relocation and sitting places. Its persistent
   first-entry guard surrounds perception changes, temporary civilian status
   and relocation. Sitting and the proximity/dialogue-gated bark then run in
   the original parallel subtree.
4. Invitation advances the arrival objective and requests the walking job.
   That job walks to the arena waiting place, completes the arrival objective,
   then continues using the leaning place.
5. A separate authorization objective starts preparation and the lesson.
   Practice item handles belong to one shared controller scope across
   preparation, exercises and cleanup. Source objectives own advancement.
6. Completion/cancellation stops workers, restores equipment and protection,
   then follows the source handoff and subsequent jobs.

These names identify the fixture. Generic conversion derives them from source
registrations, links and transitions. The intro, seat and arena are distinct.

## Native activity leases

Each resolved `daycycle:change` handle needs a controller-owned activity lease:

| Source requirement | Native conversion responsibility |
| --- | --- |
| Actor and sourceId | Bind executing soul separately from owning smart entity. Callback `this` and `__object` are not interchangeable. |
| Public behavior tag | Resolve registration file/tree; retain the tag even when it differs from the implementation name. |
| Priority/immediate | Emit compiled actor activity and positioning delegate using source policy. EnableBehavior alone creates no activity. |
| Add/remove handle | Persist availability per controller, actor and handle; remove only that lease. |
| Once/completion policy | Retire requests from scoped callbacks according to source policy; do not resubmit on every state notification. |
| Guards and phase variables | Preserve branches, order, parallel execution and persistence. Do not flatten initialization. |
| Omitted fields | Resolve defaults from the installed source type declaration, not guessed defaults. |
| Cancellation/save-load | Acknowledge stopped workers before cleanup; reconcile leases without replaying initialization or accepting old callbacks. |

Use `campaign_behavior_schedule.connect` for compiled activities and the quest
bridge for objective state. `campaign_schedule_lifecycle.ScheduleAdapter` now
lowers bound requests at their original guarded source sites and emits the
native consumer, persistent state, worker wrappers and release callback.

### Native route assembly and request consumer

`campaign_schedule_routes.plan` now groups additions/removals by resolved actor
and source handle. It retains each request's original tree, AST path, guards,
operation and arguments. Actor bindings are keyed by document, tree and source
expression: a worker's `this.id` is not the controller's `this.id`. Other quests
present in the import's library set are excluded from the default selection.
Policy changes for a reused handle, unresolved actors, missing additions and
unconverted requests block the plan.

`campaign_schedule_routes.assemble` now produces a candidate world, compiled
scheduler, controller template and waiting-link additions together. It:

- Requires a completely converted callback, matching native registration, and
  an actual emitted behavior file containing that tree.
- Adds a separate disabled behavior alias and compiled activity for each
  actor/handle. Two handles using the same callback have independent availability.
- Keeps callbacks on the original smart entity, preserving controller identity,
  brain, inboxes, instance limits and existing callback registrations.
- Preserves existing actor jobs and does not force character simulation LOD.
- Requires an explicit native priority/urgency mapping with evidence. It does
  not infer `Instant` from source `immediate(true)`.
- Works on copies, so even a failure on the last route cannot partially update
  the caller's world or scheduler. The lower-level `connect` exporter was also
  corrected to validate its activity template and identity collisions before
  adding anchors or empty link containers.

With the matching lifecycle adapter supplied, assembly now returns executable
request handling together with its cloned controller brain and mailbox tables.
Routes are initially disabled; their actual guarded source additions enable
them. The compiler still rejects raw daycycle messages without a bound adapter.

`compile_program` connects source planning, behavior compilation and lifecycle
assembly in one call. It refuses to return a controller if any registered entry
program or callback was withheld. It returns quest bridge files and wiring
metadata along with the world, compiled activities, template and waiting links;
the caller must package and wire those together. It is not called by setup yet.

The generated consumer blocks on a native mailbox rather than polling NPCs.
Each actor/handle has persistent wanted/draining/generation/actor state. A
replacement disables its previous alias and waits for the native SmartObject
`onRelease` callback with `__behaviors[alias].count == 0`. Worker completion is
separate: a synchronous message carries the generation obtained before entering
the complete source Root. A once result sets NoRequests while its worker exits.
Old results cannot consume a replacement, and unrelated preemption invalidates
the old generation without consuming the once request. Removal during pending
replacement wins. Original controller variables, inboxes and callbacks remain
registered; actor brains and simulation LOD are not changed.

This is generated control flow, **not runtime-confirmed semantics**. Native
ladder onRelease/count logic and native synchronous OnProcessed messages provide
the underlying contracts. Live tests still need to establish Disabled/NoRequests
unwind timing and source-equivalent immediate preemption, especially a new
different handle at equal priority. The consumer currently changes availability;
it does not implement a separate ForceKick/interrupt dispatch. A successful
same-handle simulator replacement does not establish that cross-handle behavior.
Non-immediate requests, synchronous source requests and changing policy for a
reused handle remain explicit conversion errors. The package remains
`publication_ready: false` and has not been installed.

The installed KCD1 `Libs/AI/TypeDefinitions.xml` declares distinct `immediate`
and `immediateDaycycleHaltSpeed` members; the latter explicitly defaults to
`$enum:daycycleHaltSpeed.slow`. `final/sb_daycycles.xml` also uses `ignoreDuplicit`
to decide whether an immediate repeated request interrupts the current job.
Consequently, a boolean availability latch alone does not reproduce every
source request. KCD2's `resultNotification` EventSet declares only Success and
Fail; it does not establish a stopped/cleanup acknowledgement. Neither a timer
nor a fabricated success event has been substituted for those missing contracts.

Validation: 603 campaign tests passed, including 20 consumer/program tests.
These execute generated control flow with explicit simulated acquire/release
events, covering stale completion, unrelated preemption, repeated replacement,
removal, restored pending state, independent handles, preserved registrations,
path-backed resources and atomic rejection of an incomplete controller. Engine
save/load and scheduler behavior are not simulated by those tests. A synthetic
controller also passed emission against the installed KCD2 AI table schemas and
generated operation/attribute validation against its executable XML catalog.

## Corrections implemented in this audit

- `campaign_schedule_requests.py` discovers add/remove requests in executable
  trees, retains ancestor guards and resolves registered callbacks. Unsupported
  policies remain explicit. Omitted `once` now uses the source boolean default
  false; explicit priority and immediate are still required. It never executes
  a flattened list.
- `campaign_behavior.py` includes those callbacks in dependency closure and
  rejects raw daycycle messages even when their types are registered. It now
  follows controller-local CallBehavior dependencies too: a failed registered
  worker withholds its caller.
- `campaign_behavior_contracts.py` supports native perception enable/disable
  operations, preserving source targets and order. The installed runtime catalog
  must confirm each operation and attribute.
- `campaign_training_schedule.bind(..., arrival_completion='source_objective')`
  accepts the arrival objective's Completed state instead of waiting for the
  walk-and-lean worker to return Success. It preserves the waiting pose until
  preparation or shutdown, delivers arrival once and avoids duplicate objective
  writes. Walking failure reports arrival failure; later waiting-pose failure
  cancels the session. Finite workers retain their worker-success mode.

The production host must explicitly select the new arrival contract. Adding
this API alone does not connect the installed quest.

## Remaining adapters and integration

### Temporary faction adapter

`campaign_temporary_factions.FactionBridge` now converts explicit source
activation, explicit clearing, persistent combat-clear protection and the
source target-selection clearing guard. The shared behavior compiler accepts
it through `faction_adapter`; `compile_program` passes it through and returns
the generated module and wiring with the other controller resources.

The implementation has no quest names, actor names, coordinates or special
fencing branches. Actor bindings are scoped by owner, source document, tree and
expression and must resolve to converted **SharedSoulGuids**, not placed-entity
WUIDs. Source superfaction names resolve through the source superfaction table
to registered `gluemapper_kcd1_superfaction_<id>` groups. They must not be
resolved using the separate, overlapping source faction-ID domain.

Each soul has one logical override slot. Setting a different faction clears
the previous slot and activates the selected native `TemporaryFactionEffect`.
Explicit clearing deactivates the effects even while combat-clear protection
is active. It does not write the permanent faction or restore a stale snapshot
of that faction. Native removal of the effect is intended to expose the current
underlying faction; that behavior and replacement notification ordering still
need engine validation.

The exact source rule in `Libs/AI/final/sb_combat_fight.xml`,
`fight_setTarget/OnInit`, clears before target assignment only when all three
conditions hold:

1. The selected target is `__player`.
2. The request's `clearTempSuperfactionAgainstPlayer` option is true.
3. No context handle holds
   `suppressTempSuperfactionClearingInCombatVersusDude`.

The installed source `combat:fightOptions` declaration defaults that request
option to **false**. The adapter retains the opponent and option expressions at
their original AI site and evaluates suppression in the shared effect module.
It does not invent a clear on combat start/end, damage, cancellation or lesson
completion. An altered/unrecognized context condition withholds the containing
tree, including when no faction adapter was provided.

Persistent source `Contexts.SetPersistentOption` and `Contexts.ClearOption`
calls become separate persistent boolean states for each soul/handle. Clearing
one handle leaves protection from other handles active. Clearing a faction
does not clear its protection handles. All source writers for a soul must use
one shared bridge, including cross-quest writers; separate controller-local
bridges would incorrectly create independent override slots.

This matters in the actual fencing source: `q_tutorial_swordOne` sets civilian
status and its protection handle, but `q_skalitz/cutscene_navsteva_racka` clears
that handle later. Automatically removing protection at lesson completion
would change the source. The real-source probe lowered those four authored
sites plus the combat guard, resolving Civilians to source group 3 and Vanyek
to shared soul `464c0078-2566-4391-4143-2659b8406689`. Its generated-graph
simulation passed activation, protected clearing, cross-quest protection
release and subsequent unprotected clearing. Evidence and generated files are
under `outputs/temporary-faction-audit/`; bindings in this probe are explicit,
not evidence of production controller binding integration.

Native format evidence is the production module
`Quests/Final/Barbora/klaster/klaster_hibernate_mode/npc_modifikace.xml`, with
`TemporaryFactionEffect` driven by `IsActive`, a `Souls` asset and a constant
`Faction`. The adapter requires that contract and the registered target groups.
This establishes an emission contract, not runtime equivalence.

**Remaining integration:** KCD2's native combat controller does not automatically
execute the translated KCD1 `fight_setTarget` tree. The complete source caller
or an evidenced native target-selection hook must be connected. Production
actor resolution must supply all scoped soul bindings across quest owners.
The generated context state preserves effective protection but does not
reproduce source Lua assertions for duplicate handle activation or clearing an
absent handle. Save/load tests copy simulated State values; native persistence,
effect teardown and notification ordering still require in-game tests. The
adapter therefore reports `runtime_validated: false`; setup remains unchanged
and no game package was installed for this stage.

Validation: 12 dedicated regression tests cover replacement, explicit clearing,
the guarded combat clear, independent protection handles and souls, simulated
state restoration, scoped references, rejection of unknown contracts/context
uses and project module wiring. The full campaign suite passes 620 tests.

Follow-up validation (2026-10-21): a new combined generic-controller test calls
`compile_program` with both scheduling and faction adapters. It checks native
consumer registration, signal-table/effect-module inclusion, project wiring,
worker-scoped soul identity, preservation of the authored OnSuccess cleanup
and unchanged input world/scheduler/template. The lifecycle test module also
now runs independently instead of relying on another test to add `tools` to
the Python import path. All **621 campaign tests and 89 setup tests passed**;
the 12 faction cases are included in the campaign count. Logs and enumerated
test IDs are under `outputs/temporary-faction-validation/`.

The same follow-up ran a fresh compiler diagnostic on the fencing source with
the schedule and faction adapters supplied. It resolves six schedule leases,
but emits only one of 21 registered controller entries. This diagnostic uses
explicit fixture bindings and no complete dependency importer, so its missing
resource/type registrations are not proof of importer defects. Confirmed
remaining semantic adapters include ProfileLoadedGate, monologue priority,
PlayerCombatControls and exercise listeners. Its readiness receipt records
`ready_for_game_test: false`, `installed: false`, `runtime_validated: false`.
The successful generic fixture is not an installable fencing package.

### Other controller adapters

**Intro dialogue:** native `AI/speech/sb_dialog.xml` supports alias/look-at
requests. The source intro adds `priority(1)`, which still needs semantic
conversion. Import actual bark/audio dependencies, the invitation scene and the
companion callback chain. Do not simply discard the priority field.

**Walk and waiting:** import linked places and native seat/lean hosts, bind
compiled activities, and use source-objective arrival. Validate controller scope
and the actual route. Do not replace walking with a teleport.

**Exercises:** movement, stab and the second ordinary block are not a one-to-one
mapping to KCD2 Basic phases. Use native tutorial phases only where equivalence
is established; otherwise convert source controls/listeners and success
predicates. Do not generate success messages to skip missing exercises.

The shared behavior compiler now lowers supported sustained combat leaves via
`campaign_combat_automation.py`. Defense/offense controls become their native
`*AutomationDecorator` with `active=true`. Explicit guard modes Automate,
ForceEnable and FreeBlock map to the corresponding native enum spelling. Weapon
automation currently accepts only explicit `WeaponChange=none` with
`noAnimation=false`; animated weapon transitions require a separate contract.
Each decorator owns a native indefinite Wait. This preserves its running
branch in the source Parallel instead of allowing a synthetic Success to end
the exercise immediately. Parent guards, timers and cleanup remain in place.
The compiler requires the operation, fields and values to be present in the
installed game's executable XML. Omitted guard modes are not guessed.

Native evidence includes `AI/animal/basic/switch/interrupt_animal_attack.xml`,
`AI/battle/battleLadderController.xml` and `AI/battles/battlegroupcontroller.xml`.
The current source audit converts 38 such calls across the quest and imported
helper libraries. This removes individual unsupported operations, **not whole
controller blockers**: the full-model before/after comparison still emits 199
complete trees, with no additional complete tree yet. PlayerCombatControls,
exercise listeners, priority speech and temporary faction integration still prevent
the lesson from compiling. Evidence is saved under
`outputs/general-controller-adapters/`. All 608 campaign tests pass, including
five regression tests covering preserved parent structure, indefinite lifetime,
unknown modes/fields, missing native evidence and whole-exercise rejection.
These tests do not establish engine execution or cancellation behavior. No
installation or setup activation was performed for this partial conversion.

**Setup:** assemble the child quest, host, actors/places, invitation/barks,
exercises and cleanup as one validated package. The earlier starting-layout
adapter alone does not implement the controller.

## Evidence and acceptance

Read-only probe: `outputs/fencing-controller-audit/source-ir.json` and
`compiler-audit.json`. It resolves installed source registrations and finds
seven schedule-change sites in onUpdate plus the intro removal site. One
companion addition omits `once`; that source default is now resolved. A fresh
probe in `outputs/schedule-lifecycle-audit/fencing-readiness.json` resolves all
eight sites into six actor/handle routes. The real controller still fails full
conversion; faction integration, intro dialogue and exercise conversion remain
incomplete.
The probe deliberately has no dependency importer: missing type/link/item
registrations in its report are not evidence those importers are broken.

Native evidence came from installed KCD2 Scripts.pak runtime AI Roots and
Quests/Final production graphs. Perception examples include
`AI/animal/basic/switch/animal_state_dead.xml` and
`AI/animal/basic/switch/switch.xml`. Source trees and faction examples are saved
alongside the probe.

Tests cover registered messages without consumers, missing callbacks, public
tag resolution, guarded add/remove requests, policy validation, perception order,
and arrival while the waiting worker continues. Graph simulation covers
cancellation, late notifications, waiting-pose failure and missing quest ports.

Runtime acceptance needs a setup-launched new game: intro relocation once,
sitting/bark, invitation, actual walk, arrival while leaning, authorized practice
equipment, all required exercises, cleanup and handoff. Repeat across save/load
and cancellation, and confirm unrelated NPC schedules remain active. These
checks have not been run; compiler and simulator tests do not establish them.
