# Open gates testing override

`tools/build_open_test_gates.py` stages an optional override against the reviewed
installed development map. It is not part of normal campaign state selection.

The override lifts three blocking pieces by four metres:

- Talburg palisade gate, source entity 124019, near (2346.54, 2828.61).
- Skalitz castle portcullis near (665.93, 3467.76).
- Skalitz inner portcullis near (725.80, 3473.85).

The Skalitz changes update the actual static-brush transform, its world bounds
and the containing HLOD radius. Other uses of the same mesh remain unchanged.
The Talburg gate remains a static testing prop raised above the passage; this
is not a conversion of its opening animation. Talburg's drawbridge already has
a horizontal deck in the imported model and is unchanged. Surrounding walls,
gatehouses and other town gates are unchanged.

Build example:

```powershell
.venv/Scripts/python.exe tools/build_open_test_gates.py --mod D:/SteamLibrary/steamapps/common/KCD2Mod/Mods/kingdomcomegluemapper --output outputs/OpenTestGates01
```

The staged level preserves 1009 unrelated archive entries. Two focused tests
check that only selected brush transforms/bounds change and reject an already
modified or wrong-mesh baseline. Installed to the development mod on 16 October
2026 with a verified hash; report: `outputs/OpenTestGates01/gates.json`.
Player passage still requires in-game confirmation. AI navigation was not rebaked.
To undo this specific override, restore the preceding TalburgRepair01 level.pak
while the game is closed, provided no subsequent level updates need preserving.
