# Original KCD1 adaptive music

The main converted world now has a dedicated KCD1 score. The converter reads
the original recordings and adaptive scene definitions from the locally
installed game and connects their inputs to KCD2's native music system.
It does not replace native KCD2 recordings or install an FMOD master bank.

## Coverage

- 119 original scenes, including exploration, settlement, weather, hostile,
  combat, minigame and silence/transition scenes. Every copied SQCB directory
  and Ogg payload boundary is validated; recording bytes are unchanged.
- 80 native TriggerArea bindings: the imported-world boundary, registered
  source music locations, and authored audio boundaries for river, cave,
  landscape and supported stealth inputs.
- 24 namespaced address inputs, registered in the native address, world-state,
  matrix and ATL control tables. Overlapping inn and settlement inputs coexist.
- Original settlement assignments come from `entered_location_*` controls in
  KCD1's `Libs/GameAudio/music.xml`, joined to its location IDs and the converted
  location polygons. Coordinates are not inferred from place names.
- Time of day, dialogue, silence, skip time, skirmish, battle, crime and dice
  inputs are adapted to the legacy controller. Detailed combat outcome and
  dice event timing remain gameplay acceptance items.

The 11 source location definitions reported without registered music areas
also have **no membership in KCD1's shipped `whdata_0` location-area list**.
Five legacy location-trigger names have no corresponding source location row.
They are retained in the audit; no replacement boundary is invented.

This covers the supported initial world of the main `rataje` map. KCD1 quest
events, later world-state layers, separate maps and campaign cutscene music
are not reconstructed by this conversion. Copying a battle scene does not
implement the original battle quest.

## Isolation and transitions

KCD2's 1.22 controller remains the host. Original KCD1 scene files are stored
under `Music/kcd/GM_KCD1/`. Legacy variables, macros and scene groups are
namespaced. Native scene selection and continuation are gated while the
imported-world area is active; imported scenes are gated in the opposite
direction. Native menus and cinematic/silence services remain available.

Both the uppercase `E` selection expression and lowercase `e` continuation
expression need this gate. Gating only selection can leave the previous
world's looping music eligible to continue. Authored musical transitions are
retained, so a new region can queue its music instead of cutting immediately.

The generated package contains merged copies of the three native music
tables and the host score. Other mods replacing those same resources require
a merge. Original/native score hashes and every copied recording hash are
included in the build receipt.

## Build and validation

The normal world builder calls `world_music.resources` after environmental
conversion and writes `gluemapper_music.pak`. For a bounded test against an
installed level that does not already contain music areas:

```powershell
python tools/build_music_test.py `
  --source D:/SteamLibrary/steamapps/common/KingdomComeDeliverance `
  --target D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2 `
  --level path/to/baseline/level.pak `
  --output outputs/MusicAudit/NewBuild
```

The staging tool never installs its output. It produces `level.pak`,
`music.pak` and `report.json`, preserves all unrelated level entries, refuses
an existing output directory, and rejects installing music areas twice.
The entity allocator skips the engine's reserved player ID `0x7777`.

On 13 October 2026, development runtime checks verified:

| Position | Legacy location | Highlight | Imported score enabled |
|---|---|---|---|
| Skalitz | `ska` | `off` | Yes |
| Skalitz inn | `ska` | `pub` | Yes |
| Countryside | `off` | `off` | Yes |
| Rattay | `rat` | `off` | Yes |
| Talmberg | `tbg` | `off` | Yes |
| Outside imported-world boundary | `off` | `off` | No |

The live SQC overlay showed original `ATWN2` town music, `BRAT` pub music and
`FL1` countryside music during the development tests. Outside the imported
world, native `B-A-FIELD*` scenes became selectable/continuable and were queued
as the destination. A native-region level-travel round trip and full auditory
verification throughout the map remain open; this is not a claim that every
track, game-state transition or crossfade has been heard and accepted.

Local evidence lives in `outputs/MusicAudit/Build03/` (generated/ignored),
including recording hashes, area provenance and six runtime input probes.
The fresh build reached `LEVEL_LOAD_COMPLETE` and `RUNNING`. Unit tests cover
variable isolation, independent selection/continuation gates, reset on area
exit and parsing the native macro header. The existing audio mapping and
region travel suites also pass.

All soundtrack data is generated locally from installed games and is excluded
from the repository. Only conversion code, tests and documentation are tracked.
