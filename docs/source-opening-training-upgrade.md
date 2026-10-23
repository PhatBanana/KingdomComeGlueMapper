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
2. Source dialogue authorizes the lesson.
3. Departure availability ends and a registered equipment activity starts.
4. The worker equips converted practice items and releases the prior action.
5. The readiness callback and actual dialogue release permit native training.
6. Completion or cancellation stops readiness before cleanup.
7. Only successful cleanup may advance the source completion objective.

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
