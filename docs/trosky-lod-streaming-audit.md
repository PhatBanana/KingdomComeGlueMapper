# Native Trosky LOD and streaming audit

Inspected 18 October 2026. This is a read-only investigation, not a verified
rendering fix. The user reports the same approach/retreat behaviour in retail
and Mod Tools. No distance overrides or mesh patches were installed.

## Evidence and scope

Inputs: installed retail `Engine/Engine.pak`, `Data/Levels/trosecko`, retail
`WHGame.dll`, Mod Tools `Cry3DEngine.dll`, and the installed converted
`kcd1_travel` package. The native level is Trosky (`trosecko`).

Local generated evidence (not game assets committed to Git):

- `outputs/trosky-cvar-registration.json`: Mod Tools CVar registration disassembly.
- `outputs/trosky-lod-families.json`: deterministic seed-0 sample of 32 vegetation
  and 32 brush resource families per level, with per-LOD headers and companion lookup.
- `outputs/lod-face-area-comparison.json`: independent triangle-area calculations
  for the 132 nonempty converted mesh chunks in that sample.
- `outputs/lod-hierarchy-audit.json`: hierarchy shape comparison. Its raw sphere
  enclosure counts are **not** runtime validity failures: native data also fails
  that naive geometric test, and the engine uses type-specific switching margins.

## Separate decisions

1. HLOD switches between a group proxy and the group's detailed render nodes.
2. Mesh LOD selection chooses the geometric detail for each individual object.
3. Streaming determines which requested geometry is available to render.
4. Hysteresis and delayed unloading retain data after moving away.

Counting external `_lodN.cgf` files only checks inventory. It cannot establish
which of these decisions is responsible for a visible transition.

## Native HLOD switching

The Mod Tools function at RVA `0x117c40` implements type-specific distances.
Its brush-family branch computes:

`radius + clusterMinimum + clusterMultiplier * pow(radius, clusterExponent)`

The vegetation branch reads the distance array at the node's vegetation tier
and adds the node radius. The interior branch adds the interior distance to
the radius. A separate state branch adds the hysteresis distance.

The observed config constructor is at RVA `0x11db80`; the equivalent retail
constructor sequence includes RVA `0x13f3fdf`. Registration identifies offset
`0x34` as hysteresis distance and offset `0x54` as frames until unload:

| Setting | Mod Tools default | Retail default |
| --- | ---: | ---: |
| HLOD hysteresis | 8 metres | 8 metres |
| HLOD frames until unload | 600 | 600 |

These are binary defaults, not captured live CVar values. A 600-frame delay
would be approximately 10 seconds at 60 FPS; it is not a fixed ten-second timer.
It describes HLOD unloading, not the entire mesh cache lifetime.

Retail `Config/CVarGroups/sys_spec_ObjectDetail.cfg`, default level 3, supplies
cluster minimum 110 and multiplier 0.45. The constructor exponent is 1.
For example a radius-50 brush group gives a 182.5-metre centre-distance threshold
before the state-dependent hysteresis addition. This example is not a measured
transition for the user's screenshots.

Retail `Config/CVarGroups/sys_spec_Vegetation.cfg` supplies the default tier
array `8000 3200 1600 400`. Tier distances vary by graphics preset; the lowest
preset has `8000 1000 600 300`. No `Config/CVarOverrides/trosecko.cfg` entry
was present in the inspected Engine archive. Runtime overrides can still exist.

Native Trosky has vegetation counts 1, 16, 256, 3849 at depths 1 through 4.
The converted level has 1, 16, 256, 4088 at those depths. Thus the converted
vegetation does not have an extra hierarchy tier in this installation.

The brush hierarchy differs substantially: native Trosky uses nested Cluster,
Prefab and Interior groups; the converted level places 2863 Cluster groups
directly under Main. That is a conversion difference, not proof of a particular
late transition. The source converter also uses authored KCD1 switching radii
as native HLOD radii; these fields do not have identical semantics.

## Mesh LOD and geometry packaging

Mod Tools registers `e_LodFaceArea` with default **2** at RVA `0x31a242`.
Its embedded description defines mode 2 as using geometric mean face area
from all LOD meshes. Base-mesh-only mode is 1. The retail registration at
RVA `0x15c3f46` supplies the same default via `r15d` (initialized from zero
plus 2 at RVA `0x15c0d18`). This does not establish the live value after overrides.

The sample selects resources referenced by each level, then checks base files
and `_lod1` through `_lod6` companions:

| Sample | Native Trosky | Converted world |
| --- | ---: | ---: |
| Resource families | 64 | 64 |
| Base and LOD CGF files found | 141 | 132 |
| Files with matching `.cgfm` companions | 141 | 0 |
| Render mesh headers, excluding physics-only entries | 158 | 132 |
| Those render mesh header flags | `0xB` | `0x2` |

Native `0xB` includes the empty/stripped mesh flag: geometry is in its companion.
The converter's `static_assets.mesh_bytes` retains legacy geometry streams,
rewrites material references, and performs selected geometry corrections.
It does not currently generate the native split header/payload arrangement.

The shared reference format identifies bit `0x8` as `HAS_FACE_AREA`. Native
samples mark the value valid; converted samples do not. Public engine-family
loader code recomputes face area without this bit, but this reference alone
does not prove KCD2's exact loader branch or that setting the bit fixes anything.

Independent geometric means were calculated from local-space triangles,
excluding areas at or below `1e-12`, for 132 converted mesh chunks. Ten differ
from the stored value by over 5%; the largest example is
`gluebuild/setup_props/mesh1310.cgf`, mesh chunk 41:

- stored: `0.000221167181734927`
- calculated: `0.0001397822460757231`
- calculated/stored: `0.632020740958099`

This calculation has not been matched to KCD2's exact treatment of degenerate
faces and subsets. It is evidence for checking metadata consistency, not
permission to replace all stored values. The earlier sampled vegetation
`mesh295.cgf` differed by only about 0.03%.

## What is and is not established

Confirmed: native retention behaviour exists in both builds; converted assets
do not follow native split mesh packaging; brush grouping differs; the active
family of mesh-LOD calculations must be considered across all LODs.

Not established: the identity and state of the pictured object, its requested
versus resident mesh LOD, its HLOD state when it changes, or whether splitting
the converted geometry corrects the observed pop-in. No runtime fix is claimed.

The next controlled capture should use native Trosky and a converted scene at
the same quality settings. KCD2's embedded debug documentation provides:

- `e_DebugDraw 1`: CGF name, polygon count and used LOD.
- `e_DebugDraw 34`: LOD distances.
- `e_DebugDraw 33`: mesh LOD versus HLOD distances.
- `e_StreamCgfDebug 2`: loading and unloading operations.
- `wh_e_HLodDebugDraw 1`: HLOD state visualization.

Use these separately in Mod Tools if retail restricts diagnostic CVars. Capture
first approach, stationary waiting, and retreat. If the requested detailed LOD
precedes residency, investigate streaming/payload handling. If the requested
LOD itself changes only at close range, inspect per-LOD metadata and object
ratios. If the group remains Far, inspect the HLOD threshold and loading state.
Only then run a bounded converted-family experiment, before any full rebuild.

## Implemented metadata correction (18 October)

`mesh_lod_metadata.py` now computes the statistic over render subsets with the
engine-family `1e-5` area cutoff and sequential float accumulation. It writes
the value and `HAS_FACE_AREA` together. It preserves every geometry stream,
node transform, material, physics chunk and LOD filename. Native assets and
already-valid metadata are left unchanged. Tiny-only/empty meshes remain
unchanged rather than receiving an invented distance statistic.

Reference algorithm: Amazon Lumberyard `CryCommon/IIndexedMesh.h`,
`CMeshHelpers::CollectFaceAreas` and `CMesh::RecomputeGeometricMeanFaceArea`.
The earlier all-triangle calculation above used a different cutoff and must
not be treated as the engine's statistic.

Native Trosky `fagus_sylvatica_c.cgfm` comparison: stored `0.1277197003`,
calculated `0.1277230084` (0.00259% difference). Converted `mesh295.cgf`:
stored `0.3478816152`, calculated `0.3479722440`. These measurements validate
the calculation closely, but do not establish that this tree is the pictured
object or that all visible pop-in is caused by this metadata.

Native `RCJob_WH.xml` runs StripMesh and StripNonMesh passes and stores CGF/
CGFM without ZIP compression. Our archives already use stored entries.
Running those RC passes on the converted tree, including native compact-stream
options, produced a zero face-area field. That output was rejected; no RC
recompiled probe was installed. The following lossless split replaces that path.

Fresh asset packaging and recipe-8 resume migration share the metadata stage.
Migration rewrites only changed shards, one shard at a time on the same drive,
checks CRCs, replaces the archive and updates receipt hashes. Unit tests cover
subset calculation, the area cutoff, invalid indices, geometry preservation,
external LOD processing and idempotent package migration.

This is a concrete missing-metadata correction, not a runtime acceptance claim.
First-approach/retreat comparison is still required to establish its effect on
the reported close-range model changes and determine whether streaming or
HLOD thresholds need another correction.

## Lossless geometry streaming implementation

**REJECTED after runtime testing.** On 18 October the retail load of
`crucialdecision871.whs` crashed while loading `kcd1_travel`, with the log ending
at `Terrain: Waiting for 8593 async loaders...`. BugSplat reported
`WHGame!00996f33`. Structural validation did not establish runtime compatibility.
The split is removed from fresh packaging, and recipe 10 restores recipe-9
packages using their preserved complete payloads. Earlier face-area metadata
is retained. The implementation below remains experimental; it is not an
accepted fix or a production build stage.

The user subsequently confirmed that loading works after this rollback.
This confirms recovery of the tested save, not resolution of the original LOD
pop-in or compatibility of the rejected split.

`mesh_streaming.py` separates compiled render streams from resident headers
without round-tripping through RC. The RC probe dropped packed-position stream
15 entirely: source mesh references stream 58, whereas RC's payload has a zero
stream-15 reference. This explains why using that result is unsafe beyond its
zero face-area statistic.

The new payload is byte-identical to the metadata-normalized source CGF. The
header removes render subset/stream chunks, clears their mesh references and
sets the EMPTY_MESH bit; bounds, area, nodes, materials and physics stay intact.
The payload intentionally retains ancillary source chunks rather than risking
a lossy reconstruction. Engine-family `LoadStreamRenderMeshes` pairs render
meshes by node name. A single unnamed root is supported, while ambiguous
multi-node names and shared resident/render streams are rejected.

Full installed-asset dry run: 16,289 split candidates, six unchanged empty or
tiny-only assets, no conversion errors. Source and payload totals both equal
2,191,602,888 bytes. Resident headers total 69,742,252 bytes. This adds about
66.5 MiB per installation, not another copy of the full build.

Fresh packaging includes `.cgfm` dependencies. Recipe 9 resume migration writes
one companion archive per changed source shard, keeping each below 1 GiB and
checking CRCs before replacing files. Missing or conflicting companions fail
explicitly. Existing split families are left intact on a second migration.

Unit tests cover payload preservation, header structure, paired metadata,
external LOD companion names, missing/ambiguous nodes, missing companions,
conflicting companions, and idempotent migration. Static validation does not
replace an engine load and first-approach/retreat visual test.
