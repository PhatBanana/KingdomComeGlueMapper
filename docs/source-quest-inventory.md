# Imported quest-item ownership

Recipe 25 removes imported quest-item rows from ordinary NPC inventory presets.
KCD2 rejects these rows, ordinary `Inventory.CreateItems`, and ordinary
`ItemUtils.GiveItem` transfers for classes marked `IsQuestItem`.

The converter emits native `AddQuestItem` effects with mutually exclusive,
persistent ownership states. Initial ownership is gated by the existing New Game
started state. Each supported source dialogue handover emits a trigger from its
original sequence, propagated through its containing graphs to change ownership.
Unrelated script statements and source acquisition objectives are preserved.
Quest flags are not cleared. No reward GUID, actor name or quest name selects the
repair.

The backup holder is resolved from the source `lostQuestibleItems` world-stash
link and the corresponding converted Stash. The importer binds it in both
EntityLinks and the native waiting-link network. A soul is not a valid permanent
backup holder. Missing or ambiguous stash, graph parent, actor role, or initial
ownership causes conversion to fail with a dependency error.

Both clean setup finalization and resume migration use this stage, after dialogue
format and branch-continuation conversion. Recipe 24 and earlier supported builds
can migrate; the rejected recipe-24 CreateItems nodes are removed. A packaged
manifest retains original and lowered scripts so repeated upgrades are
idempotent and unexpected source changes are detected.

Supported scope is direct carried NPC quest inventory and standalone literal
handover calls forming a unique, non-cyclic ownership chain. Weighted inventory
choices, conditional/compound quest transfer statements, non-singular handovers,
ambiguous ownership and cycles fail explicitly pending a semantic adapter.
Native quest items are unique: a positive integral source quantity range becomes
one managed item, with the original range recorded in the report. Ordinary items
retain their inventory quantity policy. This is not an arbitrary world-container
or live-save repair; saves that already consumed a failed handover need a fresh
New Game for validation.

Unit tests cover native ownership, ordinary loot and script preservation,
source immutability, trigger propagation, repeat upgrades, and unsupported-policy
rejection. The AddQuestItem contract is checked against the selected game's
shipped definitions. Package conversion and tests do not establish in-game
handover success: reports retain `runtime_verified: false` until playtesting.

## New-game torch — 23 October 2026

Recipe 51 appends one native `torch_weapon` to Henry's existing once-only
new-game loadout chain. The item is resolved from the installed KCD2 item table
and must have the native Torch entity script. It is unequipped and does not
reset or replace the source inventory. Loading an existing save does not grant
another torch. Clean setup and transactional package upgrades use the same
adapter, with conflict checks and repeat-upgrade validation.

Automated graph tests cover the new-game insertion, inventory parameters,
repeat application and conflicting bindings. The resulting package has not
been tested in a running game.
