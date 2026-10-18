# Source merchant purchase conversion

The immediate playtest is the Skalitz charcoal purchase for Unexpected Visit.
The merchant builder accepts an actor, namespace and destination level; it does
not inject quest-specific item grants, completion callbacks or actor positions.

## Stock correction

`region_travel_services.resolve_stock` previously treated `default_on=False`
as a disabled stock row. This incorrectly emptied source shop 17 (type 14).
The source rows contain 50 charcoal and 200 money, with both flags false.

Read-only inspection of the installed KCD1 `WHGame.dll` shows:

- RVA `0x12a6cf4` collects every matching shop-type row, multiplies its amount
  by the shop multiplier, and copies the boolean into the stock record.
- RVA `0x12a98d4` moves that vector into the shop at offset `0xa8`.
- RVA `0x449db4` iterates every stock record when restocking.
- Its cold block at RVA `0xc7ec52` turns the boolean into item-creation flag
  `0x8000`; it does not skip creation when the boolean is false.

The importer therefore must not use this field as an inclusion predicate.
The meaning of that item flag is not required by this purchase test, which uses
false for both rows. Random stock multipliers remain explicitly unsupported.

## Source relationships

The source shopkeeper table assigns shop 17 to `ska_collierVarlet`. His authored
work link selects `varlet_sellPlace` on the quest controller. That tree searches
one `QuestPlace` edge, moves to and aligns with the result, then waits indefinitely.
The generic station adapter recognizes this exact operation structure, resolves
the source edge and emits native ExactMove/Wait operations. It rejects more
complex work rather than substituting an idle routine.

The shop opens from 06:00 to 21:00 using native scheduler shop lifecycle effects.
Its linked `ska_collierStash` is a Stash with a coal-pile model, not a chest.
The builder imports that relationship and owner link; it does not guess storage
from an object name or assign a separate loot preset to duplicate shop stock.

The existing converted quest tracks ten items of class
`f879ac63-2ce2-4114-83a2-89643c1ed102`, the native charcoal class in the shop.
The user confirmed the installed purchase test works on 2026-10-19. Automated
validation separately checks stock, objective item identity, scheduler links,
archive integrity and preservation of existing quests.

Setup recipe 29 calls `setup_merchant_upgrade.upgrade` from the shared package
finalizer, covering fresh builds and transactional resume/upgrades. Recipe 28
and older supported receipts remain eligible for migration. The same generic
actor and merchant builders produce the service; the setup selection only names
the source actor and namespace. Existing verified test packages are adopted by
their marker after checking required service resources, without creating a
second seller. Temporary staging lives beside the build and is consumed/removed.

This bounded service build does not claim conversion of the two forest workers'
later quests. Those broader actor/dialogue changes remain separate work.
