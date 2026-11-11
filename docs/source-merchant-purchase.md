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

## Resident keepers outside the static profile

`setup_merchant_upgrade.MERCHANTS` also selects keepers who live in the world
outside the static Skalitz profile. Each entry names the keeper and the
namespace the profile builder would derive for the same source shop
(`gm_source_shop_<source shop id>`, shop id `20000 + source id`), and the stage
refuses a keeper whose source shop is a different one. All pending keepers share
one actor stage and one overlay.

These keepers have a real daycycle, so the service builder accepts one more
shape than an all-day seller: a selling activity plus a night at home. The home
night has no activity link in the source (the brain resolves it from the `Home`
link), so the schedule planner reports it as pending.
`source_merchant_daycycle.selling_schedule` moves exactly that case aside and
`bind_sleep` hands the keeper to the shared sleep extension after the staffed
hours are registered. A keeper without a converted bed fails the build. Any
other unlinked activity (`morning`, `fun`, `eat`) still fails as an unresolved
schedule, and so does a workplace that is not a selling point (smithy, bakery,
tailory, pub): those need their own work adapters.

A weekday restock mask uses the installed KCD2 `common_merchant` period, as it
does for profile shops (`restock_policy='source'`). Stock that has to be
imported keeps its item tables in `gluemappertravel.pak`, but its meshes and
textures go to `Data/<namespace>_assets[_NN].pak`, stored ZIP32 shards below
1 GiB (`source_merchant_assets`). The Rattay armourer alone imports 41 items and
5.3 GB of textures, which must not enter an archive every later stage rewrites.

A shop stash that the world container stage already converted is reused as
`gm_container_<source id>`; the builder only adds the `shopStash` and `owner`
links.
