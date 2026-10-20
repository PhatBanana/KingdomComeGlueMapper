# Native training conversion: implementation boundary

## Source exercise sequencing (current direction)

`campaign_training_exercises.py` resolves a bounded lesson from enabled source
objective transitions and explicit behavior registrations. It preserves whole
programs, variable scopes and source tree identities, and uses the quest
compiler's objective-port encoding for names beginning with digits. Numeric
sorting, disabled branches and native phase-number substitution are not used.
Branches, cycles, missing registrations and stale plans reject compilation.

`compile_exercises` invokes the ordinary behavior compiler and its dependency
closure. If any required exercise is withheld, no lesson files are returned;
the exception carries the full conversion diagnostics. `bind` schedules
dedicated workers from their source objective states and the host's active
state. Conflicting active exercise objectives disable all workers. Source
programs own completion through their compiled quest bridge; worker Success
and native tutorial phase events are not substituted for exercise completion.
The host must still supply the source controller scope, quest bridge and
cancellation/cleanup bindings. This API is not yet installed in setup.

The real source probe resolved movement -> normal attack -> stab -> combo ->
first block -> second block -> final showcase. Stamina and third block are
not in that enabled chain. It then correctly withheld the lesson: the legacy
player controls, melee event listeners, natural-combo listener, sweet-spot and
combat automation nodes still lack native adapters. Additional diagnostics
include monologue request ABI and tutorial Lua conversion. The isolated probe
also has no registered quest binding; that is a probe dependency, not proof of
a production quest registration defect. The diagnostic artifact is
`outputs/native-training-adapter/source-exercise-conversion.json`.

These changes implement source selection, scheduling linkage and the atomic
compilation boundary, **not playable exercise conversion**. No in-game result
has been established. KCD2's shipped Basic graph has no separate movement/stab
phases; its perfect-block phase cannot replace the source's second ordinary
block exercise. Unsupported controls/listeners must be converted before the
lesson can be published, rather than emitted as legacy XML or fake successes.

The earlier native-lesson path uses KCD2's `CombatTutorialNode`; it remains
available for lessons with matching semantics, but is not a faithful substitute
for this source exercise chain. The source quest still owns its actor, place,
equipment, dialogue and completion objective.
No generated training module selects Vanyek or a specific quest by name.

## Implemented

- `campaign_training_plan.py` extracts guarded arrival and paired borrowed-item
  lifetimes from source programs. Unsupported branches fail conversion rather
  than being flattened or silently dropped.
- `campaign_native_training.py` checks the controller's input/output contract
  against installed production quest graphs.
- `campaign_training_runtime.py` emits an acknowledged lifecycle: arrival,
  preparation, readiness, tutorial, worker shutdown, cleanup and completion.
  An individual hit or skipped phase cannot complete the quest. Only native
  tutorial completion followed by acknowledged cleanup emits `finished`.
- Instruction acknowledgements carry the expected native phase, are accepted
  once per phase, and require dialogue to have released control.
- Cancellation, preparation failure and lost readiness stop training and retain
  the cleanup obligation. Cleanup failure can be retried without advancing the
  quest. Requests during cleanup are ignored.
- `campaign_training_readiness.py` emits the native action-wait/readiness context
  worker. Its executable Root was compared structurally with the shipped Basic
  tutorial worker in `AI/quests/prepadeni/prepadeni.xml` and matches exactly.
- `campaign_training_equipment.py` lowers both source equipment callbacks with
  the existing `BehaviorCompiler` and dependency importer. It preserves OnInit
  searches, operation order, owners and exact item handles. Shared handle
  declarations become persistent using the existing type adapter (including
  source `common:wuid` associative maps). Missing resources or unsupported
  restoration operations reject the pair. Behavior completion/failure uses the
  native `resultNotification` callbacks.
- `campaign_training_controller.py` binds explicit imported call sites inside
  one existing controller. It inlines the equipment programs into that scope,
  promotes shared handle persistence, rejects incompatible variable collisions,
  and includes callback initialization inside its failure-reporting wrapper.
  Its generated event set retains existing controller callbacks. A separate
  binding function connects the phase acknowledgements to the lifecycle.
- `campaign_training_bundle.py` requires the normal dependency importer and
  returns the converted controller, event registration and dependency files
  together. Missing dependencies or ambiguous call sites abort assembly.
- `campaign_training_sources.py` resolves the controller's static smart-object
  behavior calls through authored registrations. Public behavior tags need not
  match tree names. Equipment pairing follows exact CreateItem/RemoveItem handle
  lifetimes; duplicate sites, missing registrations and incompatible scopes are
  rejected. Only referenced controller variables become equipment dependencies.
  `assemble_from_source` connects this resolution to equipment assembly and
  supports native CallBehavior call sites as well as the earlier IncludeTree
  fixture. Cross-document callbacks are rejected until their separate compiler
  document scopes are supported.

## Host contract still to implement

The scheduling and dialogue binding APIs are now implemented in
`campaign_training_schedule.py` and `campaign_training_dialogue.py`. Scheduling
requires validated compiled quest ports and an invocation-scoped arrival worker.
Arrival and lesson authorization are separate: inspection of the source showed
different objective-start messages for travelling to the arena and beginning
training. The lifecycle now waits at the destination until authorized, in either
event order. Repeated unrelated quest changes do not repeat the arrival request.

Dialogue binding requires explicit imported scenes for every native phase. The
phase extractor reads the shipped tutorial's phase switch, progress-state
acknowledgements and CustomStepEvent edges. The installed Basic example has
seven phases; only phases 0, 1, 2 and 6 use CustomStepEvent. Scene releases are
guarded by active training, expected phase and a pending invocation; cancellation
clears pending releases. Callers must provide invocation-scoped scene instances.
KCD1 movement/stab exercise numbering is not a native phase mapping. The actual
source dialogue mapping has not been resolved or installed.

The lifecycle is not yet installed or wired into setup. A host must bind the
source destination and routine, select the controller's source call sites,
connect its scheduling to the lifecycle and run cleanup there.
Installing the two callbacks as independent trees with copied variables is
incorrect: they must see the same created item instances. The controller binder
moves callback initialization into the invocation's failure-reporting wrapper;
the standalone equipment roots alone do not catch Root OnInit failures.
It must stop all workers before acknowledging `workers_stopped`: after that
acknowledgement, the previous invocation cannot create items or send callbacks.
Callbacks must be scoped to the active invocation; the graph alone cannot
identify an old callback arriving during a later invocation of the same phase.

The host must also connect native phase-specific instruction dialogue and
acknowledgements, and route `finished` into the source quest's completion path.
Do not substitute the entire native training-ground manager: it owns additional
fight transitions, and its equipment helper does not expose preparation/cleanup
acknowledgements required by this lifecycle.

## Validation

Graph simulator regressions cover ordering, duplicate requests, phase-scoped
acknowledgements, cancellation, failure, retry, and restored state during cleanup.
Restoring simulator state is not evidence of engine save/load behavior.
The readiness worker passed the shipped AI operation/attribute schema validator.
The lifecycle was emitted using the installed native Basic tutorial contract.

No in-game lesson, equipment restoration or save/load test has passed yet.
These files must not be advertised as a working setup lesson until those host
bindings and runtime checks are complete.

The equipment adapter's structural fixture passed validation against installed
native AI schemas and the resultNotification event contract. Its item identity
was synthetic; that check does not establish a real item registration. Running
the actual source lesson without a dependency importer correctly rejected its
unconverted sword, protection buffs and player draw message. The production
caller must supply the existing importer, not identity-map those resources.

The combined controller fixture also passed installed native operation/schema
validation. Tests cover preservation of controller sequencing and existing
events, shared handles, dependency inclusion, unresolved imports, variable
collisions, missing call sites, initialization failure placement and duplicate
acknowledgement wiring. These are structural tests, not engine execution.

Source resolution was exercised against the installed KCD1 controller tables
and the imported sword-training IR. It found the authored preparation/cleanup
registrations without a named-quest selector. A bounded dependency probe using
the real buff and AI structure adapters converted both protection buffs and the
draw-weapon message. The probe omitted asset, text and enum adapters and stopped
on those dependencies; this is not a full production importer failure or a
successful complete lesson build. Real controller scheduling, native phase
dialogue mapping and in-game validation remain outstanding.
