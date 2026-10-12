# Probe clipping comparison

`tools/build_probe_clip_comparison.py` creates local test packages without
installing them. It reads the installed games; extracted game assets remain
under ignored `outputs/` and must not be redistributed.

## Authored control

The KCD2 modding tools include this actual editor layer:

`Data/Levels/trosecko/Layers/main/tvid_vidlak/M01_intro/_enviro.lyr`

The generated `native-house-control.lyr` contains exactly its house brush,
EnvironmentProbe and ClipVolume. Transforms, original identities, source geometry
and properties are retained. Import it into a separate scratch editor level
with the installed native assets, not into Trosky where those identities already
exist. It retains the original world position near (1172,3390,103). Generate
cubemaps in the scratch level before using its lighting as a visual control;
the layer alone does not carry a bake for a new level.

The generator matches the probe and clip by GUID to their actual shipped
exports and saves `native-house-export.xml` and the compiled clip geometry.
This avoids matching duplicate clip names to unrelated volumes.

This native example has no explicit probe link. Its effective options are
`bAffectsThisAreaOnly=0`, `bIgnoresVisAreas=0`, `bDeferredClipBounds=0`.
That establishes one real native authoring pattern, not a universal clipping rule.
KCD1 Henry-house probes and three clip volumes are extracted separately from
the shipped level, with both games' script defaults. No KCD1 editor installation
was located and no claim of a KCD1 editor export made during this test is intended.

## Runtime cases at Henry's house

All cases retain the installed material fixes, capture offsets, probe boxes,
transforms, clip geometry and all other level entries. The lower house probe is
disabled in every case to isolate the upper probe.

| Case | Upper probe | Explicit link | Area only |
| --- | --- | --- | --- |
| 00_probe_off | Off | No | No |
| 01_native_unlinked | On | No | No |
| 02_explicit_clip | On | To original upper-house clip | No |
| 03_explicit_clip_area_only | On | Same link | Yes |

Case 01 uses native **clipping flags**, retaining the converted KCD1 cubemap and
other authored lighting values. Case 02 changes the explicit link plus its
required deferred-clipping flag. Case 03 changes only area-only behavior.

Generate with:

```powershell
python tools/build_probe_clip_comparison.py `
  --source 'D:\SteamLibrary\steamapps\common\KingdomComeDeliverance' `
  --target 'D:\SteamLibrary\steamapps\common\KCD2Mod' `
  --mod 'D:\SteamLibrary\steamapps\common\KCD2Mod\Mods\kingdomcomegluemapper' `
  --output outputs/InteriorLighting/ClipComparison02
```

Choose a new output directory for each generation. Packages are partial test
overrides of the existing mod, not standalone playable maps. No installation
or launch is performed by the generator. CRC checks and member hashes verify
that only `objects_mission0.xml` changed; the corrected installed SVO tile remains
a separate dependency.

For a runtime comparison, back up the installed level and replace only its
`level.pak` while the game is closed. Start each case with the same fresh map
load, time, weather, camera, graphics settings and exposure settling interval.
Capture the exterior roof and an interior view. Keep voxel GI enabled throughout.
Compare 00/01 for the upper probe's contribution, 01/02 for explicit clipping,
and 02/03 for area-only behavior. Also test a roof point known to lie outside
the actual clip mesh: a capture point inside a BSP is not evidence that the
renderer's stencil excludes exterior surfaces.

If 02/03 still affect exterior surfaces, the next controlled comparison is the
native editor's compiled clip versus the source clip, including its registration
and geometry boundary. Do not shrink boxes, darken materials or disable GI to
declare clipping fixed. Restore the baseline package after the experiment.

## Current validation

`outputs/InteriorLighting/ClipComparison02/comparison.json` records four generated
packages with passing CRC and unchanged non-entity entries. The native editor
fixture was matched to the shipped entities. That original comparison report
retains its generation-time `runtime_verified=false` status. Subsequent native
tests isolated the upper probe, and a geometry audit found that its clip
actually contained exterior roof surfaces. The user accepted a repair to both
the rendered clip and its BSP. See `roof-clip-repair.md` for the measured fix
and the bounded map-wide conversion, which supersede the unresolved status.
