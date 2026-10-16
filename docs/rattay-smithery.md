# Native Rattay blacksmithing test build

The optional builder `tools/build_rattay_smithery.py` swaps the equipment at
both authored Rattay workshops for KCD2's native small smithy setup. The original
buildings, surrounding scenery and other workshops remain in place.

Locations (source forge IDs):

- 62317: approximately (2540.18, 526.87, 76.29).
- 62236: approximately (2677.38, 662.61, 99.69).

The rigid transform fits the original heating and hammer contact positions to
the exported Tachov station. Residuals are 5.98 cm and 0.37 cm respectively;
characters and animations are not scaled. Native equipment is placed from the
small/base prefabs around the transformed alignment point. This replaces the
original furnace, anvil, quench tub, adjacent tool barrel and decorative hammer.
The native animated bellows, tongs, hammer, coal, effects and light accompany
the station. The six replaced static brushes are removed from HLOD blocks;
block sizes/offsets are rebuilt while retaining all other record bytes.

Each station has the native `Smithery` interaction and its complete linked
minigame dependencies, including the smart object and player clearance point.
New persistent identifiers and remapped links avoid references back to Tachov.
The clearance point's Tachov merchant links are omitted: this does not create a
shop, merchant, quest or NPC job. Reservation links, scheduler hubs and native
animation collections are registered at the new positions. The mounted mod
animation/scheduler tables match the copies inside the level archive.

The game supplies the normal blacksmithing recipe, ingredient, skill/perk,
quality and XP logic. This build does not unlock recipes or bypass eligibility.
Kingdom Come Connect is outside its scope.

Build against the installed development mod, with the game closed:

```powershell
.venv/Scripts/python.exe tools/build_rattay_smithery.py --library D:/SteamLibrary/steamapps/common --mod D:/SteamLibrary/steamapps/common/KCD2Mod/Mods/kingdomcomegluemapper --output outputs/RattaySmithery01
```

The builder stages packages; it does not install them. It rejects an already
converted level, missing original equipment and incompatible contact layouts.
Preserve both original packages, verify receipt baseline hashes before copying,
then copy the two staged packages to their matching mod paths while closed.

On 16 October 2026 the two packages were installed with matching SHA-256 hashes.
Receipt: `outputs/RattaySmithery01/smithery.json`. Backups are in the same
directory under `backup`; restore both only if no subsequent changes need
preserving. Validation: 66 new entities, two Smithery objects, all internal
links resolve, unique entity IDs/GUIDs, eight native model paths present in the
development installation, 33,096 unrelated mission entities unchanged and
1,483,225 vegetation records retained. Two focused HLOD tests pass.

Runtime acceptance is pending. Load the Rattay area in the development game,
approach the native anvil and check for the blacksmithing interaction. Test
recipe selection, heating, hammering, quenching, item creation/XP, cancellation,
then saving/reloading. Check clearance against the retained shed and nearby
props. A successful package build is not proof of a completed craft. The game
was launched normally from the development executable, without map or teleport
arguments, after installation.
