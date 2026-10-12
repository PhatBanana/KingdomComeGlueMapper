# Imported static brush visibility

## Confirmed failure

At the Skalitz tavern, KCD1 has a mesh containing the steps, large rocks, roots
and ground covering: `objects/buildings/houses/skalice_pub/skalice_tavern_terrain.cgf`.
The installed conversion had the same geometry (excluding material-name remaps)
and the exact source transform at (796.4234, 3478.05444, 50.62565), but did not
render it. Loading the same converted mesh directly as a GeomEntity displayed it.

The missing brush was already on layer 0. Its imported render flags were
`0x40100408`; clearing only bit 20 to `0x40000408` restored the original static
placement after a fresh game launch. There was no spawned replacement after
restart. Meshes, textures, transforms, bounds and layer IDs were unchanged.

KCD1's legacy static-instancing bit must not be carried into ordinary converted
KCD2 brush placements without rebuilding the corresponding instancing contract.
The exact internal meaning of that bit in KCD2 is not inferred from another
CryEngine version: the compatibility correction is supported by the controlled
single-bit runtime test and the native exported data comparison.

## Scope and implementation

The native Trosky HLOD export contains 171,333 brushes, none with bit 20 set.
The installed imported map had 23,120 brushes with that bit. Nearby land-slide
and stream-edge meshes at the second reported location (818.8, 3510.8, 50.3)
also carry it in the KCD1 source.

`building_brushes.convert_brush` now removes the legacy instancing bit when
converting KCD1 records. `brush_registration.repair_package` repairs already
converted HLOD data during combined-package assembly. It targets only mesh paths
in the imported `gluebuild/` namespace and preserves all other flag bits, native
brushes, vegetation records, placement data and archive entries. Package replacement
is atomic and does not modify a hardlinked source package.

## Validation (2026-10-12)

- Single-brush stage: `outputs/TerrainRegistration/FlagProbe01`.
- Full stage: `outputs/TerrainRegistration/Map01`.
- Original installed level preserved as `FlagProbe01/baseline-level.pak`.
- Full stage changed exactly 23,120 bytes in `terrain/hlods.dat`, one per affected
  brush; every other level archive entry remained identical.
- A second repair pass produces no changes.
- 509 working-tree tests passed, including unrelated local experiment tests.
- Regression coverage checks fresh conversion, preservation of other flags and
  native records, invalid mesh references, idempotence and package integration.

The native export comparison and tavern test establish this visibility defect;
they do not establish that every other possible asset conversion issue is fixed.

The full corrected package was installed and freshly launched. Visual inspection
confirmed the tavern steps/rock bank in the single-flag test and restored ground
detail around the second location in the map-wide test. No runtime-spawned terrain
entity is required by the installed fix. The game remains open near the second site.
