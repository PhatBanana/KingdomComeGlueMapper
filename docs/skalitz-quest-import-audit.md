# Skalitz quest import audit

Evidence: installed KCD1 data, setup build `20261018-053039-699747cf`, and
the Mod Tools `kcd.log` from the Kunesh fight test on 2026-10-18.

## Confirmed importer omissions

* Dialogue sequence 10138 originally calls
  `Utils.GiveItem(dc.KUNES,player,'bd8a4e0f-7b5d-4f6a-9546-4b71ffe6fa68',1)`.
  The live log reports `attempt to index global 'Utils' (a nil value)` and
  `Execution of script in dialog failed`. Native `ItemUtils.GiveItem` has the
  same transfer/assertion/notification contract. Imported role names must also
  replace the source `dc` participant reference.
* Kunesh's source inventory `4322cd89-de61-9763-0edc-04614468debe` contains that
  key. The NPC importer previously imported only clothing and weapon presets,
  omitting carried inventory. A working transfer API cannot transfer an absent
  item. The shared NPC converter now composes the authored carried inventory
  using the existing loot-preset converter, including source random quantities.
* The source `takeAllFromKunes` condition is
  `IsObjectiveCompleted('q_skalitz','allThingsTaken')`; the alternative debt
  objective checks `allThingsStolen`. The quest compiler retained these as
  unsupported completion policies. It now compiles local objective predicates
  and rechecks them on objective start and dependency state change. No quest
  names, objective names, item grants, or fight outcomes are hardcoded.

Recipe 17 applies the verified script/condition/inventory repairs to existing
packages as well as clean builds. Inventory migration changes actor initialization
presets, not live save contents. Runtime verification is still required.

## Quest-world dependencies still missing

The source charcoal service is a connected group:

* Actor `ska_collierVarlet`, source entity 121275, is in a layer enabled by
  `q_skalitz_normal`. It is absent from setup's explicit actor selection.
* `ska_collierShop`, source entity 120875, is a Shop with source shop ID 17.
* Its linked stash is `ska_collierStash`, source entity 120877. Its model is
  `Objects/props/coal/coal_pile_c.cgf` and its placement is
  `770.53235,3480.1978,51.862061`.
* Both service objects are in `q_skalitz_questItems`. The ordinary container
  inventory selects initially active layers and therefore omits this stash.
  The stash has no authored ordinary inventory preset (`guidInventoryDBId=0`);
  creating an empty ordinary stash would not restore the shop stock.
* The source quest behavior calls `Shops.OpenShop(17)`. This needs the service
  definition, stock, keeper, source activation and ownership conversion together.

Kunesh's ordinary chest, entity 102360, is already converted. Its source preset
contains the quest nails and hammer. The original behavior also changes ownership
of his belongings and calls `SetLootLegal(true)` after permission is granted.
The ordinary-container importer currently omits ownership links. Restoring only
the chest/pile visuals cannot restore theft or the permission transition.

Do not mark the whole quest ready based on the recipe-17 repairs. The remaining
work is a source-profile/quest dependency closure through the existing entity,
shop, inventory and ownership adapters, with explicit lifecycle handling. Do not
replace it with a charcoal spawn, forced objective completion, or free inventory
grants to the player.

## Objective event lifecycle (recipe 18)

The source onUpdate QuestMailbox handler completes getDebtMoney when
kunesSolved completes and conditionally cancels takeAllFromKunes/getLockpick.
Without this handler the parent objective and its D marker remain active even
when the visible belongings objective completes. The shared importer now
translates whole local objective-event branches with supported objective guards
and ordered mutations. Unknown operations or enclosing conditions reject the
branch; this is not a marker-hiding override. Clean builds and existing-package
migration both use this adapter. Native playtest remains pending.
