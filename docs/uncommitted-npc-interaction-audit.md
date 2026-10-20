# Uncommitted NPC interaction audit — 20 October 2026

Scope: working tree against `3b8d7cf`, including the untracked training modules,
their callers and generated/installed XML. This audit did not operate the game.
The reported retail symptom is active conversations/quests with stationary NPCs
and missing assault reactions. That symptom is **not yet explained by a proven
root cause** in these changes.

## Corrected code defects

- `campaign_quest_graph.py`: the new Quest:End conversion connected predecessor
  notifications directly to `quest_progress.SetDone`. An enabled Begin -> End
  path fed `quest_progress.OnActive` back into that same State synchronously.
  Completion now crosses a zero-duration native Timer and rechecks the active
  quest and predecessor join. Leaving Active stops the pending timer. This
  follows the existing deferred objective-completion contract; it is not evidence
  that this path caused the observed retail freeze. The timer has its own
  `quest_end_` namespace so objective-only refresh does not misinterpret it.
- `campaign_training_schedule.py`: cancellation or arrival failure could leave
  `request_sent` true while the source arrival objective remained Started. A
  later reconcile could never request arrival again. The latch now clears after
  the lifecycle's post-cleanup `canceled` acknowledgement. Requests made while
  the lifecycle is busy no longer consume the latch.
- The same schedule binder rejected a pre-existing IsActive edge but accepted
  an IsActive constant. It could therefore emit two owners for a worker's
  activation input. Both forms are now rejected before modifying the graph.
- `campaign_training_dialogue.py`: pending instruction states were cleared only
  by caller-supplied cancel events. An internal readiness/preparation failure
  emits `stop_workers`, so an outstanding instruction could remain pending and
  prevent its phase from playing on retry. Internal stop now also clears these
  pending states. Releasing a late scene still requires a pending, active,
  matching phase, and invocation-scoped scene callbacks remain a caller contract.

Regression coverage includes synchronous Begin -> End feedback, cancellation
followed by retry of an unchanged source objective, requests during cleanup,
pre-bound activation rejection without partial mutation, internal failure's
pending dialogue release, and idempotent objective refresh preserving the quest
ending timer. All 546 `test_campaign*.py` tests passed. Graph simulation and XML
checks do not validate engine execution or actor reactions.

## Production reachability and limits

The three production integration changes are objective dependency discovery in
`campaign_compile.py`, counted/map-only objective classification in
`campaign_objective_conditions.py`, and quest-end/linked-condition generation in
`campaign_quest_graph.py`. The new tutorial lifecycle, readiness, equipment,
arrival and dialogue helpers are currently called by their adapter tests and
other training helpers; setup has no production call wiring them into an actor.
They do not yet constitute an installed Vanyek lesson.

A static scan of the root Data PAKs in both the retail and Mod Tools
`Mods/kingdomcomegluemapper` installations found none of the new
`source_state_changed`, `linked_condition_`, `CombatTutorialNode`, or
`tutorial_npcReadyForCombat` nodes, nor a quest-progress SetDone edge from the
new `advance_` end gate. This rules out those emitted additions in those two
package snapshots. It does not establish that every possible local build,
override or saved game has the same contents.

The new training code does not add debug stat setters, console execution,
teleport calls or a global NPC-AI disable. Its readiness context is scoped to
the executing tutor; the host is still responsible for stopping the worker.
Equipment and controller reports continue to mark the feature unvalidated and
not ready for publication. No installed archive was changed by this audit.

Do not describe these corrections as a verified fix for the reported retail
NPC freeze, missing hit reactions, Mother's broom, or Vanyek's placement. Those
symptoms need an attributable package/code regression before changing the daily
schedule or adding an AI-reset workaround.
