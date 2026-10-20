# Source-profile population and stores

`tools/build_profile_population_upgrade.py` stages the people and stores selected
by an authored KCD1 static profile. It uses the existing appearance, inventory,
world registration and job adapters. NPC names are not an import allowlist: the
profile selects placements and souls, and `shop/shopkeeper` selects their shops.

The first bounded build uses `q_skalitz_normal`. This is the opening population,
not every actor that appears in Skalitz during later campaign states. Conditional
profile activation, departures and destruction remain separate work.

## Build

Run from the repository with both installed games available:

```powershell
.venv\Scripts\python.exe tools/build_profile_population_upgrade.py `
  --source D:\SteamLibrary\steamapps\common\KingdomComeDeliverance `
  --target D:\SteamLibrary\steamapps\common\KingdomComeDeliverance2 `
  --baseline D:\SteamLibrary\steamapps\common\KingdomComeDeliverance2\Mods\kingdomcomegluemapper `
  --output outputs\population-test `
  --profile q_skalitz_normal
```

The output directory must be new and outside the source, target and baseline.
`--profile` is repeatable; `--source-level`, `--level` and `--entry` select the
source world and destination. The command creates a complete staged `package/`,
updates its installation receipt, and writes `report.json` and `work-report.json`.
It does not install or launch the game. Setup recipe 36 invokes this builder
through `setup_profile_population` after static navigation is materialized and
before native animals are validated. Clean builds and resumed setup use the
same finalizer. Only newly generated or changed files are published; unchanged
world archives and the finalizer's receipt remain intact. The setup receipt
requires the selected profile and scheduler-validation proof before installation.

The optional `--actor-stage` reuses a previously built actor stage only when its
profile roster and baseline hashes match. Rebuild actor stages produced before
the texture writer correction; no texture migration is performed. Default setup
builds missing actors directly through the corrected writer.
Unchanged assets are hard-linked into
the stage; all PAK and receipt updates replace files atomically. Repeat upgrades
preserve existing actors and stores, validate their actual world/table bindings,
and retain unresolved work reports rather than reporting those routines done.

## General conversion rules

- Stage each selected soul once, with its source placement, appearance,
  equipment, home links and native interruptible NPC activity framework.
- Preserve existing NPCs and their quest graphs. A missing placement, ambiguous
  keeper or unresolved item dependency stops conversion.
- Resolve shop work through the source area's `merchantPoint` link. The area's
  `inside` point can be different and must not be used as its selling location.
- Replace `final/sa_shop2.xml:merchant` with the installed KCD2
  `so_seller/seller_market` activity. Validate that it owns exact movement and
  `shop_sellerReadyToSell`. Native shop ownership and source business hours
  control service availability; no permanent readiness context is injected.
- Convert all directly linked shop storage, including multiple chests. Preserve
  existing converted containers, independent loot, keys, locks, transforms and
  `iMinimalShopItemPrice`. Stock is not a substitute for a chest's independent
  inventory.
- Preserve stock quantities and prices. Convert missing item dependencies using
  typed adapters. Repair kits map ointment type/subtype by semantic names rather
  than source ordinals, retain efficiency, and use a matching native repair-kit
  icon instead of the first unrelated ointment icon.
- Source-only voice identities must have the required Skald character fields
  (`age`, `body_type`, `gender`, `unique_assets`). If source biography metadata
  is absent, use a complete shipped generic commoner classification matching
  the converted human archetype. Record this approximation in `voice_binding`;
  it does not replace the actor's appearance or add recordings. Unknown
  archetypes fail instead of receiving a guessed identity.

KCD1 weekday restocking is not equivalent to KCD2's elapsed-day interval. Daily
stock retains a one-day interval. Non-daily stock uses the installed native
`common_merchant` period only under the explicit `native_merchant` policy, and
the report retains the source weekday mask and records that it is not preserved.
This is a documented compatibility policy, not exact weekday conversion.

## 2026-10-20 staged coverage

The opening profile resolves to **55 people**: 43 added, 12 already present.
All 19 previously installed NPC entities, including actors outside this profile,
were preserved. Seven source shops are present:

| Source shop | Source keeper | Stock rows | Result |
| --- | --- | ---: | --- |
| `ska_shop1` | `ska_merchant1` | 7 | Added |
| `ska_shop2` | `ska_merchant2` | 15 | Added |
| `ska_shop3` | `ska_merchant3` | 35 | Added |
| `ska_shop4` | `ska_merchant4` | 16 | Added |
| `ska_trader` | `ska_woman20` | 35 | Added |
| `ska_collier` | `ska_collierVarlet` | 2 | Preserved |
| `ska_pub` | `ska_blanka` | 31 | Preserved |

The five new shops have seven physical storage containers, including the
grocery shop's three distinct chests. Four shops use the explicit native
seven-day restocking policy; the first retains daily restocking. Source shop
hours are 06:00–21:00.

Five new merchant activities and eleven additional supported jobs were bound
(nine sweeping jobs and two fixed guard posts). This is **not full routine
conversion**: those eleven work programs still have secondary phases pending;
27 other new people have incomplete or unresolved routines (19 unsupported
programs, six unresolved schedules and two dynamic garrison assignments).
Their source work details remain in the report. They retain the base NPC
activity framework rather than fabricated patrols or teleports.

Existing quest dialogue is preserved, and new shop trade topics use native
merchant dialogue. This stage does not import every new person's voiced
conversations, greetings or linked side quests.

## Validation boundary

The 75-test focused regression suite covers profile selection, actor identity,
merchant points, native readiness, plural storage, independent loot, repair
items, complete voice records and atomic receipt replacement. The actual staged
data passed the official Mod Tools `GeneratedDatabase.dll` reader for all
**398 new or changed database XML files**. Structural checks verified all 55
people, seven shop/stock/keeper bindings, scheduler targets and the mounted
scheduler alias. Another 97 character tests passed. Existing archive members and
baseline hashes were preserved. A real repeat upgrade added zero actors and
zero shops; all engine payloads were byte-identical, with only the population
report changing. The final package receipt covers 179 files.

After the texture packaging correction below, the user confirmed the installed
retail build loads. That is load acceptance, not validation of every new NPC's
routine. Shop opening/closing, trade, stock, chest ownership, navigation,
interaction interruptions and longer-term performance still need playtesting.
Do not label this as a completed town AI or quest port.

## Retail load failure: actor texture packaging

The first 43-person installation crashed during New Game with `Suspicious
alloc. Alloc size 1073741824`. Its private retail shader runtime's `kcd.log`
reported 53,886 MiB system commit against a 54,477 MiB limit, only 590 MiB
available commit, and 23,929 MiB game private commit. Database loading had
completed. This establishes memory exhaustion, not a corrupt database table.

`build_quest_people_test.write_actor_paks` wrote appearance files straight to
ZIP32 archives. Unlike `campaign_package.write_asset_shards`, it never called
`texture_streaming.generated_entries` or `checked_entries`. Generated half-float
clothing textures and blood/grime masks therefore bypassed the already tested
native streaming layout when actors were added after the main build. Some
individual DDS files were 178,957,116 bytes. The 43 new appearances referenced
26,402,489,072 bytes of texture **base files**; this is an asset inventory, not a
measurement of simultaneous GPU residency. Identical texture copies also exist
across body regions and actors; that is a separate optimization opportunity.

The actor writer now uses the shared texture streaming and family validation
functions before sharding. Generated high-resolution mip payloads use external
numbered slices; full-resolution pixels, texture precision, material references,
skins and gameplay data are retained. Generated byte-channel masks receive the
missing lower mip chain. Existing source streaming families remain unchanged.

`campaign_scene_test.appearance_resources` also uses this shared DDS writer for
the opening-scene actor embedded in the travel archive. This corrects setup at
generation time. Per the requested scope, no texture-repair migration or scan
of existing actor archives is added to the package upgrader.

Regression tests in `test_character_asset_packaging.py` cover half-float and
generated mask payload preservation, cross-shard families, missing/truncated
payload rejection, unchanged geometry/materials and opening-scene packaging.
Setup tests cover profile finalization, receipt ownership, cancellation,
preservation of hard-linked baselines and rejection of incomplete builds.
The user confirmed the repaired retail build loads; no post-repair memory
benchmark or full town behavior verification is claimed.
