# Building roof clipping conversion

The accepted Henry's-house fix is now a geometry-driven package pass. It
checks placed building roofs across the converted level and trims only clip
volumes for which the mesh provides a verified separating surface.

## Evidence and cause

At Henry's house in Skalitz, the upper probe is `gm_lighting_26457` and its
clip is `gm_lighting_8795`. The clip's rendered mesh and BSP included exterior
shingles on one roof slope. Linking the probe to that original volume could
not exclude those surfaces. The opposite roof slope remained outside the
volume, explaining the side-dependent result.

A neutral secondary-RGB experiment retained every alpha block and left the
black patch visible. Turning off the upper probe removed the patch while
voxel GI and ordinary tree shadows remained enabled. Original secondary RGB
was restored. The material detail fix also remains: KCD2's secondary detail
texture uses the Emittance slot, with its transform in Custom.

The initial accepted clip fit found a 0.0923 m gap between the authored inner
roof and exterior shingles. Its plane sits halfway through that gap, with
about 0.0461 m clearance on each side. It retained all 110 previously contained
interior-roof centroids and excluded 67 exterior centroids. Both the rendered
clip surface and BSP changed; the user confirmed the result works.

Local evidence: `outputs/InteriorLighting/RoofClip01/report.json` and
`outputs/InteriorLightingAudit/ClipSurface01/cross-section.png`.

## Conversion

`tools/roof_clip_repair.py` reads the final combined package, so the actual
converted meshes, material overrides and HLOD placements are available.
`travel_bridge_package.combine` runs it before calculating the receipt hashes.
It writes `roof-clip-repair.json` into the package and detaches rewritten files
from any hard-linked base package.

The pass:

1. Resolves authored inner/outer roof submaterials on the placed render mesh.
   Physics, LOD and helper geometry cannot supply roof triangles. It supports
   float/half positions, packed position/color/UV streams, node hierarchies,
   mirrored node transforms and rotated/scaled world placements.
2. Uses overlap only to find candidates. Interior-roof containment establishes
   ownership; the clip bounds and BSP are both checked. Bare BSP half-spaces
   must not associate distant buildings or probes.
3. Fits a separating plane between matching pitched surfaces within their
   shared footprint. A minimum 2 cm gap is required. Previously contained
   interior-roof vertices and centroids must remain inside.
4. Intersects the rendered mesh, caps the cut, welds submillimetre export seams,
   and requires a closed, consistently wound surface. It updates native mesh
   bounds and prepends the same half-space to the CPU BSP. Multiple contours
   and fits without a valid closed result are rejected.
5. Links active source-authored deferred probes only when their rotated and
   scaled capture offset lies in exactly one clip among all loaded clips, and
   that clip has a verified repair. Explicit conflicting links and disabled
   probes are preserved. Linked probes use deferred clipping, area-only mode
   and normal visibility-area handling.

This changes clip CGFs and qualified probe links/options. It does not change
the building meshes, material textures, moss masks, cubemaps, probe influence
boxes, voxel payloads, GI settings or exposure. The developer baseline retains
the previous lower-Henry-probe disabled state; this pass does not toggle it.

Node transform and packed stream decoding follow the published
[CGF loader](https://raw.githubusercontent.com/ValtoGameEngines/CryEngine/release/Code/CryEngine/Cry3DEngine/CGF/CGFLoader.cpp)
and [vertex declarations](https://raw.githubusercontent.com/ValtoGameEngines/CryEngine/release/Code/CryEngine/CryCommon/CryRenderer/VertexFormats.h),
cross-checked against the installed files. These are format references, not
claims that the public renderer is identical to KCD2.

## Staging an existing developer installation

```powershell
python tools/roof_clip_repair.py `
  --mod 'D:\SteamLibrary\steamapps\common\KCD2Mod\Mods\kingdomcomegluemapper' `
  --source 'D:\SteamLibrary\steamapps\common\KingdomComeDeliverance' `
  --output outputs/InteriorLighting/RoofClipMap
```

Use a fresh output directory. This command stages `level.pak` and a report;
it does not install or launch. Close the game, preserve the installed level,
check its hash against `source_sha256`, then replace only that level PAK.

## Map validation

The development scan examines 167,167 brush placements and identifies 295
placed roofs with usable inner and outer surfaces. On the accepted installed
baseline it repairs **15 additional clip volumes**, across 15 building
placements, and links **six probes**. Henry's already accepted clip is retained.
One initially proposed additional cut was rejected by the closed-surface
check. Roofs without a usable separating surface remain unchanged; the report
records why each proposed fit was rejected. These counts are specific to the
current package, not a claim that every building needed a repair.

Evidence is staged in `outputs/InteriorLighting/RoofClipMap05/`. CRC/member
checks limit the changes to 15 clip CGFs and `objects_mission0.xml`. Reapplying
the pass produces no changes. Independent ray containment checks sample 512
points per repaired volume and compare the rendered intersection with the
original mesh plus the new half-space, while checking for newly introduced
render/BSP disagreements. Closed-surface checks use the packed float vertices.

Unit coverage includes rotated/scaled placements and capture offsets,
ambiguous volumes, explicit ownership, disabled probes, bounded BSP queries,
packed vertex streams, node transforms, seam welding, rebuild idempotence and
package receipt hashes. Binary and sampled geometry checks do not constitute
a visual signoff for every building on the map.

The map package was installed with a hash-checked backup and KCD2 loaded it
successfully. The user accepted the current version as a checkpoint and asked
to move on. No further gap reduction was applied. This acceptance does not
replace full-map visual coverage; the generated report keeps its conservative
`runtime_verified=false` field.
