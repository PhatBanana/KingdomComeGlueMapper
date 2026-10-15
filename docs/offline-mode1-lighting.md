# Offline mode-1 surface conversion — development test

This converter samples converted CGF geometry, material bindings, UVs, base
diffuse textures and alpha to construct opacity/albedo/normal voxel channels.
It does not invoke the editor rebake, change character materials, or recapture
probes. It is experimental and is not yet the default world conversion.

## Implemented

- Compiled CGF render meshes, packed P3S_C4B_T2S streams, per-subset materials,
  centimetre node translations, parent transforms and world placements.
  Physics proxies and attachment helpers are excluded from render surfaces.
- Repeat/bilinear diffuse sampling in linear colour space, texture tiling and
  offsets, split DDS top mips, material opacity, alpha test and VoxelCoverage.
- Projected surface coverage along three axes; geometry-derived normals and
  alpha-weighted albedo. Duplicate triangles do not add coverage/energy.
- Bounded octree generation and planar mask-7 SVI3/SVV3 payloads, validated by
  the existing independent structural reader.
- Explicit opt-in for base-only evaluation of layered shader materials.
- Reversible package staging, backup hashes, installed-file verification and
  restore refusal when the installed files changed after the test.

## Evidence and limitations

The installed native shader decodes normal components through a ZYX swizzle
and maps normalized bytes around 0.5 to signed components. Sampled native
voxel files have planar opacity, albedo and normal arrays. Native albedo alpha
is used for scalar glow. The converter currently supports non-emissive surfaces.
Exact native coverage filtering, normal alpha and material shader evaluation
are NOT established by the structural tests. Geometry normals deliberately do
not reproduce normal-map detail. Equal-alpha overlapping surfaces retain the
first contributor; this is not layered transparent-material transport.

The house contains BLENDLAYER, SNDUVS, DETAIL_MAPPING and DECAL materials.
Their full shading is not reproduced. Default conversion refuses these;
`--experimental-base-materials` allows a clearly labelled base-diffuse test.
UV animation/projection, unsupported shaders and missing DDS data fail.

## Local test built 14 October 2026

- Analytical fixture: 12 triangles, 8 populated mask-7 bricks; the window
  opening remains empty. Preview and numerical fields are saved together.
- House01: 25,859 triangles, 23 material entries, 48 nodes/47 populated bricks.
- InstalledTest01: original mission/voxel files backed up, then test packages
  installed with checksums verified. Mode 1, UseLightProbes=0, streamed voxels,
  lighting updates enabled, geometry regeneration disabled. Probe textures and
  exposure unchanged.
- The user tested House01 and confirmed that the indoor lighting issues were
  fixed. The acceptance applies to that room, not yet to world coverage.

The house-only tile deliberately omits surrounding terrain, vegetation, props
and other buildings. It replaces the previous whole-area tile only for this
reversible development test. Do not distribute it as completed world GI.

Local results: `outputs/InteriorLighting/OfflineMode1/Fixture01`, `House01`,
`InstalledTest01`. Proprietary extracted shader files in this output directory
are local evidence only and must not be committed.

## Commands

```powershell
.venv/Scripts/python.exe tools/build_voxel_surface_fixture.py --output outputs/InteriorLighting/OfflineMode1/Fixture02
.venv/Scripts/python.exe tools/voxel_surfaces.py --manifest outputs/InteriorLighting/NativeBake01/installed-house.json --pak-root D:/SteamLibrary/steamapps/common/KCD2Mod/Mods/kingdomcomegluemapper/Data --output outputs/InteriorLighting/OfflineMode1/House02 --experimental-base-materials
```

Restore the current test after closing the game:

```powershell
.venv/Scripts/python.exe tools/stage_voxel_surface_test.py --restore outputs/InteriorLighting/OfflineMode1/InstalledTest01
```

## Remaining acceptance

1. Extend the user-accepted house result to other interiors and times of day;
   verify successful loading of the complete replacement, not just file writes.
2. Verify native normal-alpha/coverage filtering and layered material policy.
3. Include complete static world dependencies and terrain before general use.
4. Validate scene-state selection and coverage before changing the default
   importer from mode 0. Probe filtering/clipping remains a separate audit.

Validation: 41 focused tests pass: 12 surface tests, 8 voxel-format tests,
13 geometry tests and 8 world/terrain/material tests. These are not proof of
native visual parity.

## World rollout in progress — 14 October 2026

`world_surface_scene.py` reads the installed terrain/HLOD tables and indexes
every static brush placement. It caches each mesh/material variant once and
assigns crossing objects to every intersected tile. The installed scene has
167,167 brush placements and 4,490 mesh/material variants; all variants parse.
Collision-only meshes are explicitly recorded rather than treated as failures.
The brush inventory includes distant landscape geometry outside the playable
4096-metre terrain, so it spans 1,220 voxel tiles.

`world_surface_landscape.py` adds the 4,096 terrain leaf sectors and 14,198
road records (including 33 empty road records). It reconstructs sparse terrain
palettes from owned cells, preserves holes and reads installed road UVs.
13,612 terrain cells have an undefined base-layer tag. The explicit experimental
policy extends adjacent authored colours into these cells; this does not
reproduce the native macro-cover colour. Full terrain colour blending remains
unverified. Terrain and roads add 38,782,455 triangles to the bake input.

`world_surface_tiles.py` produces resumable, individually validated mask-7
tiles. Resume signatures cover scene packages, asset archive entries, conversion
code and sampling policy; saved outputs are revalidated before reuse.
`voxel_raster_fast.py` is an optional Numba backend tested against the reference
rasterizer, including alpha, tilted geometry and tile boundaries. It reproduces
the user-accepted House01 files byte for byte. Install its dependencies from
`requirements-lighting.txt`; these are build dependencies, not game requirements.

The first surrounding static-brush tile contains 4,027 placements,
10,322,756 triangles and 2,556 occupied bricks. This is an intermediate result;
it has not replaced the accepted house test. A world build is **not complete or
installable** while its plan has pending categories or failed tiles. Vegetation,
merged vegetation, decals and water still require a verified inclusion/exclusion
policy. Do not clear these coverage fields merely to enable packaging.

The experimental base-material option additionally records transparent/effect
shader exclusions and any generated/animated UVs evaluated at mesh UVs. Missing
textures and malformed geometry still fail explicitly. Authored VoxelCoverage
is a byte, normalized by 255; texture clamp/repeat settings are preserved.

```powershell
.venv/Scripts/python.exe tools/world_surface_scene.py --level D:/SteamLibrary/steamapps/common/KCD2Mod/Mods/kingdomcomegluemapper/Data/Levels/kcd1_travel --pak-root D:/SteamLibrary/steamapps/common/KCD2Mod/Mods/kingdomcomegluemapper/Data --output outputs/InteriorLighting/OfflineMode1/World01/Scene --override-pak gluemapper_native_vines.pak
.venv/Scripts/python.exe tools/world_surface_landscape.py --scene outputs/InteriorLighting/OfflineMode1/World01/Scene --experimental-base-materials
.venv/Scripts/python.exe tools/world_surface_tiles.py --scene outputs/InteriorLighting/OfflineMode1/World01/Scene --experimental-base-materials
```

Local status is in `Scene/plan.json`, `Scene/build-progress.json` and per-tile
reports under `Scene/tiles`. Running the base planner again removes the landscape
augmentation from the plan; rerun the landscape stage before resuming tiles.

Transform/palette reference code was checked in the upstream engine loaders:
[CGFLoader](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/Cry3DEngine/CGF/CGFLoader.cpp)
and [terrain node loader](https://github.com/ValtoGameEngines/CryEngine/blob/master/Code/CryEngine/Cry3DEngine/terrain_node_compile.cpp).
These establish format handling; they do not prove Warhorse renderer parity.

## Optional CUDA backend experiment

`voxel_raster_cuda.cu` is a separate offline raster backend, not a change to the
game renderer. It uses ordered per-voxel processing and sorted spatial bins,
with fused multiply-add disabled to preserve the reference arithmetic. Material
textures remain on the GPU for a tile. Geometry, texture decoding, octree
traversal, compression and packaging still involve the CPU.

Build on Windows with the CUDA Toolkit and Visual Studio C++ tools:

```powershell
./tools/build_voxel_cuda.ps1
.venv/Scripts/python.exe -m unittest discover -s tests -p test_voxel_cuda.py
.venv/Scripts/python.exe tools/world_surface_tiles.py --scene outputs/InteriorLighting/OfflineMode1/World01/Scene --origin 512 3328 0 --experimental-base-materials --backend cuda --output outputs/cuda/world-comparison/cuda
```

The current build targets `sm_120` (tested RTX 5080), not every NVIDIA GPU.
The generated DLL and build metadata stay under `outputs/cuda`; source and
binary hashes are checked before loading. CUDA is optional and the world builder
continues to default to `compiled`. Missing CUDA, allocation failures and stale
binaries are explicit failures, never silently empty output. Separate `--output`
directories isolate comparison files and progress reports from the world bake.

`benchmark_voxel_cuda.py` loads a supplied house manifest once, runs alternating
CPU/CUDA builds, records timings and checks both backends against optional
accepted files. The accepted House01 tile remains byte-identical on CUDA.
Hardware tests cover alpha cutouts, ordered overlapping surfaces, clamp/repeat,
sampling rates 1/2/4/8, deterministic repetition and tile boundaries.

On 14 October 2026, the initial naive CUDA house raster took 1.57 s versus
0.32 s for warmed compiled CPU. Spatial bins reduced CUDA to 0.57 s, versus
0.33 s CPU. These include per-tile backend preparation and output generation,
but exclude loading the house source assets. They were measured while the
separate world bake was running, so they are development measurements, not
isolated hardware benchmarks. Do not extrapolate these results into a world
speedup or enable CUDA globally without a representative comparison.

The surrounding tile at origin `(512,3328,0)`, including terrain/roads, was also
compared: 10,510,062 triangles, 2,912 nodes and 2,769 populated bricks. Its
CPU and CUDA `.idx`/`.vox` files are byte-identical (combined SHA-256
`6b56187d89ef20e670bafdfe1dec41022a435637b0e12c40b2d124f43367c459`).
CPU took 167.543 s total / 96.235 s voxel generation; CUDA took 172.923 s total /
88.305 s voxel generation. This single pair ran with the background CPU world
bake active and different source-cache conditions; it is not an isolated
throughput comparison. This initial CUDA experiment demonstrated correctness,
but did not establish an end-to-end speed improvement. Later measurements and
the selected continuation policy are below.
Local measurements are in `outputs/cuda/house-benchmark-binned.json` and
`outputs/cuda/world-comparison/comparison.json`.

CUDA does not resolve the pending world geometry/material categories listed
above, nor does it perform a native KCD2 editor rebake. The installed, accepted
lighting test has not been replaced by this experiment.

## Persistent OptiX and CPU preparation improvements

Build the optional OptiX backend with `./tools/build_voxel_cuda.ps1 -Optix`.
The build obtains NVIDIA's OptiX headers at tag v9.1.0; generated SDK files,
PTX and DLLs remain under `outputs`. This uses a persistent custom-primitive
BVH for the full tile and reuses geometry and textures for every brick.
Intersection tests retain the reference double-precision arithmetic; this is
not native hardware triangle intersection or a native KCD2 editor rebake.

Archive/mesh caches, compact float32 texture storage, and two native CPU brick
workers improved the dense tile to 87.263 s. Persistent OptiX improved it to
64.859 s. Small House01 remains faster on warmed compiled CPU (0.176 s versus
0.236 s OptiX in the latest run). `--backend auto --workers 2` therefore uses
compiled CPU below one million triangles and OptiX above that threshold, with
an explicit recorded CPU fallback on GPU failure. This conservative threshold
is not a universal hardware tuning result. Default `compiled` remains available.

A subsequent cProfile comparison on the same dense tile measured 60.353 s
before and 29.346 s after two preparation changes:

- Decode byte-valued colours through a 256-entry linear colour lookup table,
  preserving the previous float32 normalization and float64 transfer function.
- Filter octree candidates in a stable native loop, avoiding repeated Nx3
  gathered arrays and Boolean temporary arrays. Keep conservative boundaries
  and triangle ordering unchanged.

Octree traversal dropped from 15.303 s to 0.983 s. Texture decoding including
colour conversion dropped from 19.405 s to 5.524 s. GPU raster calls were
13.055 s before and 11.987 s after; CPU submission/preparation was a substantial
source of GPU idle time. Profiles include background world-build contention
and are development measurements, not isolated throughput guarantees.
The dense output retains the SHA-256 above; accepted House01 also remains
byte-identical. Tests cover all 256 decoded colour values and randomized,
reordered candidate lists including boundary-touching geometry.

The actual world continuation now uses this path, retaining 211 completed tiles
after validating binary structure and hashes, starting at plan index 212.
The local audit is `Scene/preparation-fast-continuation.json`; stdout/stderr
are `World01/world-bake-preparation-fast.*.log`. Completed tiles were not
needlessly rebuilt. The accepted installed house test remains unchanged.
Batching GPU bricks remains a candidate, not a measured improvement. The
scratch-buffer experiment below tested a smaller change first.

### Follow-up experiments

With the world bake stopped to avoid contention, the dense tile took 28.008 s
on the established backend. Persistent GPU scratch buffers and removing a
redundant synchronization measured 28.370 s. Replacing per-brick Thrust scan/sort
with persistent CUB workspaces and restricting radix sort to occupied key bits
measured 27.852 s. Neither demonstrated a material end-to-end improvement;
these GPU changes were reverted rather than adding memory retention and
complexity without a measured benefit. Their outputs retained the same bytes.
Additional GPU regression tests retain coverage of changing brick dimensions,
empty candidate sets, and transitions between large and small scenes.

The retained follow-up optimization fuses the four byte-to-float colour lookups
and stores in one Numba native loop instead of gathering temporary RGB arrays.
The NumPy reference fallback remains available without Numba. The dense tile
measured 26.259 s including profiling overhead, versus 28.008 s for the prior
implementation; colour lookup time dropped from 3.387 s to 1.231 s including
native-dispatch initialization. A repeat without profiling took 25.134 s and
also retained identical bytes. Both dense and accepted house outputs remain
byte-identical. Measurements and the negative GPU experiments are recorded in
`outputs/cuda/world-comparison/follow-up-comparison.json`.

World continuation retains 243 binary/hash-verified completed tiles and starts
at index 244 with the fused texture conversion and established OptiX backend.
Its audit is `Scene/workspace-continuation.json`, and logs are
`World01/world-bake-fused-texture.*.log`. This does not change the pending
geometry/material coverage requirements or install the unfinished world bake.

## Batched GPU pipeline and hardware-triangle experiment

The production OptiX path now groups up to 64 independent bricks into each
launch. The key includes the batch's global voxel index, preserving triangle
order and preventing cross-brick mixing. Sample counts 1/2/4/8 use specialized
CUDA kernels. Specialization alone measured 25.010 s versus 25.134 s previously:
it did not establish a significant standalone speed improvement.

Two bounded CPU tasks overlap next-batch octree preparation and previous-batch
encoding/compression with the current GPU batch. Candidate index arrays are
discarded before queuing coordinates. Each output has its own array and results
are assembled in deterministic order. This overlaps CPU work with GPU work;
it does not eliminate the candidate-count readback or claim that the full
pipeline runs asynchronously on the GPU.

The same 10.5-million-triangle tile, with the world worker stopped, measured:

| Configuration | Total seconds | Voxel stage seconds | Exact reference files |
|---|---:|---:|---|
| 8-brick batches, CPU overlap | 15.321 | 7.087 | Yes |
| 16-brick batches, CPU overlap | 13.888 | 5.746 | Yes |
| 32-brick batches, CPU overlap | 12.983 | 4.912 | Yes |
| 64-brick batches, CPU overlap | 12.511 | 4.450 | Yes |
| 32-brick batches, serial CPU work | 14.463 | 6.475 | Yes |
| 32-brick batches, pinned async readback | 12.926 | 4.858 | Yes |
| 32-brick batches, reusable CUDA Graph | 12.981 | 4.914 | Yes |
| 32-brick batches, hardware triangles | 12.596 | 4.530 | **No** |

These are individual development runs, not statistical guarantees or a world
completion estimate. Raw results are in `outputs/cuda/batch-tuning/comparison.json`.
The reusable benchmark is `tools/benchmark_voxel_batches.py`; it records failed
runs and compares both output files against a supplied reference.

Defaults are `GLUEMAPPER_GPU_BATCH=64`, `GLUEMAPPER_GPU_PIPELINE=1`,
`GLUEMAPPER_GPU_ASYNC=0`, `GLUEMAPPER_GPU_GRAPHS=0` and
`GLUEMAPPER_OPTIX_TRIANGLES=0`. Pinned readback uses a nondefault CUDA stream;
the optional reusable graph covers raster and readback, updating pointers and
launch parameters between batches. Data-dependent OptiX candidate generation
remains outside the graph. Neither showed a material gain over batching alone,
so they remain opt-in experiments. Explicit GPU allocation/budget exhaustion
splits batches recursively; other errors propagate. One-brick exhaustion can
still trigger the recorded CPU fallback in `--backend auto`.

Hardware triangles use an actual built-in triangle GAS and any-hit program,
followed by the reference double-precision predicate and sorted accumulation.
They are not a production-equivalent replacement: the dense comparison changed
847 node payloads and occupancy in 51 voxels, with no node-presence changes.
Details are in `outputs/cuda/world-comparison/hardware-triangle-differences.json`.
The builder requires an isolated `--output` when this experiment is enabled;
it cannot overwrite the continuing world bake. The custom-primitive mode
remains the accepted production path.

Validation covers mixed brick sizes, large coordinates, all supported sample
counts, graph parameter/buffer updates, empty batches of geometry, allocation
retry ordering, and serial/pipelined file identity. An initial batch-coordinate
failure was caught by these tests: mixing pointers into constant and global
address spaces produced incorrect OptiX loads. Explicit scalar loads corrected
it. The erroneous experimental outputs were never used by the world build.

Continuation retains 312 binary/hash-verified completed tiles and starts at
index 313. The audit is `Scene/batch-continuation.json`. The resumed worker is
shown in a Command Prompt window at the user's request, with a persistent log.


## Coverage completion and roundoff repair (2026-10-14)

The completed initial pass had 1,219 successful tiles and one rejected tile,
`2432_2688_0128_0256`. Diagnostic channel extrema identified an albedo maximum
of `1.0000000000000002`, with finite opacity and normals. The encoder now
accepts only 32 double-precision epsilons of endpoint roundoff and clips it
before byte encoding. Non-finite values and larger violations still fail.
The repaired tile and all 1,220 initial tile pairs passed structure/hash checks.

`world_surface_coverage.py` extends an existing scene into a separate directory.
It decodes the installed vegetation group table, including the authored
`SIGC_GI_MODE` bit at offset 332, material override, and terrain-alignment
coefficient. It preserves byte-angle XYZ rotations (255 = full turn), scale,
world translation, and terrain alignment sampled from the converted heightfield.
Shared mesh caches are hard-linked; transforms are stored compactly in NPZ.
Material/texture decoding and alpha testing use the existing generic surface
importer. No hand-authored tree, house, or region lists are used.

Reference semantics were checked against the engine source:
- [Vegetation transform calculation](https://github.com/ValtoGameEngines/CryEngine/blob/release/Code/CryEngine/Cry3DEngine/Vegetation.cpp).
- [Static voxelizer object collection](https://github.com/ValtoGameEngines/CryEngine/blob/release/Code/CryEngine/Cry3DEngine/SVO/VoxelSegment.cpp).
- [Vegetation group GI flags](https://github.com/ValtoGameEngines/CryEngine/blob/release/Code/CryEngine/Cry3DEngine/terrain_compile.cpp).

The reference static object collector includes brushes and vegetation, rather
than water-volume, decal, or merged-mesh render nodes. The installed 278 water,
15,698 decal, and 83,431 merged-vegetation nodes all have zero serialized GI mode.
They are explicitly accounted for as excluded from standalone static surface
voxelization; they remain in the game world. Unknown/nonzero modes on these
excluded types fail conversion. This is a reference-derived conversion policy,
not proof of identical behavior in Warhorse's proprietary engine fork.

The 1,483,225 HLOD vegetation placements resolve to 603,634 instances in
GI-enabled groups and 879,591 in GI-disabled groups. All selected groups decoded
successfully (119 mesh/material groups). Their geometry affects 287 of the 1,220
tiles. `validate_world_surfaces.py --reuse-base` explicitly reuses the other 933
only after checking the unchanged source packages, base placements, mesh/UV/
material metadata bytes, and the validated output hashes. This compatibility
operation applies to this category-only extension and roundoff fix; it must not
be used to bless arbitrary rasterizer changes.

The expanded regression tile at origin `(2304,2560,0)` includes 1,298 vegetation
instances and 12,994,598 triangles. It completed in 20.498 seconds (12.059 seconds
preparation, 8.427 seconds voxel generation). This is a single development run,
not a world ETA or matched performance claim. The 72 focused tests passed.

`stage_world_surfaces.py` refuses incomplete category coverage, missing/corrupt
tiles, mismatched vegetation counts, and changed installed source packages. It
writes complete SVO shards and a mode-1 mission into a fresh staging directory,
checks package CRCs, and records checksums. It does not install. Any later
installation must replace the whole old SVO shard set, not overlay a differently
partitioned set of shards (which would leave duplicate tile owners).

The full expanded bake remains experimental: base-only layered materials,
terrain layer blending, vegetation translucency/native filtering and runtime
visual equivalence still require verification. Empty `pending_categories` means
all listed object categories have an explicit policy, not that native visual
parity or in-game installation has been established.

## Native vegetation GI eligibility (2026-10-15)

Direct inspection of installed native KCD2 terrain tables found `SIGC_GI_MODE`
enabled in all 597 Trosky groups and all 599 Kuttenberg groups, including grass
and forest undergrowth. The converted KCD1 table instead retained 160 enabled
and 348 disabled groups. Consequently, the previous coverage pass selected
603,634 individual placements and omitted 879,591 based on the legacy flag.

`vegetation_gi.py` now defines the shared `kcd2-vegetation-gi-v1` policy. The
vegetation importer upgrades this one group bit, preserving every other byte.
The completion importer normalizes inherited groups as well as newly appended
groups. Herb provenance matching normalizes the same bit on both sides so the
upgrade does not invalidate item registration. This is generic group conversion,
not a list of selected trees or regions.

The surface planner applies the same eligibility policy and records original
flags separately. Hidden and proxy render-node exclusions remain in place;
alpha-tested foliage keeps the existing material sampling. The staging tool
packages an upgraded `terrain.pak` together with the SVO shards and mission.
Both runtime eligibility and baked inputs must be installed together.

`reuse_equivalent_world_tiles.py` is a narrowly scoped migration for this
eligibility-only change. A freshly regenerated scene must match the previous
asset catalog, decoded mesh arrays, material bindings and base placements.
Only tiles with identical vegetation mesh/transform multisets may be reused.
Reference reports must match the supplied pre-change builder digest, supported
sample count/backend settings and verified voxel hashes. It is not permission
to reuse results across rasterizer or shader changes.

This observation establishes vegetation group eligibility, not that native
KCD2 voxelizes every grass blade. Merged vegetation remains excluded from the
standalone static-node pass under the existing reference-derived policy.
Native translucency/filtering parity and the forest's in-game appearance still
need verification after the expanded bake is installed.

The native comparison also found zero serialized GI mode on all 46,569 Trosky
and 64,236 Kuttenberg merged-vegetation nodes, matching the converted world's
83,431 such nodes. This supports retaining the existing separate merged-node
treatment; group eligibility is the demonstrated mismatch. The evidence is
`World01/native-vegetation-gi-audit.json` under the offline-lighting outputs.

The fresh plan selects 1,483,225 individual vegetation instances, with 879,591
legacy-disabled instances upgraded. Equivalent-input validation retained 932
tiles and identified 288 for rebuilding. `SceneNativeGI01` and
`StagedNativeGI01` are separate from the previously installed coverage build.

`install_world_surfaces.py` verifies staged hashes/CRCs, unique tile ownership,
the full previous shard set, and baseline installed hashes. It requires the
game to be closed, retains the old package set under a new recovery directory,
verifies copied files, replaces the complete set, and rolls back on failure.
The receipt records installation verification separately from in-game testing.

## Inventory exit crash investigation (2026-10-15)

User reproduced a crash on ESC from inventory after changing equipped garments.
The preserved log ends at ApseClose. The minidump identifies an access violation
reading 0x1ba8 at CryRenderD3D12.dll RVA 0x3ac882 (BugSplat displays 0x3ab882).
Instruction analysis identifies CSvoGiStage::ExecuteComputeShader, called with
ComputeClearBricks from the TI_INJECT_CLEAR path. The caller adds 0x1b50 to a
null stage member at offset 0x16b0; the faulting instruction reads +0x58.
This establishes a missing GI render object, not a clothing-renderer stack.
Device Removed is No. It does not by itself establish why the object is missing.

The converted mission disabled UpdateGeometry while native Trosky uses 1 with
IntegrationMode=1 and StreamVoxels=1. configure_environment now preserves this
native runtime update configuration for surface bakes. Installed only that
mission attribute change; voxel PAKs and clothing assets were not replaced.
Evidence, crash dump, original log, backup and installation hashes are under
outputs/InventoryExitCrash. Eight world-surface tests pass. Inventory exit
reproduction after this candidate correction remains required; it is not yet a
confirmed crash fix.

The user subsequently confirmed the inventory ESC crash is fixed after installing
this single-setting correction. This is runtime confirmation for the reported
inventory-to-world transition, not a claim that all GI lifecycle paths are tested.
