# Combat response comparison — 2026-10-11

The user confirmed the same isolated Fritz bandit clone works in native Trosky
after relocation away from the coach camp. The KCD1 comparison still failed.
This increases the priority of destination-world response registration, but
does not isolate one cause: geography, nearby actors, region faction binding
and encounter state also differ.

## Warmonger and morale

Verified against the installed retail English localization and Tables.pak:

- `perk_warmonger`, buff `2db7639e-ace8-4af2-a135-768bbe82f4be`, uses
  `Cpp:Warmonger`. Its parameters add two to strength, agility and combat
  skills; its duration is 21600 seconds. The description says it activates
  after combat ends. The native C++ implementation was not inspected.
- That buff ID appears in the preserved Matthew combat event log at
  `outputs/BuildWork/combat-lock-audit/eventlog_samue_2026-10-10t21-00-02.json`.
  Activation may indicate a combat-state transition, not establish its cause.
- `perk_frightening_presence_desc` explicitly describes increased enemy flee
  and surrender likelihood with armour and a heavy weapon.
- `perk_beast_of_a_dog_desc` describes increased enemy give-up/run-away
  likelihood when accompanied by the dog. The player's ownership of either
  of these perks has not been verified.

## Confirmed native contracts and destination gaps

`AI/crime/surrenderDecision.xml` calls `combat_checkMoraleForCombat`. Its
`combat_disableOffenseAutomation` context wraps an atomic transition invoking
mercy, reporting or flee interrupts. The existence of this context is not
proof that it was active in the failed encounter.

`AI/npc/basic/switch/interrupt_mercy.xml` applies surrender/withdraw-skirmish
contexts. It contains waits on inbox `crime_mercyDialogueResult` with timeout
-1, alongside other behavior branches. The sender/binding for that dialogue
result still requires tracing; a stalled wait has not been observed live.

`AI/crime/fleeLeaveLevel.xml` searches children of `$__land` with category
`levelExit`, with `failOnEmpty=true`, then moves toward the nearest exit.
Native Trosky has eight `levelExit` links on `sa_land` (and nine exit-category
entities in the main mission, including a quest-specific point). The installed
KCD1 destination has zero exit-category entities and only `mrkev`/`redkev`
links on `sa_land`. Thus the leave-level flee dependency is actually missing.
Ordinary flee is a different branch and does not necessarily require exits.

Native world links also include emergency points, punishment services and a
player link rerouter. Their absence is not independently proof of the combat
lock's cause. Source-region coordinates and quest targets must not be copied
verbatim to resolve these dependencies.

Next implementation should translate authored KCD1 escape destinations and
trace the mercy dialogue producer/registration, then test the transition with
the same Henry save/perks. Preserve perk effects and native surrender behavior;
do not hide missing services with forced aggression or never-surrender flags.
No game/mod behavior was changed during this audit; the standalone Trosky
test remains enabled.
