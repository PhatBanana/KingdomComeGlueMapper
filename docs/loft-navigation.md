# Forge loft navigation

Status: converter, validation and tests done; **not tested in game**. The parents' climb,
lie-down, wake-up and save/reload remain retail acceptance steps (below). Corrected on
2026-10-30: the lie-down start model (see "Lie-down starts").

## Why

The authored forge loft ([forge-loft-design.md](forge-loft-design.md)) gives Henry's parents
assigned beds at z 67.3, but the converted navigation mesh has no polygon on the loft and no
off-mesh link to it. That is not a conversion loss: KCD1's own `rataje/recast.pak` has none
either, and neither does any of the 362 variant meshes. The parents reach the loft by
scheduler placement only, stop about 0.9-1.1 m beside their beds and never lie down, because
the `Bed_1Place_High` animations carry navmesh checks (`Checks="1,1"`, `CheckMNMTolerance`).
The 2026-10-29 probe (`D:\KCD\Builds\glue\diag\navmesh-forge-loft-20261029`) decoded the
tile format and proved the gap; the follow-up probes in `diag\loft-navmesh-20261029` settled
the remaining header and record fields from every tile of Trosky and the package.

## What `tools/loft_navigation.py` adds

One new layer tile in each of the two 16 m cells under the loft, (45,213) and (46,213), appended
after the native layers. Every existing tile stays byte-identical (the converter proves it and
records the native mesh digest). The new tiles carry `userId = 0x474d4c46` in the header, which
native tiles never do, so `static_navigation_profiles` can recognise and drop them when it
recomposes the Skalitz cells from the `q_skalitz_normal` variant; the loft converter rebuilds
them afterwards in the same finalization.

| polygon | cell | z | world rectangle (x / y) | bound from |
| --- | --- | --- | --- | --- |
| `loft_west` | 45,213 | 67.30 | 733.75-736.00 / 3417.15-3421.96 | Henry's bed +0.18, boards' south edge, Mother's bed -0.18, tile border (+x portal) |
| `loft_border` | 46,213 | 67.30 | 736.00-737.00 / 3417.15-3422.00 | tile border (-x portal), Father's bed -0.18 |
| `loft_landing` | 46,213 | 67.30 | 737.00-737.38 / 3417.15-3422.00 | sack clearance 737.39 |
| `loft_hatch` | 46,213 | 67.30 | 737.38-738.20 / 3416.60-3418.55 | ladder-landing keepout, family chest -0.25 |
| `foot_west` | 46,213 | 63.92 | 736.00-737.25 / 3414.40-3415.19 | tile border (-x portal), 0.6 m object at y 3415.51 |
| `foot_east` | 46,213 | 63.92 | 737.25-738.24 / 3414.76-3416.20 | object at y 3414.44, hearth at y 3416.54, east wall |

Polygons are clockwise in (x, y) like the 1,038,342 native Trosky polygons, area 1, flags 0x100,
quantized to the native 16 m / 2047 grid; shared edges become 1-based neighbour links, edges on
the cell border become portals. The `foot_west` portal meets native polygon 25 of (45,213) layer 0
across x = 736 with 0.72 m of shared border, which is how the patch joins the workshop floor:
layers of one cell only connect through border portals in Detour, so the patch cannot be linked
to polygon 19 of (46,213) directly without rewriting that tile.

The ladder record lives in the (46,213) layer and copies the 58 native Trosky ladder records:
category 3, flags 1 (bidirectional), radius 0.5, side 255, entity = the converted ladder's GUID,
tail `7fffffff 0100ffff`. Endpoints follow the native rule in the ladder's local frame, start
(-0.038, +0.518, -0.139) at the foot and end (+0.023, -0.425, +height) at the top, which for
`gm_forge_loft_ladder` (height 3.25, leaning 8 degrees north) gives foot (737.64, 3415.27, 63.84)
inside `foot_east` and top (737.58, 3416.67, 67.07) inside `loft_hatch`, 0.23 m below the floor
polygon and within the 0.32 m climb tolerance.

Header fields that the first probe left open: offset 32 is the packed vertex count, offset 36 is
the internal-link count plus 2 (91% of native tiles), offset 40 is a bake statistic that no
stored structure reproduces (set to 3, the native mode for tiles of 1-4 polygons). `bmin.z` and
`bmax.z` sit on 0.08 m multiples like every native tile.

## Layout derivation and validation

`convert(files, mission, helpers, native_mesh, brushes=None)` reads the ladder and both
parents' beds from `objects_mission0.xml`, the beds' lie-down starts from
`smartobjecthelpersetanimations.xml`, resolves `forge_loft_layout.LAYOUT` through `room_layout`
and rejects the authored rectangles unless all of this holds on the decoded bytes:

- size law `112 + 4*vertCount + 28*polyCount + 68*offMeshConCount`, `offMeshBase`, zeros and
  agent floats match the native pattern; the tile count and the `.hdr` index are rebuilt and
  the result round-trips through `static_navigation_profiles.decode`;
- every polygon is convex, clockwise, inside its tile and within 6 mm of the design after
  quantization; every neighbour link is shared back by the neighbour's reversed edge; every
  portal edge lies on the border and meets an opposite portal in the neighbouring cell at the
  same height (native or authored);
- loft polygons lie inside the floor boards' extent or the ladder-landing keepout and do not
  overlap any furniture footprint expanded by 0.18 m (beds) or 0.25 m (chests, table, stool,
  basket, sack); every navmesh-checked lie-down start of each parent's bed has a loft polygon
  within 0.90 m horizontally and 0.10 m vertically, the native reach (next section);
- the ladder foot is inside a ground polygon of its own tile and the top inside a loft polygon
  of the same cell, within the landing keepout;
- the ground patch stays 0.30 m clear of every HLOD brush that stands on the floor (height
  0.15-0.5 m above it, extent under 4 m), 667 brushes in the installed package.

## Lie-down starts

`Bed_1Place_High` has five distinct `LieDown` starts in `smartobjecthelpersetanimations.xml`
(`HelperTransformLocal` plus `StartTransform`, in the bed's frame): three approach variants at
(0, +0.85..0.87, 0.02) facing across the bed, with `Checks="1,1"` and `HasAlignProcclip`, and
two already-sitting variants at (0, -0.47, 0) with `Checks="0,1"`. The start therefore lies on
the bed, 0.26 m short of its +y end, not beside it; the engine projects it onto the mesh within
its `CheckMNMTolerance` (`MNMToleranceDefault`; the binary also names `MNMToleranceStrict`, no
numeric value found). The first version of this converter placed the starts 0.867 m beside the
bed on either long side, which is not what the engine checks; the bed audit of 2026-10-30
(`D:\KCD\Builds\glue\diag\bed-navmesh-audit-20261030`) caught it.

Native reach, measured on all 103 `Bed_1Place_High` beds of Trosky against the native mesh
(`diag\loft-navmesh-20261029\native_bed_reach.py`): the nearest polygon to a checked start is
0.54-1.18 m away (median 0.89, p90 1.00), within 0.10 m vertically (p90), and lies beside the
bed in 88 cases, 0.73-0.96 m from the bed's centre line (0.12-0.43 m outside the `bed_rustic_d`
box; native models may be narrower). The audit's own 0.79 / 0.85 / 0.90 figures are the best of
all five starts including the unchecked sitting ones. The validation limits are the native median
and p90 for the checked start: 0.90 m horizontally, 0.10 m vertically.

The forge beds are `bed_rustic_d` at yaw 91 degrees (local +y points west), so the starts sit at
the beds' west ends and the nearest mesh is the room side: `loft_west` and `loft_border` end
0.18 m south of the measured bed box (south edges y 3422.14 and 3422.18), 0.82 m from the beds'
centre lines and 0.82-0.83 m from every checked start, at the native median. The polygons cannot
go further north without entering the bed box, which begins 0.64 m from the start: the 0.4 m gap
the audit suggested is not reachable with any clearance, and no native bake gets closer than
0.73 m either. The converted Skalitz high beds with sleepers sit at 0.48-0.74 m, so the forge
beds are the farthest in town but inside native practice.

Repeating the conversion strips the tagged layers first and produces byte-identical archives
(`previously_authored_layers` in the report, never in the marker). `stage(mod, target, output)`
writes a dry-run copy of `recast.pak` plus `report.json`; `upgrade(package, target)` rewrites
the package archive only when the bytes change and runs in `setup_package_upgrade.finalize`
right after the forge loft on the clean path and beside the completed-build repairs on the
fast path (recipe 68).

## Dry run (installed package, recipe 66, forge loft v3, 2026-10-30)

Staging took 3.5 s. 736 -> 737 archive entries (the marker), 734 untouched entries identical,
58,064 -> 58,066 tiles, only cells (45,213) and (46,213) changed, native stacks preserved
(base mesh sha256 8c475da6...). Every checked lie-down start has its nearest polygon 0.82-0.83 m
away (Mother: `loft_west`, Father: `loft_border`) and 0.01-0.04 m below it; the sitting starts
0.77-0.88 m. A second plan on the staged package reports no changes. Report:
`D:\KCD\Builds\glue\diag\loft-navmesh-20261029\dry-run-report.json` (the first version's
report, with the wrong pose model, is `dry-run-report-acea251.json`).

## Decisions and limits

- The `q_skalitz_normal` variant mesh and the other 361 variant pairs stay byte-identical: the
  static world never activates them (`static_navigation_profiles` requires them to match the
  source) and only the base mesh is loaded. `ubernav.tmm` (the coarse travel graph) and the
  12-byte `areasmission0.bai` are untouched; the loft is a 2 m local detour, not a travel node.
- The patch overlaps the workshop polygon 19 of (46,213) in x/y at the same height. Detour
  tolerates overlapping layers; a path from the workshop crosses x = 736 twice (about 1.5 m).
- The record's end lies in the same tile as its start; 14 of 58 native ladders do the same.
- Field 40 and the `userId` tag have no proven runtime meaning. If the loader rejects a
  non-zero `userId`, the layers would be dropped, not the mesh.
- The lie-down starts are on the beds; the mesh ends 0.82 m from them, at the native median
  (0.54-1.18 m). Whether `MNMToleranceDefault` accepts that is only shown by native beds, which
  routinely do the same.
- Nothing here changes the 100 imported KCD1 ladders, which still carry category 2 and source
  GUIDs ([parent-sleep-audit.md](parent-sleep-audit.md)); that is a separate converter.
- Runtime behaviour (link traversal, ladder smart-object use, bed entry) is unverified.

## Retail acceptance

1. Install the staged package over its baseline with the game closed and a save backup.
2. At 20:13 watch Father leave his work, walk to the ladder foot, climb and lie down in
   `gm_forge_loft_father_bed`; at 22:12 the same for Mother and her bed.
3. Confirm the parents do not stand beside the beds or teleport; check `game.log` for navmesh,
   ladder or smart-object errors around those times.
4. Wait for wake-up (06:46 and 06:52): both climb down and resume work.
5. Save while one parent sleeps, reload, and repeat the next night.
6. Walk the loft as Henry: the beds, chests and ladder still work as before.
