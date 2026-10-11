# Neuhof horse purchase development test

This opt-in test builds on an **existing combined mod**. It does not regenerate
terrain or replace the user's world with another build. It is not enabled in
the retail setup/release workflow yet.

```powershell
python tools/build_horse_trader_test.py `
  --source D:\SteamLibrary\steamapps\common\KingdomComeDeliverance `
  --target D:\SteamLibrary\steamapps\common\KingdomComeDeliverance2 `
  --mod D:\SteamLibrary\steamapps\common\KCD2Mod\Mods\kingdomcomegluemapper `
  --output D:\KingdomComeGlueMapper\outputs\HorseTrader\CurrentBuild
```

The output must be a fresh directory. It contains staged package replacements,
database XML for the native validator, and `horse-trader-report.json` with
baseline/package SHA-256 hashes. Never replace PAKs while a game/editor has them
open. Retain a verified baseline on D: before installing staged replacements.
For the initial installation, the unchanged retail mod has identical baseline
hashes; `installation.json` records it as the restore source without duplicating it.
The added appearance PAK belongs inside the existing mod's Data directory.

## Data and behavior

- Zora (`neu_zdena`) uses her imported appearance/clothing and original position:
  `3552.9197,1521.5421,128.5`.
- The ten sale horses come from KCD1's `Horsetraders.lua` Neuhof roster, not a
  list inferred from names. Soul IDs, names, world placements and base stats
  come from the original soul/world/localization records.
- Horses use the KCD2 native sale-horse brain/class and a native compatible
  appearance. **Original horse coats are not converted in this test.**
- Dialogue calls native `Shops.DoMoneyTransaction`, using decigroschen, then
  triggers native `horseinstance` / `ReplacePlayerHorse`. The native flow trades
  in and disposes of the previous horse; it is not a multiple-owned-horses system.
- Pricing/trade-in uses KCD2's derived stats, not guaranteed KCD1 prices.
- A separate shop/stash, native staffed-shop scheduler, native companion
  aliases, and compiled sale-area polygon are registered in the destination.
- Original stable work/sleep schedules, haggling and washing cinematics are
  not included. Horses and Zora have native interruptible idle scheduling.
- This is a registered world population, not a Lua spawn-on-whistle workaround.

## Test procedure

Start the development client with the updated package and enter `kcd1_travel`.
For quick access, `goto 3554 1519 129` is near Zora's source position. Talk to
Zora, select a horse, then choose the payment/trade-in option. The horses stand
in their original paddock roughly 150–190 metres northeast of Zora.

Check a cancelled purchase and insufficient money before spending money. Then
check a successful purchase, the exact balance change, riding/dismounting, X
recall from a distance, and ownership/equipment after save/reload. Also check
trading in an already owned horse and round-trip regional travel. Use a test
save. Native database deserialization and unit tests do not establish these
runtime results.

`GLUE_HORSE_SALE event=payment` logs the chosen source horse and signed amount.
`GLUE_HORSE_SALE event=talk` logs the current owned horse, entity ID and location
when the dialogue opens. Reopen the dialogue after buying to inspect ownership;
the payment log alone does not prove the companion transfer completed.

## Validation on 2026-10-11

All 374 unit tests passed. All 14 staged database tables deserialized with the
mod tools' official `GeneratedDatabase.dll` reader. Additional checks verified
native soul ID uniqueness, world soul/entity identities, compiled scheduler
targets, the sale polygon, graph definitions/assets, and dialogue Lua syntax.
The package preserves existing scenery entries. Zora's 417 appearance assets
are namespaced below `objects/characters/gluetravel/gm_neuhof_zora/` and do not
replace native shaders or materials. Installed file hashes match the stage.

This validates packaging and references, **not successful in-game purchasing**.
