# Source opening and training upgrade

The setup recipe selects content in `tools/setup_gameplay.py`; shared converters
read its behavior from the installed games. The selection identifies an opening,
source lesson programs and conversation, plus a complete native curriculum. It
does not specify a starting hour, actor coordinates, objective names, inventory
GUIDs or a delay before the trainer becomes available.

## Opening time

`campaign_opening_clock.source_clock` reads the unconditional clock program at
the start of the selected source opening. The shipped selection resolves to
10:00. `bind` inserts it into the existing once-only new-game initialization
chain, preserving the campaign-start gate and loadout continuation. Loading a
save or entering the region does not reset time.

The converted campaign deliberately lets time run. The source prologue's pause
lock is recorded as provenance, rather than freezing the added day/night jobs.
A conditional or ambiguous initial clock program is rejected.

## Training handoff

`campaign_training_handoff.resolve` follows the source departure, objective
message and duel-result handler. It resolves the actor, destination reference,
priority, authorization and completion objectives without recognizing a named
trainer or town. `campaign_training_sources.resolve_equipment` follows the
registered controller callbacks to pair creation and removal of practice items.

`setup_training_upgrade` imports the follow-up conversation through the ordinary
dialogue converter. It retains source conditions, choices and quest actions.
The selected complete native Basic curriculum provides seven phases, instruction
dialogue, tutorial UI and combat settings. Its generated quest contains the
required state types and objectives; audio is relocated using the instantiated
quest namespace, with native duration and facial-index checks.

The shared host and worker enforce this order:

1. Source invitation and successful movement establish arrival.
2. Source dialogue authorizes the lesson, and its scene fully releases the participants.
3. The source arena's ordered position links select the player and tutor entry
   poses. The native training teleport scene places both participants there.
4. Only acknowledged scene release starts the registered equipment activity.
5. The worker equips converted practice items and releases the prior action.
6. Readiness permits native training. Its Basic curriculum deliberately begins
   with an instruction to draw the equipped sword.
7. Completion or cancellation stops readiness before cleanup.
8. Only successful cleanup may advance the source completion objective.

The earlier conversion omitted the source arena's entry handoff and began loan
preparation while the authorization dialogue still owned the actors. Recipe 56
repairs both stages in fresh and resumed packages. It reads the selected request,
arena dispatch and ordered source links; it contains no Vanyek coordinates or
new time gate. `training_entry_repair` uses the native `trainingGrounds_teleport`
fader scene with the project's actual player asset and the resolved tutor.
Scene cancellation drains the outstanding scene before acknowledging worker
shutdown, preventing a late completion from equipping a new session. JSON
receipts and PAKs are replaced atomically to preserve saved-build hard links.

Both equipment programs share persistent instance handles. Partial preparation
does not remove items by type or clear an arbitrary inventory slot. An absent
original weapon does not prevent borrowed-item cleanup. A cleanup failure emits
a fault and parks the worker, preventing repeated preparation and duplicate
loans. Automatic retry after a cleanup fault is not implemented in this host.

An older save with an already-completed arrival objective can enter the handoff;
a completed lesson cannot start again. Missing state-change output ports on an
older imported quest are added from its persistent source states, without
rebuilding or resetting that quest.

## Setup and validation boundary

Package finalization runs the same training and clock stages for fresh builds
and eligible package upgrades. The training receipt records selected inputs,
source hashes, generated resources, graph bindings and compiled activity links.
Repeated upgrades validate those records and do not add another activity or
duplicate dialogue.

Unit tests exercise arbitrary actor/objective/place names, source request
priorities, resumed arrival, completion suppression, real acknowledgement gates,
dialogue release and partial equipment cleanup. Private package assembly against
the installed source and target data validates native AI schemas, resource
closure and repeated migration. This is not an in-game verification of fighting,
equipment restoration, cancellation or save/load behavior. The receipt retains
`runtime_verified: false` until those playtests pass.

The separate report that Vanyek first arrives at noon remains unconfirmed as a
clock condition. The audit found full-day availability and no two-hour wait in
the converted introduction or source quest. No speculative timing or recurring
position correction is included; see [the introduction audit](quest-intro-entry-order.md).

## Recipe 56 verification

The test suite completed 1,894 tests with 17 skips. The six arena-entry and
scene-release migration tests also passed after adding the unnamed source-link
regression case. A private copy of saved job `20261023-092726-5f44be67` upgraded
to recipe 56 using the actual installed game data. Its only changed tracked
files were the travel archive, level archive, training receipt and new entry
receipt. Repeated finalization preserved all 184 tracked file hashes, and the
original saved package retained all its verified hashes. The aggregate install
receipt may update its per-run `changed` flags; this is separate from game-file
idempotence.

Setup 0.3.20 was built and passed its frozen self-test. Evidence is in
`reports/jobs-completion/trainer-audit/training-entry-upgrade-proof.json` and
`outputs/training-entry-fix/self-test.json`. This build was not installed or
tested in a running game during this verification.

## Recipe 57 introduction and work migration

The source introduction's indefinite bark wait explicitly has
`skipInLOD="false"`. The previous emitter omitted that attribute. The emitter
now preserves the source wait policy, and the completed-package fast path
regenerates and validates the introduction as well as the training handoff.

The source quest controller also disables the actor's perception before faction
setup and worker activation. The old conversion retained the worker's
Disable/EnablePerception pair but omitted this controller-side preparation.
The new native adaptation applies `switch_disabledPerceptionReaction` while the
introduction request is eligible and uninitialized. An `Initialized` callback,
emitted after the whole worker initializer, releases it. Withdrawal of that
request also releases it, including invitation acceptance before initialization.
This context suppresses native reactions; it does not reproduce the source's
full perceptibility change or prove ordering against the engine's scheduler.
It adds no clock cutoff, retry timer or actor position.

Saved-package migration validates the invitation receipt before modifying the
callback event set and updates only that verified node's digest. It does not
accept unrelated graph drift. Table-cleaning and source-linked pub-rest choices
use the same source-driven adapters in fresh builds and saved upgrades; their
remaining dispatcher limits are documented in
[the pub work guide](source-pub-work-upgrade.md).

A private recipe-56 package upgraded to recipe 57 against both installed games.
The repeat upgrade preserved all 184 tracked file hashes and the base package
still matched its receipt. Evidence is in
`D:/BuildKCDMod/intro-preparation-proof-result.json`. These checks establish
package consistency, not a successful in-game trainer or job playtest.

## Recipe 57 combined verification

Setup 0.3.21 includes the introduction/training repairs, pub cleaning and resting,
source-selected gambler work, supported voiced market calls, and source work
ownership reporting. The full suite completed 1,968 tests with 17 skips. The
frozen installer self-test passed with 102 converter imports, worker pools, long
staging paths and the byte-equivalent OptiX probe.

A clean private copy of the verified recipe-56 package was upgraded twice using
the installed source and target data. Both runs passed package validation; all
186 tracked hashes were identical after the second run. The original baseline
also retained all verified hashes. Evidence is in
`D:/BuildKCDMod/source-jobs-final-proof.json` and
`outputs/source-jobs-intro-fix/self-test.json`.

This combined check exposed two repeat-upgrade defects: inherited native dice
types were compared by XML formatting instead of content, and an already-correct
opening clock rewrote unrelated native definitions to normalize indentation.
Semantic type validation and preserving a validated clock's original payload
now avoid both issues. Actual legacy clock migration still rewrites its node.

These checks validate the build and upgrade paths. They do not verify the
trainer's arrival, arena entry, job selection, dice dialogue or ambient playback
in a running game. Unsupported source dispatcher and speech contracts remain
listed in the linked job guides rather than being counted as completed work.
