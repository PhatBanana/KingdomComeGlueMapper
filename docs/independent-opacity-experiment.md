# Independent geometry-opacity experiment

`tools/geometry_opacity.py` is a NumPy implementation of a bounded, three-axis
surface-coverage sampler. It reads the installed converted CGFs and a placement
manifest. It does not depend on an editor, proprietary voxelizer, OpenVDB, or
Embree, and does not reuse CryEngine voxelization implementation code.

This is a diagnostic stage, **not a replacement GI bake**. It writes NPZ, PNG,
and JSON evidence only. It does not modify the game or emit installable voxel
files. Native KCD2 equivalence has not been established.

## Run

The placement manifest is an array of objects containing `mesh`, optional
`material`, and `transform` (12 row-major floats for a 3x4 world transform).
`mesh` and `material` resolve to virtual asset paths in the supplied PAK folder.
Ambiguous duplicate asset paths fail instead of guessing archive precedence.

```powershell
python tools/geometry_opacity.py `
  --manifest outputs/InteriorLighting/NativeBake01/installed-house.json `
  --pak-root D:/SteamLibrary/steamapps/common/KCD2Mod/Mods/kingdomcomegluemapper/Data `
  --output outputs/InteriorLighting/IndependentBake03 `
  --cell-size 0.25 --samples 4 --geometry-only
```

Use a new output directory. The example manifest and generated game-derived
geometry are local ignored outputs, not redistributed repository assets.

## What is measured

- Reads compiled render positions, indices, subset bindings and the explicit
  world placement. Physics-proxy and LOD nodes are excluded.
- Applies the world transform once, before sampling; world X/Y/Z directions
  therefore change correctly when a building rotates.
- Casts a regular subpixel grid through each projected triangle, accumulating a
  union of sample bits per cell and axis. Duplicate faces do not add opacity.
- Stores three coverage channels in an array indexed `[z,y,x,axis]`, plus the
  exact origin, cell size and source triangles. Channels are independent world
  X/Y/Z coverage, not a claim about native byte-channel order.
- Uses half-open voxel cells. Does not fill the building's interior. Openings
  stay empty if no other geometry covers them. Thin subpixel geometry may be
  missed; increase sampling/resolution to measure sensitivity.
- Audits material bindings and counts triangles requiring transparency, decal,
  or shadow-proxy policy. Geometry-only sampling includes these triangles as
  opaque for inspection; that result must not be installed as a finished bake.

Only supported static root meshes with identity local transforms are accepted.
Nonidentity or parented render nodes fail explicitly until their CGF transform
conventions can be tested. This differs from the supported world transform,
which can include rotation, scale and translation.

## Henry's house result, 12 October 2026

Local report: `outputs/InteriorLighting/IndependentBake02/report.json`.

| Measurement | Result |
|---|---:|
| Converted building parts | 4 |
| Render triangles | 25,859 |
| Cell size | 0.25 m |
| Samples per cell face | 16 |
| Grid dimensions X/Y/Z | 46 / 84 / 54 |
| Cells with sampled coverage | 30,459 |
| Triangles needing material policy | 10,206 |

The fixture includes the accepted `building_blend` floor and roof meshes.
The report retains each input SHA-256, material attributes and world transform.
The PNG is a geometric coverage visualization, not a rendered lighting result.

## Native reference attempt

The saved `gm_native_house_bake` editor scene remains on disk. Running
`wh_ed_ExportSvo` after enabling geometry updates reached the native exporter.
The log ended with `There are 0 streamable layers with objects`. The editor
process then exited, and the script did not reach its post-export checkpoint.
No valid native SVI/SVV reference pair was verified. This does not establish
whether the exit was a crash or an exporter-controlled exit, nor whether the
streamable-layer count caused it.

`e_svoTI_StreamVoxels` is not a registered CVar in this build and has been
removed from the local export script. The earlier warning was not evidence
that streamed voxels had been enabled.

The scratch scene's material appearance also needs verification before its
cubemaps could be treated as a radiance reference. A returned cubemap command
alone does not validate the scene's shading.

## Remaining acceptance work

1. Establish a native export fixture with a verified nonempty SVI/SVV result.
   Inspect native layer/export prerequisites and output locations; do not
   repeatedly invoke the failing command against the user's saved scene.
2. Verify native axis/channel order, coverage/filtering and alpha metadata on
   isolated planes, a sloped roof and an open window at matched transforms.
3. Implement and validate material alpha sampling and native decal/shadow-proxy
   inclusion rules. The present report identifies the affected subsets.
4. Only then connect the independent result to the native-format writer and
   test it in an isolated level before replacing any installed tile.
5. Rebuild/validate probe clipping separately. Replacing opacity data does not
   itself prove that the upper probe stops affecting the exterior roof.

No albedo, normal, radiance, probe-capture or clip-volume data is synthesized by
this tool. Those are separate dependencies, not missing channels that can be
filled with defaults.

## Validation

`python -m unittest discover -s tests -p test_geometry_opacity.py -v`

Eleven tests cover axis-specific coverage, transformed walls, sloped roofs,
open windows, overlapping faces, boundaries, degeneracy, malformed grids,
CGF render/proxy selection, invalid indices and unverified local transforms.
The full suite passed with 490 tests after this addition. These are geometry
and parser checks; they do not assert visual or binary equivalence to KCD2.
