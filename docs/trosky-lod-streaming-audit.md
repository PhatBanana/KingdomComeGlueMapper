# Native Trosky LOD and streaming audit

The sections through the rejected split experiment record the 18 October 2026
investigation. The 19 October follow-up below identifies and tests a separate
LOD-ratio encoding defect. Historical measurements are retained with their
original limitations; they are not descriptions of the newly corrected build.

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

## Confirmed encoding defect and runtime test (19 October)

The KCD1 object LOD byte is a linear percentage. KCD2 interprets the upper
part of that byte range differently. This was verified in the installed
executables, not assumed from public CryEngine source:

```
KCD1: ratio = byte / 100
KCD2: ratio = byte / 100                    when byte <= 100
              1 + (byte - 100) * 19 / 155   otherwise
```

Copying a source byte of 255 therefore changes its meaning from 2.55 to 20.
The nearest KCD2 representation of 2.55 is byte 113 (2.593548). Likewise,
160 becomes 105 and 200 becomes 108. Values at or below 100 remain unchanged.
This preserves source meaning within KCD2's quantization; it does not apply
a global distance multiplier or force maximum detail.

Evidence locations, as RVAs in the examined local DLLs:

- KCD1 `WHGame.dll`: streaming-priority function `0x3fcbf0`, byte read and
  linear scaling at `0x3fcd15..0x3fcd3d`.
- KCD2 Mod Tools `Cry3DEngine.dll`: streaming-priority function `0x1d6fb0`,
  piecewise ratio at `0x1d71a2..0x1d71e7`; float constant at `0x3ac6b8`.
- KCD2 mesh LOD selection at `0x1e5990` uses the same encoding, including
  the branch at `0x1e5a1f..0x1e5a52`.
- Debug mode 3 prints the raw byte, not the decoded multiplier.

SHA-256: KCD1 DLL
`cf9f6dc384edcf35c20647a912745ddb8adb5ba65953e329c24e89dd9c4381aa`;
Mod Tools DLL
`06ecd1f38847c1029eeb0894dd86c8e30f6e8c82e49f29fde92f7e1dd2db1e13`.
The tested Mod Tools build identifies itself as `release_1_5_1166656_117`.

### Why both group and instance records need conversion

The intermediate builders retained source bytes at offset 43 of vegetation
and brush records. Vegetation group records also retain a float at offset
324. The loader derives the live instance setting from that group float.

A bounded test changed only the 132 instances of vegetation group 295 from
255 to 113. Debug mode 3 still reported 255, and the tree remained coarse.
Changing the corresponding group float from 2.55 to 1.13 as well made the
live debug value 113 and removed the coarse foliage in the controlled test.
Group floats are converted with float32 multiplication/truncation in mind:
for example, the representation of 1.05 must round-trip to byte 105.

`tools/lod_ratio_metadata.py` now finalizes both fields together, once, after
the world overlays. It only converts imported namespaces (`glueveg`,
`gluebuild`, `gluelandscape`, `glueitems`, `gluewater`). Native KCD2 references
are unchanged. Native Trosky/Kuttenberg legitimately use bytes above 100;
their authored values must not undergo a KCD1 conversion.

### Controlled observations

Target: `glueveg/setup_vegetation/mesh295.cgf`, the tree near Kunesh at
`725.932922,3501.060547,56.251305`, scale 1.125. Viewing position:
`748.065,3462.210,58.900`. Each test used a fresh process, a distant wait,
approach, 60-second stationary wait, close approach and retreat.

The severe leaf-shape change was visible while geometry stayed at **LOD 0/4,
5,269 polygons**. Texture-streaming debug exposed an overly coarse texture
request, rather than missing high-detail geometry for this particular tree.
The uncorrected stationary request showed mip factor about 63.42 and a
desired mip count of 3. With the group and instance encoding corrected,
the settled factor was 8.23 and desired count 6. The factor change closely
matches `20 / 2.593548`. Cache retention still raises residency after a close
approach, as expected; the correction does not disable that behaviour.

- Byte-only test: `ratio-v1-captures.json`, still visibly coarse.
- Paired test: `ratio-v2-captures.json`, first approach and wait already show
  fine foliage; retreat retains fine foliage. All three viewing captures
  have camera `748.018,3462.286,60.512`.
- Whole-map conversion: `ratio-v3-captures.json`, repeated the improved tree
  result and loaded successfully. Camera bob/heading variation makes this
  run unsuitable for a pixel-identical image comparison. The user confirmed
  that this installed version works.

These local captures and logs are under `outputs/new-game-compare`; game
assets and screenshots are not committed. This establishes the reported
tree failure and its correction. It does not establish identical behaviour
for every roof, every LOD transition, retail build, or hardware configuration.
Existing HLOD startup timeouts/`StreamingStatus=InProgress` warnings still
occur; they also occurred before this correction and are not claimed fixed.
Debug overlays and uncontrolled background activity make the captured FPS
unsuitable for a performance-regression benchmark.

### Vegetation grid metadata

Native archive comparison covered all 4,122 Trosky and 4,266 Kuttenberg
vegetation HLOD nodes. Both use a 4096/1024/256/64 metre hierarchy, cell-centre
XY coordinates, terrain height at that centre, and the XY half-diagonal as
the non-root switching radius. The root uses radius 8000. The 64 metre leaf
radius is consequently 45.254834 metres. These are spatial-cell switching
bounds, not canopy-enclosing spheres.

`spatial_hlod.py` previously used a fixed Z of 128 for the upper tiers and
assigned cells from the source group's centre; leaf radii could retain the
source switching sphere. `rebuild_spatial_hlod.py` now supplies the actual
heightfield. `hlod_spatial_metadata.py` derives membership from instance
origins, validates parent/proxy ownership, and fixes only vegetation Pos/Radius.
It rejects cross-cell proxy ownership instead of silently moving its members.
All native nodes validate without changes; 4,361 converted nodes changed.
Correcting this metadata alone did **not** fix the controlled tree symptom.

`NearestObserverDistance=0` occurs on every inspected native node in both
worlds, so zero was retained. Brush Cluster/Prefab/Interior radii have distinct
semantics; no universal sphere-enclosure rule or blanket radius replacement
was applied. All placements, record bounds, proxy references, transforms,
materials, lighting, terrain heights, collision and gameplay remain intact.

### Setup, migration and verification

Recipe 32 calls the shared grid and ratio stages for clean builds and existing
package migration/resume. `terrain/gluemapper_lod_ratios.json` records the
encoding version and hashes of the converted record stream and group settings.
An unchanged resume validates and skips conversion. A stale marker rejects
mixed data rather than converting an already encoded value a second time.
The new modules are included in the frozen setup import/self-test list.

The migration changes only `level.pak` and `terrain.pak`. It does not rebake
lighting or regenerate mesh/proxy geometry. The archive rewrite helper now
supports the ZIP64 directory already required by the baked terrain's 83,434
members; its previous 65,535-entry limit prevented that targeted upgrade.

Whole-map application changed 438,335 of 1,483,225 vegetation records,
129,478 of 171,290 imported brush records, and 164 of 508 vegetation group
definitions. Byte comparisons verified that unrelated members of both
archives stayed identical. Native resources and all non-LOD record bytes
remain unchanged.

Structural validation: 7,737 groups, 4,102 proxy links, 9,201 referenced
resources with zero missing, 6,967 external LOD companions, and 14,171 valid
texture families. The 16,295-CGF geometry scan checked 57,297 mesh headers
and 16,414 nonempty render meshes with zero errors. These checks do not
replace runtime validation.

Regression tests cover byte decoding/quantization, all group float round trips,
native-resource preservation, exact changed-byte scope, malformed references,
idempotent clean/migration/resume paths, stale markers, native spatial-cell
rules, proxy preservation and archive directories over 65,535 entries.
The experimental CGF/CGFM split and native full-world exporter remain excluded.

The crash reported during diagnostics was caused by switching a live converted
world to `trosecko`: the log records recursive
`CNetwork::SyncWithGame(eNGS_Shutdown)` and fatal error 200 during teardown.
Subsequent tests used fresh processes, not hot map switching. This identifies
that diagnostic crash; it is not proof that every historical crash shares it.
