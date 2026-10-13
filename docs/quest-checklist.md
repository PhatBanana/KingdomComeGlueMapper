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
- [ ] Connect the menu's native New Game route to the accepted opening package; validate movie completion and skipping, two fresh starts, and Continue without replaying the opening.

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

## Campaign conversion milestones

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
