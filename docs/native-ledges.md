# Native vault ledges

Gameplay recipe 59 adds fence and wall vaulting (issue #5) to fresh builds and
the saved-build upgrade. Both games compile ledges into `whdata_1`
`Root/LedgeManager`, using identical `Ledge` (`entityId`, `markersStartIdx`,
`markersCount`, `ledgeCornerEndAdjustAmount`, `Flags0`, `Flags1`) and `Marker`
(`worldPosition`, `facingDirection`, `endOrCorner`) records in world space. The
converted world keeps KCD1 coordinates, so the records are copied unchanged.

- **Static ledges** (`entityId` 0): 3,361 of 3,589 source ledges. All are kept.
  Every one has markers inside the bounds of an active-layer source brush.
- **Entity-bound ledges**: each references one `LedgeObject`. Active ones (210)
  are re-created as `gm_ledge_<source id>` with fresh converted EntityIds and
  their full source properties, and `entityId` is remapped. All of these
  property names are present in retail `WHGame.dll`. Ledges whose object is on
  an inactive source layer are dropped and counted per layer: 18 ledges in
  quest/state layers such as `army_camp_state1` and `Pribyslawitz_hide`.
- Markers are re-indexed contiguously: 3,571 ledges and 30,066 markers.

`LedgeManager` comes first in `whdata_1`, as in native `trosecko`, followed by
any existing `GameProfileManager`. The root attributes must match native
(`version="1"`). No empty profile manager is added, because the current world
already loads with none.

`world-ledges.json` fingerprints only the ledge manager and its entities.
Repeating the stage revalidates without rewriting. Converting twice is refused.
`tools/build_ledges_test.py` stages a candidate level from an installed mod
without installing anything.

**Vaulting, climbing and entity enable/disable have not been playtested.**
