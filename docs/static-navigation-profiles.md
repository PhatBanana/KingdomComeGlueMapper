# Static world navigation profiles

## Confirmed packaging defect

The converted world flattens selected source geometry and doors into resident
placements. `region_travel_navigation.package_navigation` copied all 736 members
of KCD1's Recast archive, but only checked settings, tile versions and extents.
The installed `kcd1_travel` level has no `whdata_1` profile manager. Consequently,
placing a profile's mesh file in the archive did not select it for the world.

The opening population builder separately selected `q_skalitz_normal`. The
corresponding intact town navigation remained unused. Source profile 814 declares
`HasNavigation=1` and contains 73 layers; its mesh has 239 tiles in 193 cells.
All 76 door identities in that variant are present in the converted mission at
their authored positions, rotations and scales. **71 of these identities are
missing from the installed base navigation.**

At cell (45, 213), covering X=720..736 and Y=3408..3424, the original base has
80 polygons and one off-mesh connection. The intact variant has 85 polygons and
three connections. The two additional door GUIDs are:

- `8b71a425-7086-47af`, at 732.33154,3413.6091,63.95702.
- `9faa3c51-1da6-44d2`, at 734.6156,3411.668,63.932709.

The third, `90f5c3d2-9030-43ac`, was already in the base mesh. This matches the
reported difference between the house's doors. It proves missing navigation
dependencies; it does not by itself prove every reported stuck/fleeing route has
the same cause.

## Format evidence

The new reader was checked against every base tile in both installed native
KCD2 reference worlds: Trosky (26,009 tiles) and Kuttenberg (54,620 tiles).
Both use the same compact v14 layout as the selected source tiles:

- 112-byte header, including cell and vertical-layer identity.
- 4-byte compact surface vertices and 12-byte off-mesh vertices.
- 28-byte polygons and 52-byte off-mesh connections.
- Connection entity GUID is a little-endian uint64 at byte 32, with category 8
  for doors at byte 40. KCD2 text GUIDs use low32-mid16-high16, not an ordinary
  concatenated UUID. Native references contain 252 and 995 distinct door GUIDs.

The payload length is `112 + 4*vertex_count + 28*polygon_count +
68*off_mesh_connection_count`. The extra 16 bytes per connection account for its
two full-precision vertices. The reader validates counts, bounds, connection
polygon indices and finite endpoints. It does not reinterpret compact vertex
coordinates using an assumed upstream Detour format.

## Conversion

`static_navigation_profiles.py` accepts explicit source profile selections. For
an already flattened world it replaces the entire tile stack at each selected
cell, rebuilding the base header offsets and tile count. Tiles are copied
byte-for-byte from their authored variant. Unrelated cells and every original
variant archive member remain unchanged. It changes neither the high-level
`ubernav.tmm` graph nor physical geometry, doors, schedules or quest scripts.

This is a static profile materialization, not runtime profile activation or a
new navmesh bake. Dynamic profiles with transitions need their native lifecycle;
the adapter refuses worlds already declaring runtime navigation profiles. It
also refuses grouped combinations, conflicting overlays, unknown existing cell
edits, modified source variants, missing door entities and relocated doors.
It never chooses an alternative world state from filenames or NPC names.

`setup_gameplay.STATIC_WORLD_PROFILES` owns the existing opening population's
explicit selection; the same selection now feeds navigation. Recipe 34 calls
the adapter in shared package finalization for both clean setup and transactional
resume. The receipt records profile identities and hashes. Installation requires
that receipt, so a failed finalization cannot leave a nominally current recipe
that skips the repair on resume. No public setup executable has been rebuilt.

The adapter is reusable for additional converted static profiles. This change
selects the shipped opening layout; it does not automatically enable every source
quest state. Fourteen converted doors elsewhere still have no matching active
base connection after this repair. Thirteen have source connections in other
intact-layout profiles (farms, the Rattay upper hall, windmill and siege-camp
layout); the custom rental door has none under its converted identity. Those
selections need their world dependencies checked before enabling them. Their
identities are reported for follow-up, not silently supplied with guessed links
or opening scripts.

## Bounded validation

`build_navigation_profiles_upgrade.py` stages just `recast.pak` from an existing
package. The test candidate is `outputs/static-navigation-profile-test`.

- Replaces 193 cells with 239 authored tiles; total base tiles become 58,064
  rather than 58,056 (whole vertical stacks are replaced, not appended).
- Restores 71 missing door identities and validates all 76 selected door TRS.
- All other cells and all 734 unrelated archive entries remain byte-identical.
- Archive membership and CRC checks pass; reapplication is byte-idempotent.
- Regression tests cover complete stack replacement, dependency failure,
  conflicting/grouped states, invalid binary structure, stale/moved doors,
  preservation and idempotence. Setup tests cover the shared finalization hook
  and rejection of incomplete navigation receipts.
- 129 relevant unit tests passed, including 11 navigation regression tests.

Installed in retail on 20 October 2026 after verifying the game was closed.
Only `Data/Levels/kcd1_travel/recast.pak` and its install-receipt hash changed.
Installed archive SHA-256:
`83681307052085cbb8ca4882f1deac3f65880a0804ae0fa4339580c767b44894`.
Rollback archive and original receipt are in
`outputs/static-navigation-profile-test/rollback-20261020-122711`.
The level and gameplay archives retained their pre-test hashes.

The user confirmed on 20 October 2026 that this installed retail test fixes the
reported issue and requested a commit. That is user-observed runtime acceptance,
separate from the automated structural checks above. The tested baseline also
includes the earlier sweeping point-navigation and door-animation registration
corrections; neither of those candidates resolved the door failure alone.

The confirmation does not establish coverage of every fleeing route, both hand
states, schedule interruption, save/load or navigation around other buildings.
Those remain additional test cases, along with the fourteen unconnected doors
reported above. The converter's generated report retains `runtime_verified=false`
because producing valid files cannot itself certify an in-game test.
