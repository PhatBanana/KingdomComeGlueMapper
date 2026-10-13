# Quest conversion checklist

Status: 13 October 2026. This tracks the original KCD1 campaign conversion into
KCD2. A checked implementation milestone means that specific capability exists;
it does not mark an entire quest complete. Development scene tests are separate
from the normal coach-travel installation route and published installers.

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
- [ ] Verify shared-tool contention, missing/stolen tools and save/load persistence.

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
