# Interior lighting conversion

The travel/world build now converts the original Rattay world's initial-state
`EnvironmentLight`, `ReflexLight`, and `ClipVolume` records. Building materials
alone do not provide these scene-level lighting volumes. This stage runs in the
normal Python `region_travel.build` pipeline and stays inside the combined mod.

## Native contract

- Positions, parent transforms, rotated probe boxes, attenuation, priority,
  projection, source activity, and supported authored properties are retained.
- Properties are read from both games' installed Lua defaults without executing
  Lua. Source defaults are overlaid with the authored XML, then translated into
  the native schema. New native properties retain KCD2 defaults, except the
  reflex light's new thick-wall and vertical-camera clipping models: KCD1 has
  no data to author those correctly, so both are explicitly disabled.
- Local lights use `PerInstanceStreamable` and conservative world-aligned bounds
  relative to the entity origin. The global probe remains nonstreamed. This
  follows native entity metadata; it is not a measured performance claim.
- KCD1's extra PC shadow tier (`7`) maps to KCD2's Experimental tier (`5`), as
  verified against the installed `sys_spec_Light.cfg` files. Tiers 0–4 retain
  their values.
- Clip geometry uses the same observed `CrCh` 0x746 chunk versions as KCD2.
  Geometry stays in the generated level; IDs, GUIDs, paths and light links are
  remapped. Referenced dependencies must resolve. A single unreferenced source
  clip whose geometry is absent is logged and omitted.

The initial-layer selection is the same policy used by the world/furniture
builder. Quest-specific alternative lighting is not activated wholesale. Link
dependencies are followed explicitly.

## HDR cubemaps and time of day

KCD1's nine baked samples are at 03:40, 04:40, 05:00, 08:00, 13:00, 18:00,
21:00, 21:20 and 22:20. KCD2's eleven native samples are at 03:00, 04:00, 04:45,
05:45, 07:00, 13:00, 19:00, 20:15, 21:15, 22:00 and 23:00. The builder verifies
the target schedule and 128px BC6H atlas format against installed Trosky assets.

The converter reconstructs the source cube faces and streaming mips, decodes
BC6H to linear half-float HDR, resamples the authored prefiltered roughness
levels, and interpolates the source lighting at the native times, including
the midnight wrap. Irradiance and specular cubes are converted separately.
There is no tone mapping, sRGB conversion, or generation of reflection mips
from only the sharpest image. Reflex-light samples are interpolated as
`colour × multiplier` radiance, then factored back into native properties.

This adapts the existing bake, not a fresh KCD2 bake. Upscaling a 32px source
does not create additional scene detail. Lighting/material differences between
the engines can still require a later rebake in the editor.

Each dynamic entity's cube set lives under the generated level/name path.
Static mine probes retain explicit source selections. The temporary single
Trosky daytime probe is replaced with the KCD1 global probe schedule. The
native inventory/UI probes remain untouched.

Missing source bakes are explicit: the entity's volume is recorded, but its
light is disabled. The converter does not substitute another room's cubemap.
Current owned source data has 15 such probes, listed individually in the build
report. Seven further probes already have `bActive=0` in the source.

## Tool and packaging

HDR decoding/encoding uses Microsoft's [DirectXTex texconv](https://github.com/microsoft/DirectXTex/wiki/Texconv),
May 2026 release, SHA-256
`dcfdec10244e02cf5037fba089c55fb7e1326b1c8181742d77d15fa5cb5eef06`.
Source builds download this pinned tool into their build directory on first
use. The setup EXE build bundles it and its MIT license; frozen self-test
checks its hash. Game content is never bundled in the source or setup EXE.

Four bounded workers convert content-addressed schedules. Completed outputs
are hash-checked on cache reuse. Intermediate float textures are discarded
after successful encoding.

The final DDS repacker uses native RC's layout: three resident specular mips
and separate six-face high-resolution chunks. Payloads match KCD2's RC repack.
Headers additionally carry the native probes' `0x200011` flags (split, cubemap,
and suppress engine resolution reduction), which generic RC repacking does
not infer from a standard DDS. Linear BC6H pixels remain unchanged.
PAKs are stored, non-ZIP64, and sharded below 1 GiB.

## Test build

`tools/build_lighting_test.py` stages changes to an existing combined mod. It
does not install or launch the game. Pass `--source`, `--target`, `--mod` and
`--output`; optional `--cache` reuses a previous conversion directory. The
package audit checks CRCs, duplicate paths, links, cubemap references, sizes
and complete streaming mip families.

Local build `outputs/InteriorLighting/Build06` contains 1,033 probe records,
2,271 reflex lights, 992 clipping volumes, and one linked area. Of the probes,
1,011 are enabled after preserving source activity and disabling missing bakes.
The package audit resolved 21,482 active cubemap references and 54,091 asset
entries across three PAKs. Ordinary point/spot/torch lights are outside this
stage; existing cooking/fire lighting is unchanged.

Automated tests cover periodic time interpolation, source/native defaults,
rotated bounds, prefiltered roughness retention, HDR face/mip serialization,
native DDS streaming round trips, and shadow-tier mapping. In-game visual
acceptance remains separate from these format and package checks.

The first runtime comparison of Henry's house exposed a second issue: Trosky's
active voxel GI settings were copied into a world with no loaded SVO data.
The engine reported zero voxel nodes; temporarily toggling `e_svoTI_Apply`
off restored dark, warm interior lighting using the same materials. Toggling
`UseLightProbes` alone did not resolve the grey ambient wash.

The probe-only conversion stage disables voxel GI until voxel dependencies
have been built. The normal world builder and lighting test builder now follow
that stage with `world_voxels.build` and enable native basic GI (mode 0) with
`UseLightProbes=1`. This uses the available source opacity bake; it does not
claim to reconstruct the albedo/normal channels required by advanced GI.

## Voxel conversion (2026-10-12)

`voxel_lighting.py` validates KCD1's recursive `.dat` records, compressed
payload lengths, crop bounds, and layer identities. It expands the source
sqrt-encoded opacity nibbles to linear channels and combines only layer zero
and the same initial-state layers selected by the static world builder.
Other state layers are excluded, including unused burned-town alternatives.

The output is native SVI3 `.idx` and SVV3 `.vox` data with explicit spatial
keys, channel masks, payload offsets and compressed blocks. Packaging uses
stored, non-ZIP64 `svo-part*.pak` files below 800 MiB. The source bake remains
an approximation for the converted geometry; no new geometry bake is claimed.

`build_voxel_test.py` stages this dependency independently of the cubemap
conversion. `--tile` produces an explicitly partial development test. Normal
builds convert all 256 source tiles. The completed local full-map stage has
1,737,920 nodes and 1,108,018 payload blocks. Every generated tile passed the
format validator and the final archives passed CRC checks.

Runtime validation so far covers the single tile containing Henry's house:
KCD2 loaded the tree, displayed its debug boxes, and reported nonzero SVO
counters using mode 0. The full-map stage has not yet received runtime testing.
The black exterior remained in that test. This is a restored GI dependency,
not visual acceptance of the complete material/probe conversion.

Automated tests cover malformed references, cycles, truncated records,
decompression sizes, channel expansion, and exclusion of inactive layers.

### Full-block placement correction and clipping test (2026-10-12)

The sampled native Trosky index references 5,784 payloads, all with 16x16x16
dimensions and zero crop offsets. The converter now expands each legacy crop
into a zero-filled 16x16x16 block, placing cells in z/y/x storage order at the
original crop coordinates. Node origins, octants and physical cell size stay
unchanged. Regression checks exercise nonzero, unequal x/y/z crop offsets and
confirm that cells outside the source crop remain empty.

Focused installed package: `outputs/InteriorLighting/Bounds01`, with backups
of the replaced level and voxel packages. It retains the committed building
material assets. With the local probes disabled and voxel GI enabled, the
earlier rectangular artifact is absent in `screenshot_261012_133444.jpg`.
This is single-tile runtime evidence, not full-map validation.

The same development package tests explicit capture-to-clip links for probes
26456 and 26457. Strict BSP containment places their capture points in source
clips 8756 and 8795 respectively. Runtime `CountLinks()` reports one link on
each probe; `GetLinkTarget()` returning nil is not sufficient to diagnose a
broken link because a native clip entity need not expose a Lua script table.
The upper probe still causes an exterior artifact when enabled. Neither the
candidate association nor area-only flags have passed visual acceptance.

`lighting_clips.associate_probe_clips` therefore defaults to read-only
candidate reporting. Normal conversion does not invent these links. Its
explicit `apply=True` mode is for controlled development tests only. Existing
authored links are retained. The world audit found 246 unique containment
candidates and 56 outside captures; containment alone does not prove the
desired light influence region. No global exposure, brightness, or GI-disable
workaround is baked into this correction.

## Packaged area-contract audit (2026-10-12)

`tools/audit_lighting_contract.py` compares source Rataje, shipped Trosky and
the installed converted level without modifying the game. Pass `--source`,
`--target`, `--mod`, and a JSON `--output`. It resolves Lua defaults before
comparing entity options, inspects clip CGF chunks and BSP child indices,
and distinguishes probe entity positions from their offset bake positions.
Counts include the records in all XML layers, not just currently active lights.

The inspected Trosky package has 683 probe records, none with
`bIgnoresVisAreas=1` or `bDeferredClipBounds=1`. The earlier Build09 converted package had
334 and 304 respectively. Build10 normalizes the area flags to native defaults
and requests explicit clipping only when an actual source link exists. That
normalization did not eliminate the exterior artifact. Successful texture/CRC
checks do not validate lighting influence regions.

At Henry's house, the three converted clip CGFs match the source bytes.
Their mesh and BSP chunk versions agree with the inspected native example,
and all BSP indices are valid. This is structural compatibility, not proof
of correct registration in the KCD2 renderer.

The main room probe `skalice_forge_probe_2` has its entity origin inside
`ClipVolume_henryhouse_d`, while its rotated `GenOffsetY=-7` puts its bake
origin inside `ClipVolume_henryhouse_a`. Neither house probe has an explicit
clip link. Automatically assigning a probe to the volume containing its
entity origin would therefore associate the main room bake with a different
volume. This needs a deliberate dependency conversion, not a blanket flag
change or nearest-volume guess.

Runtime isolation confirmed that disabling the two house probes removes
the dark exterior wall/bench artifact. Changing their area flags also
removes it, but loses the accepted interior balance. The area-only experiment
is not a validated fix and has not been saved into the converter.
The complete package check still resolves 21,482 cubemap references across
54,091 entries with valid CRCs and streaming mip families. Window shafts
and the final indoor/outdoor lighting conversion remain unfinished.

## Remaining material comparison

The user's KCD1 exterior reference shows grey shingles with patchy moss and
pale plaster. The converted exterior still appears almost black. Compare
blend masks, secondary UVs, shader permutations, and per-layer parameters
against the original before changing material brightness. The current second
detail-map compatibility mapping is not a verified fix for this artifact.
