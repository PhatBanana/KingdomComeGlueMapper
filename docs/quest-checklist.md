# Quest conversion checklist

Status: 14 October 2026. This tracks the original KCD1 campaign conversion into
KCD2. A checked implementation milestone means that specific capability exists;
it does not mark an entire quest complete. Development scene tests are separate
from the normal coach-travel installation route and published installers.

## Current work boundary: New Game to the start of the Skalitz attack

The user reconfirmed this boundary on 14 October. See
[opening dependency coverage](skalitz-dependency-coverage.md) for the current
source-profile and dialogue closure audit, importer corrections, and unresolved
actor/work-program dependencies. The broader profile rebuild is staged work;
it does not establish an installed, complete opening-to-attack quest.

The latest staged actor rebuild (`SkalitzProfileActors04`) resolves the ten
previous appearance failures: eight clothing coverage cases, nonvisual ring
equipment, and an explicit source CDF body fallback. It packages 48 new actors,
preserves eight existing quest/profile actors and has no pending appearance
failures. These are build checks; appearance, equipment and profile activation
still require in-game verification. The updated schedule planner resolves 46
intervals with no exceptions and retains 21 intervals needing quest-assigned
work or other link dependencies. Full routine execution remains unchecked.

### Camera command regression correction (14 October)

The automatic-cut update emitted `CameraType="Auto"`, which the target engine
rejects during FaderDialog deserialization. This prevented the enclosing
converted quest graph from loading, including Mother's opening. The importer
now preserves response speakers without inventing an automatic camera enum;
supported authored shot overrides remain intact. Explicit unsupported camera
commands still fail conversion.

The installed recovery removes 78 invalid commands across four dialogue files,
preserving all other package entries. Backup, failed-session log and hash receipt
are retained in `outputs/OpeningStart/CameraEnumRecovery01`. Validation: 261
campaign tests pass. The corrected game was launched for user testing; opening
recovery and automatic speaker-camera switching remain unverified in-game.
The subsequent crash occurred while loading Kuttenberg, not the converted
Skalitz level; its cause has not been established.

### Kenish quest-line focus (14 October)

The source actor is `ska_kunes`. The actor-scoped audit selects branches through
source soul/role membership within the opening quest closure, without matching
dialogue labels or embedding topic IDs in importer rules. Reproduce with
`tools/audit_actor_quest_dialogues.py`, supplying the source/target/mod paths,
quest IR, quest-scoped closure and `--soul-name`. The retained audit is
`outputs/OpeningStart/KenishAudit02/report.json`.

Thirteen branches are selected. Five emit XML; eight still fail conversion:
one requires area/context bindings, two require actor-identity predicates,
four require branch-type/reputation policies, and one references three missing
localized source responses. XML emission is not voice packaging, runtime
registration or a completed quest. Friend-assistance branches not owned by
this actor remain additional dependencies of the full quest line.

The generic dialogue condition importer now supports `IsActorInside` with
explicitly resolved context and area bindings. It emits the shipped native
`wh::rpgmodule::AreaCheck` contract and requires Soul/Area assets of the correct
types. Source numeric context indexes are not guessed from sorted roles.
Unknown contexts, missing areas and failed expressions cannot create partial
condition ports. This adapter is not yet bound to the source encounter.

- [ ] Resolve and register the original encounter area and dialogue contexts.
- [ ] Connect the first debt conversation, choices, voices and quest effects.
- [ ] Convert combat initiation, win/loss/flee outcomes and follow-up dialogue.
- [ ] Preserve goods, key/chest access, ownership and objective completion.
- [ ] Connect friend assistance and quest-controlled work interruptions.
- [ ] Verify each supported route and save/load in game.

Validation: 266 campaign tests pass. No package was installed in this pass;
the installed travel package still matches `CameraEnumRecovery01`.

The subsequent area dependency pass discovers literal `IsActorInside` references
after expanding source dialogue functions, including objective-effect conditions.
It stages the source encounter trigger in `outputs/OpeningStart/KenishAreas01`:
one entity, original GUID `b3533381-56bd-4678`, four unchanged world-space polygon
vertices. Existing entities and polygons are preserved; conflicting or missing
source areas fail the merge. This package is not installed yet. The actor is
already installed, but was missing this referenced trigger entity.

Read-only native inspection finds `IsActorInside` in Framework.dll and `IsActor`
in RPGModule.dll; a shipped native test dialogue also uses `IsActor`. The saved
binary hashes/string offsets are discovery evidence, not proof of equivalent
dialogue context indexing. Check that contract before substituting a fixed actor
or enabling encounter branches. Validation now passes 269 campaign tests.

### Latest accepted development checks: Father greeting and skill check

On 14 October 2026 the user confirmed that Father's automatic proximity callout
and the skill-check conversation both worked in the installed development build.
This supersedes the earlier unverified status for these two acceptance targets.

- [x] Father calls out on approach without the player selecting Talk.
- [x] Father's skill-check conversation is reachable and works in the live test.
- [ ] Verify all skill-check outcomes, greeting replay rules and save/load.

The generic proximity adapter converts the source observer's objective gate,
delays, distance thresholds and monologue aliases into native quest nodes. It
runs alongside the accepted smithy routine. In-world monologues retain native
speech handling and recording bindings. The dialogue emitter registers local
sequence-history references with `Visibility="Internal"`; omitting this caused
runtime `SequenceUsed` evaluation errors and prevented the greeting.

Validation: 241 campaign tests passed. The installed package and hash receipt
are in `outputs/OpeningStart/FatherGreetingRuntime03`. Only the two greeting
dialogue definitions changed in that final package correction. These checks do
not establish completion of every work routine or the opening-to-attack quest.

The requested next milestone ends when Skalitz is attacked. Playable escape to
Talmberk is outside this pass. Dependencies must be discovered from source
records and upgraded or merged through reusable adapters; actor-specific
startup scripts are not the implementation.

- [ ] Preserve Henry's original starting appearance, equipment, inventory,
  hunger, injuries, stats and quest-controlled restrictions.
- [ ] Complete normal parent conversation, quest hand-ins and return to their
  original work routines after dialogue or interruption.
- [ ] Import the remaining quest actors, tools, workplaces, movement and
  relocation dependencies for every supported pre-attack branch.
- [ ] Complete the source errands, training and optional village branches,
  including failure conditions, item ownership and rewards.
- [ ] Connect forging and subsequent scenes to the original attack profile
  transition, with participant placement, animation and control handoff.
- [ ] Test the sequence from a fresh menu start, including save/load at its
  phase boundaries, through attack onset.

The state dependency pass now compares buff effects before reusing native IDs.
All eight buff identities referenced directly by the Skalitz quest resolve:
seven merge with matching native effects, while attack protection receives a
separate converted record because KCD2's version adds protection effects.
The generic compiler upgrades add/remove references to the same registered
identity, preserves source lock scope/name/value, translates supported stat
advancement calls, and resolves literal actor/item keys only for declared
string-keyed associative maps. Unknown scripts and ambiguous indexes remain
explicit conversion failures.

The dependency report preserves action sites, ancestor conditions and persistent
variables. It is not a list of actions to execute at startup. Included helper
documents contain additional trees whose reachability is not established by
this scan; one helper buff still lacks a source UI-visibility enum contract.
Run `tools/campaign_state_dependencies.py` with the source/target installations,
quest, namespace and a new output directory to reproduce the preflight.

Validation: 160 campaign tests and 67 character tests pass. The source-backed
Skalitz preflight is staged in `outputs/OpeningStart/StateDependencies01`.
These changes have not been installed or validated in game. The complete
opening-to-attack sequence remains unaccepted.

### Starting-state and work-program conversion follow-up

The earlier live menu test exposed missing conversation continuation, source
starting state, and full parent routines. The follow-up below records the fixes
that have since been installed and distinguishes remaining runtime failures.

The follow-up dependency correction expands named dialogue predicates, follows
`IsSeqAvailable` dependencies, and discovers dialogue aliases from registered
controller callbacks and reachable work/include trees. The campaign compiler
now requests source NPC souls referenced by that closure even without explicit
quest asset links. Source test-only branches and unlinked historical callbacks
remain recorded separately and are not activated. The dialogue staging command
supports `--discover-quests` instead of requiring a manually selected topic list.

Two additional conversion errors were identified and corrected in source:

- Unflagged terminal sequences now retain native EndTopic behaviour for forced
  conversations too; choosing ForcedDialog must not itself force EndDialogue.
- Constant-true, untracked objective completion with an explicit source `#GT`
  duration now emits a native persistent Timer with the original duration and
  start event. In Skalitz this includes `fatherIsUpset`'s `4m #GT` timer, which
  selects Father's reprimand/skill-check route. Completion still checks that
  the objective is Started; cancellation stops the timer.

Validation for this correction: 227 campaign tests pass. Source-backed graph
emission produces the four-minute timer. This does not establish in-game timer,
save/load, conversation continuation or schedule behaviour. A complete dialogue
staging attempt also exposed missing localized source responses in the larger
closure; the build fails rather than emitting text or voice placeholders.
The ending/timer refresh is installed in the development build, with a backup
and SHA-256 receipt in `outputs/OpeningStart/ConnectedOpeningFix01`. The live log
shows the opening and ordinary Mother questions in one dialogue session; the
user also confirmed the follow-up menu appears. Timer outcomes remain unverified.
The complete startup controller, housework and blacksmith programs still require
conversion and integration. The audio packager now derives enclosing level/quest
namespaces from instantiated definitions. The corrected package is installed;
live audio callbacks and the user confirm Mother's and Father's voices now play.
Mother's follow-up restores 34 authored camera commands using the registered
source camera assets, with live camera-cut events recorded. Lip-sync is still
missing and Father's automatic camera selection reports collision failures.

The installed development scene still uses selected opening fragments and
schedule arrival/housework-sweeping support. It does **not** run the complete
source startup controller, housework cycle or blacksmith cycle. The source
time/equipment adapters are not proof that those effects occur in game.

Source RPG initialization is now bound to the existing persisted New Game
entry before dialogue rewards. The generic initializer reads source core stats,
extracts unconditional source quest-start state calls, validates native setter
contracts, and preserves the selected lifecycle edge. It does not reset stats
on each load. The source player has no explicit soul2skill overrides; the
requested unassigned skill baseline is 1. Native merged skills use that baseline.
A fresh menu start verified all four core stats at 1 and nourishment at 40 before
choices, and 15 active skills at 1. The user confirmed starting hungry. Main-level
UI, perk points, reward retention and save/load still need separate verification.

Rebuild with `tools/build_campaign_initial_state.py` and an explicit lifecycle
binding JSON. The installed package, backup and receipt are in
`outputs/OpeningStart/InitialStateAndCameras02`; audio namespace installation is
in `outputs/OpeningStart/ParentAudioScope01`. The retained live log is
`outputs/OpeningStart/InitialStateAndCameras02/live-test.log`. Validation: 231
campaign tests pass. Full routines, Father's proximity bark, and the timed
skill-check route remain the next acceptance targets.

- [x] Follow database-dispatched area work, object work and literal
  `CallBehavior` callbacks in addition to `IncludeTree` dependencies. Preserve
  all matching source implementations, their registry rows and provenance.
  Dynamic dispatch and missing source documents remain explicit unresolved
  dependencies; a missing secondary document no longer hides every other
  valid program in the import.
- [x] Add native contracts for work-loop iteration, save-load branching,
  reservations, mailboxes, interruption gates and search/execution structure.
  Unsupported children still withhold their entire tree and its callers.
- [x] Convert supported continuous objective-state gates while retaining their
  `Halt`/`KeepRunning` and negation policies. Bind object-relative quest names
  only at database-registered quest callbacks.
- [x] Register source AI link types, translate link-data variables and literal
  search masks consistently, and assemble original world edges after both
  endpoints have converted. Preserve untagged tool edges and graph cycles.
- [x] Correct native inventory presets to reference actual registered item
  names rather than unsupported `ItemClassId` attributes. Resolve replacement
  IDs through emitted definitions and reject absent or ambiguous names.
- [x] Discover area lifecycle callbacks and sibling work programs in addition
  to the initially requested job. Register converted smart-area templates and
  their native SmartArea subbrains, retaining enter/exit/request/release/update
  entry points. Convert quest-bound work-area placement and geometry.
- [x] Preserve compiled world-space area vertices, or transform source XML
  local-space vertices once when the compiled polygon is absent.
- [x] Preserve behavior-request lifecycle handlers, string type defaults,
  home-link pruning and exclusive named area/object requests. Convert the
  housework random selection and player-proximity operations using native
  evidence, including a runtime probe for string defaults and random selection.
- [ ] Translate the remaining source animation events,
  item pickup/release, LOD transitions and cleanup semantics.
- [ ] Finish remaining type contracts, home-link ownership, actor brains and
  area/object behavior registration needed by the complete work programs.
- [ ] Integrate source startup state at its original guarded execution sites,
  then test fresh New Game, dialogue interruption/resumption and save/load.

The source-backed rebuild at `outputs/OpeningStart/ControllerAudit10` discovers
1,426 trees through includes, database callbacks and area-context dependencies;
334 whole trees convert (previously 279 of 1,361). Those totals include shared library programs and
alternative registrations, so they are **not** a percentage of quest completion
or proof that each program is reachable. `housework` and the `fatherPatch`
scheduling wrapper now emit completely. `BlackSmith_new` still requires 18
operation-site conversions; the mother's wrapper needs its dialogue helper.
The area registration pass attempts all 74 discovered candidate templates.
One complete template (`sa_watch`) registers; the home and forge templates
still need their other job programs and lifecycle dependencies converted.
The housework entry tree alone is not the complete housework cycle.
The fragments remain outside an installable `Data` tree.

Validation for this follow-up: 220 campaign tests, 67 character tests and seven
quest-import tests pass. The prior temporary native contract probe was run and
removed; this area-registration follow-up has source-rebuild and regression-test
coverage, not new in-game acceptance. The production schedule package has not
been replaced. See
[native work-contract validation](native-work-contract-validation.md) for
runtime evidence and the remaining integration milestones.

## Original New Game and character creation

- [x] Inspect the original New Game entry, opening behaviour and referenced source records.
- [x] Convert the original opening movie and demonstrate native playback; the user accepted the movie stage.
- [x] Import the mother's source appearance and resolve her cross-layer entity links.
- [x] Bind 27 original recordings to native voice, dubbing and subtitle registrations.
- [x] Convert the source dialogue choices and nine objective callback connections in the staged runtime package.
- [x] Register imported custom-camera assets and their world links.
- [x] Convert source participant markers to native dialogue-entry placement, without changing camera coordinates or adding guessed height offsets.
- [x] Test both Speech choices and return to normal gameplay with Henry and the mother remaining at the authored indoor floor height, without manual jumping or repositioning.
- [x] Resolve the full quest-graph loading stall and load all 109 source objective states in the development scene.
- [ ] Reconnect objective callbacks and verify that each selection awards the correct stat increase exactly once. Staged bindings are not runtime reward acceptance.
- [x] Verify both Speech selections execute rewards, return to gameplay, and retain Speech 7 after a quicksave/reload. Other branches and forced duplicate-completion tests remain open.
- [ ] Validate every first- and second-round choice combination against the original source flow.
- [ ] Import the five unresolved gesture commands currently omitted by the explicit test flag.
- [ ] Restore original lip-sync and verify voice, facial animation and gesture timing together.
- [ ] Import the original starting-player appearance, equipment and relevant RPG state.
- [ ] Convert incompatible tutorial calls and suppress unrelated exploration quest notifications during New Game.
- [ ] Verify a fresh complete movie and a skipped movie both enter the correct conversation once.
- [x] Verify dialogue completion completes source `objectiveStart`, activates its original successor objectives, and releases the conversation to gameplay.
- [x] Register original journal strings and place the quest under its destination Level; opening journal text and region are confirmed in game.
- [ ] Verify quest markers and connect the father's original interaction.
- [ ] Validate saving/loading before and after the conversation, stat persistence and prevention of repeated rewards or scene replay.
- [ ] Integrate the accepted opening into the campaign installer with its movie-conversion prerequisites.
- [x] Connect the development menu's native New Game route to the installed opening package. The user confirmed the menu works; its entry is **New Game Debug Sasua region**, directly below **New Game**.
- [ ] Validate movie completion and skipping, two fresh menu starts, and Continue without replaying the opening as separate acceptance cases.

The placement test uses the original participant transforms. Both real actors
and dialogue copies measured 63.9089 m during the first menu; the real actors
remained at that height after dialogue cleanup. The earlier initial fall may
involve collision readiness, but that cause has not been isolated. Native
scene-entry placement is the verified correction in the sampled scene.

Implementation and evidence: [cinematic and dialogue import](cinematic-dialogue-import.md),
[dialogue runtime binding](../tools/campaign_dialogue_runtime.py),
[scene conversion](../tools/campaign_scene.py),
[development scene builder](../tools/campaign_scene_test.py).
The builder stages packages and does not install them implicitly. The current
development package includes the full source objective graph, original journal
text and all eight stat-reward bindings. The graph is not a complete quest:
unsupported behaviour, conditions, timers and interactions remain reported.
The sampled save/load retained Speech 7 and did not replay character creation;
that does not yet establish persistence of every objective or reward guard.

The journal correction registers 59 source strings and moves the quest instance
under its native Level while preserving graph connections. The user confirmed
the region correction in the fresh JournalRegion01 development build. Existing
saves from the earlier project-root quest layout have not been migration-tested.

The next quest pass discovers 94 source dialogue branches referencing Skalitz,
including anonymous entry topics, and reports two orphaned callbacks. Supported
boolean quest predicates are converted to validated native dialogue ports.
Tracked objectives no longer complete merely because their source condition is
constant true: their item/NPC tracking still needs conversion. This prevents
false completion; it does not yet make father's errands playable. Persuasion,
reputation, remaining conditions and interactions stay open.

The next development package adds native inventory descriptors and event-driven
completion for 12 supported item-tracked objectives. The original crossguard
and beer item dependencies are imported through the existing item converters.
Completion checks retain source quantities, require the objective to be active,
and recheck inventory after a queued event. Fourteen tracked objectives still
need NPC, location or other predicate support. This implementation does not yet
verify inventory thresholds in game or connect the father's interaction.
Build with [the quest-item staging tool](../tools/build_quest_items_test.py);
the staging tool never installs implicitly.

The quest-person staging tool now discovers explicit `quest_npc` soul dependencies,
reuses actors already present, and imports missing source appearances, identities,
homes and authored entity placements. The Skalitz development package adds father,
`ska_sarka`, `ska_blanka`, `ska_fricek` and Kunesh; mother and Theresa are reused.
Six active objective logs now reference registered soul assets, including both
father objectives. These markers follow actors; source quest-editor coordinates
are not world positions. Archive integrity, actor/soul identity and original
placement checks pass, but in-game visibility, markers and save/load remain unverified.

`vra_vanek` now converts with his original outfit. All six installed base/patch
copies of the lowered-hood mesh lack the table's requested `#V_001`; another
source clothing record explicitly uses the same mesh without a variant. The
importer retains that dedicated base geometry only when matching source records
support it and the mesh has no selectable variant shapes, recording the decision.
Shared location/home areas are reused after transform and polygon validation.
All eight explicit NPC dependencies are registered. Vanek's authored world
placement is at Vranik; his Skalitz quest-stage relocation remains unconverted.
New actors use the existing native interruptible
idle baseline; their authored work routines, dialogue roles/conversations and
hand-ins are not converted by this dependency pass. Existing actor presence also
does not establish the correct quest-stage placement (notably Theresa).
Build with [the quest-person staging tool](../tools/build_quest_people_test.py).

Schedule conversion now resolves source daycycle intervals through activity links,
smart-area templates and behavior-tag tables using [the generic schedule resolver](../tools/character_schedule.py).
The parents resolve to `final/sa_smithy.xml:BlackSmith_new` and
`final/sa_home.xml:housework`, both all-day `work` entries. These are complete
activity graphs, not fixed walking targets. Native `Move` and `ExactMove` lowering
preserves variable destinations, speed, direction and arrival tolerances.
The schedule staging tool now registers native movement activities at the source
area arrival positions and uses the original daycycle intervals. Runtime testing
moved father from the house to the smithy, but he became stuck before reaching
the final target. This is not a completed forging routine.

[The generic job-item helper](../tools/character_job_items.py) reads KCD2's native
job reservation graph, registers/reuses source tool slots, supplies pickup
helpers, and replaces decorative NPC-tool meshes without duplicating the item.
The housework sweeping adapter uses the source-linked broom and the native
`schedulerReservedItem['use','tavern_broom']` contract. In `ParentSchedules04`,
mother collected one broom, held an item in her hand, and entered native
`SweepingFloor`; the pickup logged an animation fallback. No NPC-specific
inventory injection, animation timer, or teleport implements this job.

- [x] Source-linked broom registration, native reservation, collection and sweeping tested.
- [ ] Resolve the pickup-animation fallback and verify tool return after interruption.
- [ ] Convert the original sweeping route points and the remaining housework activities.
- [ ] Resolve father's blocked approach and convert the full forging/tool cycle.
- [x] Connect the imported smithy schedule to native blacksmith work animations;
  the user confirmed Father performs his work animation on 14 October 2026.
- [ ] Verify shared-tool contention, missing/stolen tools and save/load persistence.

The installed `FatherRoutineBuild02` upgrades source `BlackSmith_new` jobs by
behavior identity and workstation category links, without selecting an NPC by
name. It connects the native heating/forging controller, source sword and hammer
slots, reservation graph, heating slots and animated bellows. The workstation
uses a rigid fit to the source tool contacts (approximately 6 cm residual for
this smithy); incompatible layouts are rejected rather than scaled.

The first live build reached the native controller but failed to resolve
`BlacksmithBehaviorHeatingIn`. The second binds the exported local animation
collection hash at the converted world transform. Father performing his work
animation is user-confirmed; a complete repeated cycle, item return after
interruption and save/load still need validation. Original KCD1 tempering and
quest-cooperation phase locks remain unconverted. Validation: 70 character tests
and 4 activity-contract tests pass. `--jobs --jobs-only` in the schedule staging
tool upgrades existing imported arrivals without resetting other schedules.

Build with [the schedule staging tool](../tools/build_person_schedule_test.py),
using `--jobs` for supported work phases. Its report lists unconverted activity
phases explicitly. Other NPCs' idle baselines and existing authored jobs are
preserved; complete schedules across Skalitz are not yet verified.

## Campaign conversion milestones

Parent dialogue import remains in progress. The importer now resolves source
`soul2role` memberships and conversation branches, including unnamed branches,
and can register isolated dialogue roles through Storm without per-NPC rules.
Source `dialogue_functions` dependencies expand through the condition parser;
supported item-count predicates require registered items. Selection conversion
resolves the source `sequenceType` enum, named difficulty records and reputation
effects against inspected target contracts. Renamed skills require an explicit
upgrade mapping. Reputation-cap differences can generate separate imported
records instead of changing native game records.

The parent source audit found 214 role-associated branches, of which 10 touch
the Skalitz quest. Father's first conversation now emits with a selection
contract. This is **not** in-game acceptance: normal talk interaction, the other
conversation branches, dialogue interruption/resumption of jobs, and father's
full forging cycle remain unchecked. Source health/bleeding and streaming
predicates still need adapters; no unsupported predicate is treated as true.

- [x] Provide source quest, dialogue and dependency inspection and bounded graph-conversion tooling.
- [ ] Audit the complete source quest inventory by main quest, side quest, activity and DLC, retaining original IDs and names.
- [ ] Convert the remaining Skalitz opening objectives and their original ordering, conditions and dependencies.
- [ ] Convert subsequent main-quest sequences and transitions between source maps.
- [ ] Convert side quests, activities and DLC quest chains, including their prerequisites and alternate outcomes.
- [ ] Translate remaining objective conditions, timers, failure/cancellation rules and behaviour-tree callbacks to native contracts.
- [ ] Register all required NPCs, roles, schedules, homes, ownership, interaction targets and navigation dependencies.
- [ ] Convert quest-driven world profiles, layer activation, entity visibility and persistent world changes.
- [ ] Convert cinematic actor placement, animation, camera, audio and scene-completion contracts throughout the campaign.
- [ ] Preserve quest items, inventories, rewards, reputation, money and stat changes.
- [ ] Restore journal entries, markers, tutorials and discovery notifications with correct localization.
- [ ] Verify death, combat interruption, retries, fast travel and leaving/re-entering quest regions where supported by the source.
- [ ] Verify campaign state across saves, reloads, region transitions and supported mod upgrades.
- [ ] Package and validate a fresh campaign installation with an explicit list of supported quests and remaining blockers.

No whole quest chain is marked accepted solely because its graph converts or
its dialogue plays. Existing KCD1 save migration is a separate feature.

## Acceptance checklist for each quest

Use this checklist when adding a quest to the audited inventory. Record its
original ID/name, prerequisites, source map, converted dependencies, test build
and evidence, along with any unsupported source semantics.

- [ ] Prerequisites and activation match the original source.
- [ ] Required actors, objects and layers load with correct identities and placements.
- [ ] Objectives start, update, complete, fail and cancel correctly on every supported branch.
- [ ] Dialogue choices, checks, recordings, subtitles and presentation match the source.
- [ ] Cutscenes complete and skip correctly, with actor/control handoff verified.
- [ ] Items and rewards are correct and cannot be duplicated by re-entry or reload.
- [ ] Journal entries, markers, tutorials and world changes appear at the correct stages.
- [ ] Save/load preserves progress, inventory, actors and persistent world state.
- [ ] The next quest or intended free-play state begins correctly.
- [ ] In-game acceptance evidence is recorded; remaining limitations are explicit.

### Parent conversation runtime checkpoint (14 October)

The staged ParentInteraction01 build registers four ordinary conversations and
70 recordings. In-game entry is reachable, but the user reports missing voices,
camera changes, and father's work/reactions. The menu exposes an internal
sequence path. Henry's starting outfit is also missing. These are open failures,
not accepted campaign coverage. At this checkpoint, conditional father-return
objective effects and health predicates were unsupported. Streaming predicates and Level-host
bindings now have adapters. The current campaign unit suite passes 162 tests;
this does not verify the installed conversation or full Skalitz progression.

The next source audit identified a general integration gap: the playable opening
uses selected scene/reward fragments, while the full quest controller remains
blocked. Consequently, controller-owned initialization is absent from that
playable stage. In the source, `onUpdate` sets hunger to `40` only after the
`assetsLoaded` lock and the quest-start mailbox event. It is not inferred from
elapsed time. The bounded RPG adapter now converts native-supported hunger,
exhaustion and health setters at their original execution sites, and tests
ensure a blocked sibling prevents emitting a partial initialization tree.
State reports distinguish a supported lowering from an installed operation.
This adapter has **not** yet restored the controller to the installed build.

Dialogue scope is another gap: source `next=0` ends a branch, but the current
emitter assigns `EndDialogue` to every such terminal. The original opening
returns to Mother's ordinary questions before the player ends the session.
Session continuation, automatic entries, explicit exits and their conditions
must be converted together; the current forced-scene handoff is not accepted.

Runtime logs also confirm missing recording lookups for father (voice 0) and
Henry (voice 108). The ordinary-dialogue builder now derives imported actor
voice registrations from source role membership and recordings, rejects
conflicting voices, and preserves existing master roles. Runtime lookup paths
still require verification. Father's first branch has 71 presentation commands;
45 gestures match native clips, while six references to two distinct clips
remain unresolved. No missing gesture is counted as converted. The current
campaign test suite then passed 167 tests; voice, presentation and full work-cycle
acceptance remain open.

### Generic initialization and dialogue update (14 October)

The source opening calls `forwardTime(10.00)` and acquires the named
`q_skalitz` world-time lock. The attack scene releases that lock and advances to
`16.00`. The converter now emits ordered native clock actions and independent
persistent pause states, and the campaign host declares their module. These
clock operations remain inside their original behavior-tree gates. Their
runtime scheduling relative to surrounding AI actions and save/load still
require verification; they are not installed as a replacement startup script.

Initial-equipment discovery now follows source clothing and weapon presets,
including instance overrides, quantities and equipped flags. The full campaign
item path uses the existing wearable/weapon/document adapters. Henry's source
outfit resolves to four registered items, with an explicitly empty weapon
preset. His source strength, agility, vitality and speech are all `1` before
dialogue rewards. The generic loadout output is staged in `PlayerClothing01`;
the original player initialization and full soul/brain registration still need
integration. No starting-stat or outfit runtime acceptance is claimed.

`ParentInteraction03` is installed with a hash-verified backup. It contains five
ordinary conversations and 116 recordings, including Father's return branch.
Source branch priorities and greeting policy are preserved. Unflagged ordinary
branch terminals use native `EndTopic` semantics instead of closing the whole
conversation. The native editor declares this as enum value zero and omits
`EndType` when serializing it; production FaderDialog files use that default.
The forced opening's continuation into Mother's ordinary questions is still
pending, as are automatic entry and nonzero source sequence-flag semantics.

Conditional objective effects now retain their source ordering and evaluate
each predicate against live state when its turn executes. Father-return topic
`9193` contributes two programs containing five actions. Unsupported
dialogue-local predicates still block conversion. Imported parents receive
their recorded voice identities and retain their existing display-name keys.
Voice playback, camera switching and work interruption/resumption need another
in-game test; installing the package is not that verification.

Validation: 184 campaign tests and 67 character tests pass. Package integrity
and installed hashes pass, with no archive entries removed. The complete
Skalitz controller, all schedules, Henry's initialization and the attack
handoff remain unfinished. The current scope ends at the start of the attack.


### Debt conversation dependency conversion (14 October)

The generic actor branch selector now follows source role membership within
the quest dependency closure. Dialogue entity predicates preserve the original
context index and resolve source names against installed actors and converted
trigger areas. The area importer preserves source polygon geometry and rejects
missing or ambiguous references instead of substituting a position check.

`KenishRuntime01` installs the first debt conversation with 23 recordings,
source-derived voice registration and its original trigger area. All four
archives were backed up and hash-verified. The development game reached Skalitz
gameplay without a new dialogue-expression load error; condition evaluation and
the complete debt quest remain unverified. The explicit threaten-to-might skill
upgrade also needs gameplay validation; identical check mathematics is not claimed.

A proposed single-predecessor exclusive-objective rule was withdrawn before
installation: it would activate both caught and escaped branches, and source
selection semantics have not been established. `KenishConnected01` is marked
rejected and must not be installed. No source-exclusive transition is forced on
to make the conversation available. Combat outcomes, friend assistance, goods
collection, and return-to-father progression still require integration and tests.

Validation: 271 campaign unit tests pass. This is package/load verification,
not an end-to-end quest pass.


### Debt-state transition correction and outcome dependencies (14 October)

The earlier concern about starting exclusive objectives was based on an
incomplete interpretation. The developer Quest System Documentation specifies
that exclusivity applies to predecessors: completing one alternative cancels
its exclusive siblings and starts their successor. Exclusive objectives can
themselves be started normally. The importer previously inspected the target
flag and incorrectly suppressed these transitions.

The generic graph emitter now handles ordinary all-predecessor joins and
exclusive alternative joins, emits guarded sibling cancellation, and permits
restarting canceled objectives on subsequent predecessor completion. Mixed
exclusive/nonexclusive joins remain explicitly unresolved because their
combination is not established by the documentation. The effective Skalitz
source has no such mixed joins. A transition refresh replaces generated graph
wiring while retaining installed dialogue, inventory, journal and reward logic.

Reference: https://modding.wiki/en/kingdomcomedeliverance/developers/quest-system-documentation

`KenishRuntime02` installs this graph correction, two additional dialogue actor
dependencies (from source normal-profile membership), and three outcome
conversations with four recordings. Six archives were backed up as applicable,
installed and hash-verified. Source profile membership disambiguates roles
shared with the Theresa campaign. Missing or multiply matched actors still
fail conversion rather than selecting the first soul.

Validation: 274 campaign tests pass, including alternative-join truth cases,
sibling cancellation wiring, shared-role resolution, and preservation and
idempotence of transition refresh. The restarted game reached Skalitz gameplay;
the opening dialogue and its ordinary-question handoff appear in the log.
The pre-existing DialogueHolder reset warning remains and is also present in
`KenishRuntime01/startup.log`. This is not an end-to-end debt quest pass.

Still pending: original voice abbreviation `fwri` needs a destination voice
registration for the friend conversation; the complete combat behavior needs
its source operation/dependency adapters and dispatch; work/home links and
friend assistance, goods collection and return-to-father must be tested.
No installed quest outcome was forced through a debug completion call.

### Additional behavior adapters (14 October)

Explicit buff removal now accepts the native no-tag sentinel `BuffTagId="-1"`
when the referenced buff is registered. Link-data assignments resolve their
source link tags and typed dependencies before emitting native writes; local
variables and quoted strings are preserved. Missing or ambiguous link types
remain conversion errors. These adapters are source-tested but have not been
rebuilt into the installed `KenishRuntime02` package.

Validation: all 276 campaign unit tests pass. Combat dispatch and end-to-end
debt progression remain unverified; this does not mark the quest complete.


### Automatic conversation camera correction (14 October)

The prior camera-enum recovery removed the entire automatic camera command.
Native shipped conversations instead serialize automatic selection as a
`CameraCommand` with no `CameraType` attribute. `Skald.Core` defines Auto as zero;
27,311 shipped commands omit both CameraType and CustomCamera. A response role
alone does not carry the explicit cut request.

The generic emitter now emits that native command for the source response's
speaker. Authored entry shots take precedence, while delayed cuts retain an
initial automatic speaker shot. Explicit source automatic commands use the same
serialization. No NPC-specific coordinates or camera choices are added.

`build_dialogue_camera_refresh.py` discovers installed imported cinematic
dialogues by their source topic identity and refreshes only their camera
commands after validating source response order and role mapping. It preserves
other commands, dialogue actions and recordings, and leaves in-world barks alone.

`CameraSpeakerRefresh01` was backed up, installed and hash-verified. It restores
104 automatic commands across ten cinematic dialogue definitions and retains
66 authored camera commands, including the original opening cameras. All 277
campaign tests pass, including refresh idempotence and preservation checks.
The development game reaches the menu. Speaker switching remains pending a
live conversation check. Earlier logs also report invalid bone cameras and a
missing camera-animation timing GUID; whether those remain after the restored
cut requests must be checked before declaring the camera work complete.

### Repeat-conversation camera placement (14 October)

The user confirmed Mother's lip-sync works, but reopening her conversation
still selected fixed opening-room cameras. The runtime log confirms the repeat
branch requested `cam_26424_mother*` and `cam_26424_henry*`. Source camera
references alone do not establish that participants remain at those positions.

Generic dialogue emission and refresh now adapt custom world cameras to native
actor-targeted automatic cuts unless the conversation has explicit scene
placement. Authored role targets and delays are retained. The package refresher
checks DialogueHolder bindings on graph instances; mixed placed/free instances
of a shared definition fail rather than silently choosing one policy. Standalone
scene conversion can retain fixed cameras with `--scene-bound`, which requires
the caller to provide the corresponding actor placement.

`RepeatConversationCamera01` is installed and hash-verified. Its only changed
archive entry is Mother's repeat conversation: 34 fixed camera commands became
actor-targeted cuts. The opening definition and its 27 authored commands are
unchanged. All 279 campaign tests pass; non-camera XML was compared and is
unchanged. Live repeat-conversation framing after Mother moves remains unverified.

### Native-head facial compatibility trial (14 October)

Mother's original imported face was confirmed moving by the user. Henry uses
native facial controls, while the imported recordings previously supplied only
KCD1 controller IDs. The active native male skeleton and shipped facial DBAs
use `FA_POSE_*` controls; the separate legacy Henry head preview rig is not the
correct vocabulary for those speech tracks.

`facial_rig_adapter.py` validates a reusable semantic mapping against the source
and target rigs. Forty source controls add 43 native controls for jaw opening,
lip shapes, eyes and expressions. Original controller IDs and shared compressed
curves remain intact, so source heads retain their animation. The adapter updates
both DBA controller counts and facial-index counts. Missing controls, competing
drivers and hash collisions fail explicitly. Thirteen source expressive controls
have no mapped native equivalent; their original tracks remain. This is a
compatibility mapping, not proof of identical acting on the different face rigs.

`HenryFacialRig01` is installed with a backup and verified checksum. It covers
293 recordings in 30 DBAs, including 125 Henry recordings. Package validation
confirmed every original controller, curve buffer and timing record is retained;
Henry's native jaw aliases reference his source jaw tracks. All 288 dialogue and
campaign tests pass. An incremental rebuild produces identical entry contents.
The user confirmed Henry's facial animation works in-game after launching this
installed package. Mother was confirmed working before the native-rig adapter;
a separate post-adapter Mother regression check and broader NPC facial acting
coverage remain unverified.
