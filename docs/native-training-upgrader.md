# Native training conversion: implementation boundary

The controller integration design and 2026-10-21 audit are documented in
[quest-controller-training-conversion.md](quest-controller-training-conversion.md).
The source walk-and-wait routine requires `arrival_completion='source_objective'`;
waiting for its overall Success is not an arrival acknowledgement.

## Selected direction: complete native KCD2 Basic lesson

On 2026-10-21 the user explicitly selected KCD2's complete native Basic lesson
for combat exercises. Preserve KCD1's invitation, walk, practice equipment and
quest handoff. Temporary-faction conversion is deferred and is not a prerequisite
for this selected path. This is an intentional curriculum replacement, not a
claim that KCD1 movement/stab objectives equal KCD2 phase numbers.

`campaign_training_curriculum.py` resolves a selected production graph from the
installed target archive. It follows each Phase switch entry through the phase
module's output and state activation to the actual instruction dialogue and its
trigger. It validates the selected graph's own full controller contract rather
than merging evidence from unrelated examples. The emitted lifecycle uses that
complete native domain from phase zero; legacy exercise compilation is not called.

The installed Basic lesson resolves as follows:

| Native phase | Native instruction alias | CustomStepEvent |
| --- | --- | --- |
| 0 | combatTutorial_phase0_start | Yes |
| 1 | combatTutorial_phase1_start | Yes |
| 2 | combatTutorial_phase3_start | Yes |
| 3 | combatTutorial_phase4_start | No |
| 4 | combatTutorial_phase5_start | No |
| 5 | combatTutorial_phase6_start | No |
| 6 | combatTutorial_phase7_start | Yes |

Instruction bindings follow native document identity and authored trigger ports.
`campaign_training_presentation.py` preserves native alias dispatch; it does not
enqueue a second copy of the instruction. A CustomStep phase must emit its
authored cue and release the dialogue before the adapter acknowledges it. A
scene release without that cue cannot advance the lesson. Cancellation clears
pending cues, hides tutorial windows and blocks late objective/UI activation.
Native scene occupancy remains set until the actual scene-release callback;
stop/reset cannot falsely clear it and allow a new lesson to start while an old
instruction still owns the actors. That occupancy is combined with source
dialogue occupancy inside the assembled lifecycle.
Native `Tracker` is exposed alongside Phase and combat events; it was missing
from the previous wrapper even though native progress displays consume it.

The importer follows the actual seven phase modules, their progress states,
UI prompts, skip conditions, feedback barks and referenced quest objectives.
Phase-dependent native buffs and combat contexts require an explicit tutor or
player binding. Constant-only effects, unrelated story inputs and unrelated
local cycles are not treated as lesson effects. Five unreferenced crowd-only
dialogue documents are explicitly omitted for this selection; tutor/player
instructions and feedback cannot be omitted by that policy.

`campaign_training_native.assemble` connects the presentation to the acknowledged
lifecycle and imports the native combat tutorial settings with their three
namespaced combat helpers. It preserves their native post-combat grace periods.
Native exercise completion has a separate `exercises_finished` output, while
the source-facing `finished` still requires worker release and equipment cleanup.
Cancellation does not mark the native exercise objectives complete. Instruction
acknowledgements are internal to this assembled module rather than exposed as
an alternative way for the source to skip exercises.

`bind_resources` resolves audio folders through the actual instantiated Project /
Quest / Module hierarchy. It preserves native text and recorded voices, resolves
inherited voices using the target character table, and verifies OGG durations
against the shipped dubbing index. One shipped recording has a complete final
page without EOS; that opt-in is accepted only alongside matching native index
timing. The ordinary source OGG importer remains strict. English is the currently
implemented recording selection; this is not a multi-language media conversion.

The native recordings also require relocated facial lookup paths.
`dialogue_facials.NativeFacialImporter` retains the native rig, controllers and
curves, extends the current combined facial index, and retains earlier converted
dialogue entries. It does not run the KCD1 facial-rig remapping on native tracks.
Native instruction recordings remain the original Hans/Henry performances when
bound locally to Vanyek; this does not produce new Vanyek recordings or rewrite
native tutorial text that mentions Hans.

`campaign_training_exercises.py` remains available for explicit source-faithful
conversion elsewhere. Its unsupported legacy movement/stab listeners do not
block selection or emission of the complete native lesson. The replacement
adapter does not manufacture success for those legacy objectives.

**Integration boundary:** source arrival/controller scheduling and shared
equipment callbacks still need connection to this assembled native lesson in
the installed quest. The generated module explicitly exposes those inputs;
it does not fabricate acknowledgements. It is not yet a setup-installed,
playable fencing lesson. Do not install the emitted module by itself or claim
that the source controller has been replaced. The starting-placement adapter
is separate. Temporary factions and the superseded legacy exercise listeners
are not blockers for the selected native curriculum.

Validation: **640 campaign tests and 14 dialogue/audio/facial tests pass**,
including 71 training tests. The actual installed Basic lesson assembles into
33 XML documents, 19 tutor/player dialogue documents within that set, 93 native
OGG recordings and 26 relocated facial databases. The source inspection covers
39 native graph/phase/dialogue documents plus the four combat-settings helpers.
A rooted validation harness adds two XML documents, resolves the actual voice
namespace and checks local edges/definitions. The facial index retains all
295,556 native entries and adds 93 relocated entries. Regression tests also
cover preserving an already extended index and rebuilding a previously imported
facial namespace. Artifacts and source hashes are under
`outputs/native-basic-integration/assembled/`. The harness is structural evidence,
not the installed source quest: no in-game completion, cleanup or save/load
result has been established.

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

The earlier source-scene dialogue binding API requires explicit imported scenes for every native phase. The
phase extractor reads the shipped tutorial's phase switch, progress-state
acknowledgements and CustomStepEvent edges. The installed Basic example has
seven phases; only phases 0, 1, 2 and 6 use CustomStepEvent. Scene releases are
guarded by active training, expected phase and a pending invocation; cancellation
clears pending releases. Callers must provide invocation-scoped scene instances.
KCD1 movement/stab exercise numbering is not a native phase mapping. The selected
complete-native mode uses the presentation importer above instead of that
explicit scene-dispatch API. It preserves the native alias registrations and
uses the original native exercise instructions.

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

The assembled native module now owns phase-specific instruction dialogue and
acknowledgements. The host must route its `finished` into the source quest's completion path.
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
