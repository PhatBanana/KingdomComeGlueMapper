# Bed navigation audit

`tools/audit_bed_navigation.py` checks, offline, whether the NPCs of the
converted world can lie down in the beds their schedules send them to. It
reports and changes nothing; it is meant as a package gate before a test
build and as the first stop when an NPC is seen standing beside a bed at
night.

```
python tools/audit_bed_navigation.py --package <mod folder> --target <KCD2 folder> --out <report folder> [--town skalitz]
```

`--recast <recast.pak> [--variant q_skalitz_normal]` measures the same beds
against another mesh, for example KCD1's own `rataje/recast.pak` or a staged
branch output. The report folder receives `beds.jsonl` (one converted bed per
line with every pose, its nearest polygon and the status) and `report.json`.

## What the engine checks

An NPC lies down through a smart-object animation. Its start pose comes from
`smartobjecthelpersetanimations.xml` in the level: for each helper family the
`LieDown` entries carry a `StartTransform` local to the bed, with
`Checks="1,1"` and `CheckMNMTolerance="MNMToleranceDefault"`, so the pose is
projected onto the navigation mesh within a tolerance before the animation
(`HasAlignProcclip`) slides the character into place. The pose is on the bed
itself, on its local +y side only:

| Family | Lie-down start pose (local x, y, z in m) |
| --- | --- |
| `Bed_1Place_High` | (-0.002, 0.867, 0.021), (0.004, 0.853, 0) |
| `Bed_1Place_Bench` | (-0.101, 0.557, 0) to (0.067, 0.647, 0) |
| `Bed_1Place_Low` | (-0.117, 0.912, 0) to (0.017, 0.669, 0) |
| `Bed_1Place_Tent` | (-0.262, 0.838, -0.021) |

The `sittingNoTable` entries at y -0.46 have `Checks="0,1"` and are not lie-down
poses; the audit keeps only poses tagged `liePlace*`. Because the pose is on
the bed, even native beds sit about 0.8 m from the nearest walkable polygon
(bed half-width plus the 0.32 m agent radius). Nothing documents the
tolerance, so the audit measures it.

## Calibration on native Trosky

The same measurement over all 498 beds of the retail `trosecko` level against
the native mesh gives, per family, the distance from the best lie-down pose to
the nearest walkable polygon (3D-nearest, as the engine's closest-mesh query;
horizontal gap and height gap listed separately):

| Family | n | horizontal p90 | horizontal max | height p90 | height max |
| --- | ---: | ---: | ---: | ---: | ---: |
| `Bed_1Place_Bench` | 64 | 0.96 | 1.05 | 0.14 | 0.48 |
| `Bed_1Place_High` | 103 | 0.85 | 0.90 | 0.09 | 0.14 |
| `Bed_1Place_Low` | 104 | 0.46 | 0.65 | 0.19 | 0.31 |
| `Bed_1Place_Low_Var1` | 50 | 0.50 | 0.81 | 0.17 | 0.24 |
| `Bed_1Place_Low_Var2` | 59 | 0.42 | 0.75 | 0.18 | 0.24 |
| `Bed_1Place_Tent` | 78 | 1.17 | 1.40 | 0.29 | 0.50 |
| `Bed_2Place_High_Left` | 20 | 0.88 | 0.93 | 0.08 | 0.09 |
| `Bed_2Place_High_Right` | 20 | 0.87 | 0.89 | 0.08 | 0.09 |

A converted bed is `ok` within the native 90th percentile, `marginal` within
the native maximum plus 3 cm (vertex quantization is 16/2047 m and the native
sample is finite), and an `outlier` beyond that or when no walkable surface
lies within 2 m horizontally and 1.5 m vertically. Native NPCs sleep in every
one of those 498 beds, so the envelope is a lower bound of what the engine
accepts, not an upper bound: an outlier is a bed to look at, not proof of a
failure, except when there is no surface at all.

## Results, 30 October 2026

Installed package (`main` 47f031a, setup recipe 66), every bed a scheduler hub
uses: 66 beds, 63 of them in Skalitz. Calibration and audit take 11 s.

| Status | Beds | Notes |
| --- | ---: | --- |
| ok | 53 | |
| marginal | 10 | benches 0.96 to 1.07 m from the mesh or with the surface 0.16 to 0.49 m off; low beds inside a polygon whose surface is 0.21 to 0.25 m above the pose |
| outlier | 3 | the two forge-loft beds (no surface within reach; the ground floor is 3.4 m below) and `gm_world_bed_102268_bed`, a public bench by the castle at 877.7, 3341.1 whose nearest surface is 0.65 m below the pose |

The converted mesh is not the cause of any of this: the same 63 Skalitz beds
measured against KCD1's `rataje/recast.pak` (base with the `q_skalitz_normal`
variant, which is what the package uses for Skalitz) give identical nearest
polygons for every bed.

With the mesh staged by `feat/loft-navmesh` (acea251) the two loft beds become
`ok`: 0.80 m (father) and 0.77 m (mother) from the new loft polygons, with the
surface 1 to 2 cm below the pose, inside the native high-bed envelope. Skalitz
then has 54 ok, 8 marginal and the castle bench as the one outlier. Note that
the loft branch's own validation places the poses at +-0.867 m along the bed's
local x; the engine's poses are on local +y, 0.82 m north of its polygons. The
geometry holds either way; the validation and its documentation should follow
the helper set.

## Tile layout used by the reader

Recast tiles in `recast/rdnavmesh_1.nav`, indexed by `.hdr` records of
`u32 x, y, offset, count` followed by `count` `u32` sizes (one per layer).
Each tile, little endian: 17 `u32` (magic `VAND`, version 14, tx, ty, layer,
userId, polyCount, vertCount, packed vertex count, 2*polyCount, a bake
statistic, four zeros, offMeshConCount, polyCount - offMeshConCount), 11 `f32`
(agent height, radius, climb, 0.8, bmin xyz, bmax xyz, quantization 12.5),
packed `u32` vertices (x bits 21..31, y bits 10..20, z bits 0..9, scaled to the
tile bounds), six `f32` per off-mesh connection, 28-byte polygons (six `u16`
vertices, six `u16` neighbours, area, vertex count, flags) and 52-byte
off-mesh records. The size law `112 + 4*vertCount + 28*polyCount +
68*offMeshConCount` holds for every tile of both games; the reader enforces it
and tolerates the flat bounds of empty tiles.

## Limits and retail acceptance

Nothing here has run in the game. The envelope says what native beds look
like, not what the engine's tolerance is; a `marginal` bed is expected to work
and an `outlier` to fail only when it has no surface at all. The audit covers
the beds that scheduler hubs link with `_,use`; beds reached through other
links are not measured.

1. Build with `feat/loft-navmesh` included, start in Skalitz and watch Henry's
   parents from 22:00 to 01:00: both should climb the ladder and lie down.
2. Spot-check two marginal benches at night: `gm_world_bed_102637_bed` in
   Filip's house (768.0, 3510.8) and `gm_world_bed_101784_bed` at the
   merchant's (817.1, 3487.4), then the castle bench `gm_world_bed_102268_bed`
   (877.7, 3341.1).
3. Any NPC standing beside a bed for more than a minute is a failure; note the
   bed name from `beds.jsonl` so the envelope can be tightened.
