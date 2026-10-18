# Retail campaign initialization

Retail New Game was verified by the user on 19 October 2026 after replacing
the 34 imported debug stat/skill setters with native `I_Soul` member functions:
`AdvanceToStatLevel` and `AdvanceToSkillLevel`.

The importer previously accepted `SetStatLevelDebug` and `SetSkillLevelDebug`
because they appear in retail `definitions.xml`. Their names were absent from
the inspected retail WHGame binary, despite being present in the Mod Tools RPG
module. Definition availability alone is not proof of retail execution support.
The startup chain depended on those calls completing before starting the quest.

Fresh builds now emit the native member functions. Recipe 30 upgrades existing
recipes, including recipe 29, through the same generic initializer migration.
Migration preserves node names, source values, soul bindings, trigger edges,
and the persisted New Game/region-readiness guard. It requires the target game's
native ABI and is idempotent. Final content validation rejects remaining debug
stat/skill setters in the opening project. World conversion and lighting baking
are not required by this repair.

The level policy is explicitly `advance_to_minimum`: native advancement does
not lower a higher inherited level. The successful quest-start test does not
establish exact source starting-stat parity. Existing-player travel must continue
to bypass initialization.

The temporary retail trace was removed. Its `ExecuteConsoleString` callback
was found to immediately return in retail, so absent graph trace messages were
not evidence that startup events had failed to fire. No diagnostic nodes are
included in setup or the upgrader.
