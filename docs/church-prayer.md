# Native church prayer test build

Current installed revision is WorkshopPrayer03; see `docs/workshop-test.md`.
It includes the four altar placements and removes the required-perk restriction
from all six church triggers. The original build notes below describe the older
perk-gated build, not the current interaction requirement.

## Altar placement revision

`outputs/ChurchPrayerAltars01` stages the altar attachment revision. It is not
installed yet. Four existing native pairs are relocated to reviewed altar brush
locations: Rattay upper church, Talburg castle chapel, Sasau monastery and Sasau
church. The invisible interaction target sits on the altar's approach-facing
edge, roughly one metre above the kneeling floor. The kneeling anchor faces the
altar and its animation-table transform is updated with it. Trigger range is
2.5 metres and approach tolerance is 100 degrees. Native perk gating remains.

Rattay lower church and Uzhitz remain at their original authored points below;
separate altar meshes have not yet been identified there. Floor clearance and
prompt targeting at all four relocated sites still require in-game validation.
The Rattay upper floor height was observed in the live church; other placements
use source prayer floor heights and require particular attention to steps.

The builder accepts the already installed prayer build, retaining entity IDs,
links, scheduler registrations and voice files. Structural validation confirmed
only the eight intended entities changed, all four animation transforms match,
mounted tables match, dialogue files are preserved and relocation is idempotent.
The existing game session has not been restarted and shaders/cache are untouched.

The table below records the original prayer points, not revised altar positions.

`tools/build_church_prayer.py` adds native cross-style prayer at six active,
authored source prayer points. It retains the native prayer perk requirement,
interaction label, kneeling behavior, cancellation and prayer dialogue.

| Location | Source point | Position |
| --- | --- | --- |
| Rattay lower church | 12746 | 2491.90, 586.43, 75.39 |
| Rattay upper church | 12824 | 2676.66, 642.28, 100.15 |
| Talburg castle chapel | 9869 | 2336.12, 2756.75, 110.07 |
| Sasau monastery | 11950 | 981.18, 1692.22, 39.57 |
| Uzhitz church | 10157 | 3086.07, 3367.39, 156.92 |
| Sasau church | 12275 | 867.17, 1167.06, 29.33 |

This is an initial six-location build, not automatic coverage of every religious
building. Inactive rebuilding/DLC layers and locations without reviewed authored
prayer points are excluded. Position and facing are taken from those source
points, but kneeling clearance against retained furniture still needs playtesting.

The donor pair is native Trosky 30109/30110: InteractionTrigger and
so_player_prayingSpot. Both entity links and waitinglinks carry prayingSpot.
Native GenU_PrayKneelingGround animation helpers and new transformed animation
rows accompany scheduler registrations. Mounted mod tables match level tables.
No buildings or existing mission entities are removed or changed.

The native prayer dialogue is instantiated under open_world/perky, retaining its
alias, conditions and text keys. All 28 referenced Tom McKay English recordings
were verified. The existing smithing open_world/minihry registration is retained.
Only the prayer dialogue is added, not unrelated native perk or story modules.

Build against the installed smithing-voice build:

```powershell
.venv/Scripts/python.exe tools/build_church_prayer.py --library D:/SteamLibrary/steamapps/common --mod D:/SteamLibrary/steamapps/common/KCD2Mod/Mods/kingdomcomegluemapper --output outputs/ChurchPrayer01
```

The builder stages two packages. Receipt: outputs/ChurchPrayer01/report.json.
Structural validation checked twelve new linked entities, unique IDs/GUIDs,
unchanged existing mission entities, the original perk gates, six animation
registrations, mounted tables and both prayer/smithing voice scopes.

Runtime acceptance remains pending: with the native prayer perk, approach a
listed spot, face the prayer direction and confirm the Pray prompt. Test entry,
spoken prayer, normal exit, cancellation, combat interruption and save/reload.
The native perk requirement was not bypassed or granted to the player.
