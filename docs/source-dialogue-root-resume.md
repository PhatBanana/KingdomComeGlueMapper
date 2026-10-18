# Source dialogue root continuation

Recipe 23 restores a bounded part of the shared dialogue selector that was lost
when multi-person KCD1 branches became separate KCD2 ForcedDialog nodes.

The observed guard run played topic 7691 through sequence 11052 and then ended
the scene. Topic 14861 never started. Its original sequence 24855 owns the
crossguard transfer script. Janek's generated equipped preset already references
the source inventory containing that item, and KCD2 ItemUtils.GiveItem has the
same inventory-transfer contract as KCD1 Utils.GiveItem.

Source branch 7691 has priority 1; branch 14861 has priority 2 and becomes eligible
when crossGuardMultilog is completed. Source sequence 11052 has next=0, flags=0:
it returns to topic selection rather than explicitly ending the dialogue. The
multi-person adapter discarded branch priority and exposed each branch through
a separate Talk interaction. The handover therefore was not selected as part of
the first conversation's return to the source root.

`campaign_branch_resume` reads source topic aliases, branch declarations, and
sequence endings. It converts only a uniquely determined higher-priority,
mandatory branch with exactly the same runtime participants. A returning source
sequence must demonstrably invalidate a negative objective-completion condition
on its own entry; repeatable questions are excluded to avoid loops.

The sequence emits a return event into a native SceneFinishedWaiter. After the
scene releases, graph-readable successor prerequisites are evaluated again and
the existing ForcedDialog is enqueued with its existing participant parameters.
The successor retains its own native sequence-history check, voices, script,
objective effects, and audio namespace. The adapter does not award items or mark
objectives complete. Ambiguous successor families and unsupported conditions
require further conversion rather than guessed routing.

Setup's shared finalizer applies the stage to clean builds and resumed packages.
Recipe 22 packages are eligible for migration, using the existing build folder.
The adapter is idempotent. Synthetic tests cover renamed identities, scene-release
ordering, retained effects/audio, source prerequisites, repeat migration, explicit
dialogue ends, non-invalidating branches, unrelated participants, and ordinary
priority-zero branches.

Runtime acceptance still requires playing the conversation, receiving the item,
and seeing the objective complete. Already-played branch history remains owned
by the native dialogue system. Migrating a save that has already passed the first
conversation does not replay the missed return event; test from before that
conversation (or a fresh New Game). This is not a general cinematic/daycycle
controller conversion.
