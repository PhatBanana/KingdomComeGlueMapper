# Starting quest audit — setup 0.3.14

Audited 20 October 2026 against source commit `3b8d7cf`, the original installed
KCD1 quest tables/controllers and completed build `20261020-042542-d3827be8`.
This is a static source/package audit, not a new playthrough. Earlier user
confirmations apply to specific interactions, not every route or save state.

## Present in the current package

- New Game initialization, starting state and equipment, Mother's opening and
  follow-up conversations, Father's initial conversation and hand-in dialogue.
- Kunesh's initial conversation, combat and result conversations, carried
  inventory conversion, quest-item tracking and local objective-event handling.
- Janek/Jaroslav guard conversations and crossguard handover infrastructure.
- Bianca's source-selected dialogue, ale/quest-item handling and merchant service.
- The selected `ska_collierVarlet` charcoal seller and stock/service import.

The built travel archive contains the corresponding dialogue definitions and
service markers. The setup merchant selection contains only that charcoal
seller; it does not establish conversion of all charcoal workers and their later
quest dialogue. Older October 14/18 checklists predate several current repairs.

## Confirmed remaining progression gaps

### 1. Vanyek's linked fencing quest is absent

Source quest `q_tutorial_swordOne` exists (ID `67972108`). Its 16 objectives
include movement, normal attack, stab, combo, stamina, blocking and the final
showcase. Its registered controller also includes walking to the training area,
training setup, cleanup, completion and leaving.

The opening objective `practiceFencing` explicitly depends on
`IsQuestCompleted('q_tutorial_swordOne')`. No quest XML in any root Data PAK of
the completed package references that quest. Vanyek is selected as an actor,
but `setup_gameplay.systems` excludes him from its ordinary actor-system
conversion. An actor and map marker are not an imported training quest.

The installed `q_skalitz` graph's automatic `returnToFather` transition ANDs
charcoal, crossguard, beer, `kunesSolved` and `practiceFencing` completion.
Father's dialogue also contains a conditional direct start/complete route for
`returnToFather`; therefore this finding does not prove every hand-in branch is
unreachable. It does prove the ordinary dependency path is incomplete.

Relevant code: `setup_gameplay.py` quest selection, actor systems and dialogue
selection; `campaign_objective_conditions.py` currently binds local objectives
only; `campaign_quest_graph.py` constructs predecessor joins.

### 2. Sword-making is a state without its source scene handoff

The source transition is `returnToFather -> fatherAndHenryMakeSword`. The source
controller responds to the latter starting by requesting `kovani_otcem` or
`forging_father_insert`, depending on the painting branch.

Neither scene alias appears in packaged quest XML. There are no external
packaged quest references to `fatherAndHenryMakeSword` beyond the objective
graph itself. Father's ambient blacksmith work is not this quest scene.

Required conversion includes source scene selection, participant bindings,
control/animation handoff, completion callbacks and interruption cleanup.

### 3. Theresa's nails and the attack transition remain incomplete

The source graph starts `henryGetsTheSword`, `takeNailsFromChest` and its tracking
after sword-making, then links the nails objective to `giveNailsToTereza`.
The existing package has a Theresa marker/reference, but that is insufficient
evidence of the original opening-scene exchange.

The original controller releases the `q_skalitz_terezaSynchro` external lock on
the nails handover and `q_skalitz_horseSearchSynchro` on `endQuest` starting.
The narrow objective-event importer accepts objective mutations, not these
external-lock actions. No `q_skalitz_normal` or `q_skalitz_attack` references
appear in packaged quest XML. Full profile activation/deactivation, actor
lifecycle and attack choreography are not supplied by the current slice.

### 4. Optional routes and area markers are only partial

The installed receipt still lists four pending place-marker bindings involving
Kunesh trigger areas and the German's house. It explicitly reports unsupported
area/cross-map handling or `TriggerArea` presentation.

Friends' assistance, the painting/manure sequence, pursuit/punishment and the
full theft/permission variants need their source-controller dependencies and
dialogue activation audited and converted. Existing actors, journal states or
ordinary containers do not establish those routes. Do not treat this audit as
proof that every such route fails at runtime.

### 5. Quest end and source rewards lack complete lowering

`campaign_quest_graph.emit_quest` records `quest_end_policy` and does not connect
the source end transition. For this quest the predecessor is objective 4,
`endQuest`. It also reports nonempty reward tables as unsupported: 13 XP rows,
four reputation rows and three achievement rows in the source opening quest.
Starting-stat conversion and dialogue side effects are separate mechanisms.
Do not assume they reproduce these objective rewards. Source-platform
achievements should not be mapped to unrelated KCD2 achievements.

## Recommended next general upgrader stage

Implement linked-quest dependency conversion, using fencing as the first
acceptance case:

1. Discover external quest references from source conditions, dialogue effects
   and registered controllers; resolve a deduplicated, cycle-safe dependency set.
2. Register the linked quests and bind their persistent states across graphs,
   including completion, failure, cancellation and save/load re-evaluation.
3. Convert the selected quest's reachable actor, dialogue, area, equipment and
   controller dependencies. Reject unsupported required operations with a source
   location instead of silently shipping only its objective states.
4. Convert training start, authored lesson progression, interruption/cleanup and
   quest completion through reusable operation adapters. Do not automatically
   complete fencing or bypass the prerequisite.
5. Verify a fresh New Game can finish the lesson, return the borrowed equipment,
   complete `practiceFencing` and reach Father's proper hand-in. Repeat across
   save/load and interrupted training before moving to the forging scenes.

Then tackle scene handoffs and profile lifecycle through sword-making, Theresa
and attack onset. Quest-end/reward lowering and optional routes remain explicit
follow-up requirements.

## Evidence and validation limits

The source quest has 109 objective records. That is a schema count, not a
completion percentage. Re-emitting the basic graph reports tracking policies
that later item/dialogue adapters already handle; those reports alone must not
be used to call working errands broken.

Read-only audit outputs are in `outputs/skalitz-audit-0.3.14/`:
`source-graph-report.json` and `sword-training-ir.json`. Inspection covered the
completed package's quest XML, receipt markers, source controller behavior and
registered training controller entry points. No gameplay code, installed mod,
save, or build package was changed during this audit.
