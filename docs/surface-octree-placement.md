# KCD2 surface placement (PR #42 follow-up)

The original PR put roads, decals and water into the deepest **existing** cell
that contained their entire bounding box. Native Trosky does not use that rule.
The replacement uses centre selection and the size/view-distance stopping
conditions, checked against native level data.

## Rules

- Stop at an 8 m cell or when the object radius reaches 1/16 of the node radius.
- Stop when maximum view distance reaches node radius times
  `e_ViewDistRatioVegetation` (default 30).
- Stop if the object's centre is outside the current cell.
- Otherwise descend by centre: X selects bit 4, Y bit 2, Z bit 1. Equality with
  the splitting plane selects the low half. Create missing children.
- Objects may cross cell boundaries. Serialized cells remain spatial cells;
  the engine rebuilds aggregate object bounds during loading.
- Use float32 arithmetic for the placement comparisons.

The offline policy uses the following defaults: `e_ViewDistRatio=60`,
`wh_e_ViewDistRatioRoad=28`, `e_ViewDistMin=5`. Decals use scaled first-column
length times 0.75; water uses its serialized bounds radius; roads use their
distance setting. Per-instance view byte 255 is the exceptional 100x multiplier.
View distance and the separate nonlinear LOD byte are different properties.
No per-instance bytes or player graphics settings are changed.

## Evidence and limits

The audit compares the complete octant path, not just node depth:

| Native world | Record type | Matching / total |
| --- | --- | ---: |
| Trosky (`trosecko`) | Roads | 11,343 / 11,343 |
| Trosky | Water | 115 / 115 |
| Trosky | Decals | 37,853 / 37,886 |
| Kutnohorsko (second corpus) | Roads | 40,672 / 40,672 |
| Kutnohorsko | Water | 401 / 401 |
| Kutnohorsko | Decals | 64,838 / 65,049 |

All differences are decals with view byte 255. Saved native placement does
not reproduce the current policy defaults for those records.
The original compilation settings and cached view distances are not available
in the terrain archive. Do not describe this as a byte-for-byte reproduction
of the native compiler, or silently special-case those decals to force parity.

Reproduce the audit without modifying the game:

```powershell
python tools/audit_surface_placement.py '<KCD2>/Data/Levels/trosecko/terrain.pak' --output trosky.json
python tools/audit_surface_placement.py '<KCD2>/Data/Levels/kutnohorsko/terrain.pak' --output kutnohorsko.json
```

Trosky terrain SHA-256:
`c1261a20d17a53b0f67ee2bb7dbf67284e11f412c142ad9af11da0cb696e0def`.
Kutnohorsko terrain SHA-256:
`db05e0ca184713433bfa57eaee997fd721fe22438374a2ccb15d02b3657f238e`.

## Setup and cache integration

Recipe 41 calls `terrain_surface_placement.upgrade_package` after the existing
terrain/LOD stages. Resuming a recipe-40 completed map performs this migration.
KCD1:MP setup runs the same migration on its private exported snapshot before
recording receipt hashes. The standalone bridge has an optional upgrade hook
and does not acquire a dependency on setup's Python modules.

The migration reinserts surfaces only. Existing merged records keep their cell
ownership. Record bytes and their multiplicities must match before and after;
terrain height, resource tables, lighting, shaders, entities and schedules are
preserved. Archive replacement detaches hard-linked inputs. A versioned marker
hashes the resulting object tree; a repeat run is a no-op, while a stale marker
is rejected. Existing caches and installed source packages are not modified by
the multiplayer export.

On the installed converted-map fixture, all 113,605 records survived byte for
byte. Root occupancy fell from 30,174 to 9; maximum occupancy fell to 105;
node count changed from 6,720 to 9,869. Repeating the conversion produced
identical bytes. These are structural results, not measured FPS improvements.

## Retail installation verification (2026-10-21)

The corrected terrain was installed into the existing retail single-player map
and the existing KCD1:MP export. Before replacement, all 352 unique files across
both packages (240.19 GB) passed their receipt SHA-256 checks. Each package was
staged separately, the terrain archive was rewritten, and its receipt updated.
Both upgraded object trees have SHA-256
`fa87b4df09a4e623cf97a5c7f3648377fab876744105c181dfd1bca3925bbcb4`.

All files other than the terrain archive and receipt were preserved. Other
members inside the terrain archive were compared byte for byte. Existing
lighting, shaders, gameplay, NPC schedules and quest data were unchanged.
Previous packages were retained for rollback. The multiplayer export is updated
but was not activated; retail remained on the single-player map.

Validation: the main suite ran 1,657 tests (1,640 passed, 17 skipped), and the
multiplayer bridge suite ran 37 tests (36 passed, one skipped). No live-game
load, menu-freeze reproduction or frame-time comparison has been performed on
this revised installation.

## Runtime acceptance still required

Load a package produced by current setup, including an MP export of an older
completed map. Check `KcdMp_ready` / player spawn, open and close menus after a
cold load, walk through Skalitz and check road/decal visibility and water while
crossing node boundaries. Compare frame timings from the same camera and
settings, and inspect logs for new render/streaming errors. Passing static
tests alone does not establish that the reported freeze is fixed.
