# Rattay miller test

Peshek (`rat_pesek`) uses his original KCD1 soul/instance identity, appearance,
clothing, shop position, work point and household. The shop is a native KCD2
Shop with an owner-inventory preset and the tested Trade → OpenShop dialogue
handoff. It is packaged inside `kingdomcomegluemapper`, not a separate mod.

## Schedule

The source soul's daycycle supplies the times; no fixed coordinates or times
are embedded in the adapter:

* Work: 06:39–22:49, using the source mill's nearest authored leaning point.
* Sleep: 22:49–06:39, using the non-player household bed upstairs.

Midnight is split into two native scheduler windows. Work opens the merchant
service through native scheduler initializers. Sleeping uses the native bed
`use` activity with the `sleeper` role, its bed/trigger links, scheduler effects
and animation helpers. Bed alignment is derived from source/native helper
transforms. Henry's marked downstairs bed is excluded.

Theresa and Peshek share an existing home polygon. Comparisons are normalized
to the FUBAR float32 storage format before deciding whether geometries conflict.

## Explicit test-world differences

KCD1's miller stock starts disabled and its original quest can disable trading.
This test enables the source quantities of 20 lockpicks and 10,000 money units
immediately. Lockpicks and money use their existing native KCD2 item IDs;
native prices and the source shop buy/sell multipliers are retained.

The test shop restocks daily. KCD1 weekday mask `9` is not converted to an exact
KCD2 weekday policy. Three source skill-book IDs lack shared native item IDs;
they are omitted and listed under `pending_stock` in the build receipt.

The daily work/sleep boundaries are converted. Mill machinery, carrying,
sweeping, original quests, skill training and stolen-goods service rules are
not converted. This is not a claim of full Peshek behavioral parity.

## Build and validation

The regular `region_travel.build` includes the miller. To stage the same feature
onto an existing combined test mod:

```powershell
python tools/build_miller_test.py `
  --source D:/SteamLibrary/steamapps/common/KingdomComeDeliverance `
  --target D:/SteamLibrary/steamapps/common/KCD2Mod `
  --mod D:/SteamLibrary/steamapps/common/KCD2Mod/Mods/kingdomcomegluemapper `
  --output outputs/Miller/Build02
```

Use a fresh output folder and a baseline without Peshek. The builder rejects
duplicate registration. Validate `validation/` using
`tools/validate_database_tables.ps1` under PowerShell 7. Shut down the game
before replacing the four files from `package/`; retain their original hashes
and backups. The builder does not modify installed files itself.

The first staged build passed all 440 repository tests and 18 native database
readers, including scheduler and smart-object animations. Package auditing
found no removed entries or new duplicate entity IDs/GUIDs. The only existing
entity changed was the LevelHolder, to add the shop asset link.

## Gameplay acceptance still required

1. Talk to Peshek at Rattay mill and open Trade. Buy lockpicks; verify money and
   inventory changes, close and reopen the shop.
2. Walk away and return; verify shop availability and ordinary NPC reactions.
3. Cross 22:49 and watch him reach the upstairs bed. Cross 06:39 and verify he
   returns to work and can trade again.
4. Save/reload at work and asleep, then travel away/back. Confirm no duplicate
   actor, preserved purchased items and a functioning merchant.
5. Check the existing Theresa/home, inn, horse trader and quest interactions.

Database validation and startup logs do not prove these runtime behaviors.
