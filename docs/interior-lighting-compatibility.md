# Interior lighting compatibility audit — 14 October 2026

The installed converted world is not using the same lighting configuration or
voxel payload as the shipped KCD2 worlds. This is a verified compatibility gap,
not yet a demonstrated cause of the reported bright eyelid rims on native Henry.
No game settings, shaders, materials or installed packages were changed by this audit.

## Evidence inspected

- Current KCD1 `Data/Levels/rataje/level.pak` and `svo.pak`.
- Current KCD2 `Data/Levels/trosecko` and `Data/Levels/kutnohorsko` mission settings
  and a voxel tile from each world.
- Installed mod `Data/Levels/kcd1_travel/level.pak`, all mod archives for additional
  voxel payloads, and its sole installed voxel tile.
- KCD2 `Engine/Shaders.pak`: Eye.cfx, ForwardShading.cfi, TiledShading.cfi.
- Native EnvironmentLight.lua and the probe, exposure and voxel converters.

Local extracted evidence is under
`outputs/InteriorLightingAudit/NativeComparison20261014/`. Proprietary shader
extracts remain local; this document summarizes the behavior without embedding them.

## Packaged configuration comparison

| Setting/data | KCD1 Rataje | Native KCD2 Trosky and Kuttenberg | Installed converted world |
| --- | --- | --- | --- |
| GI active | 1 | 1 | 1 |
| IntegrationMode | 0 | 1 | 0 |
| UseLightProbes | 0 | 0 | 1 |
| HighGlossOcclusion | 1 | 1 | 1 |
| Voxel payload | legacy opacity | sampled native channel mask 7 | channel mask 1, opacity only |
| Voxel coverage on disk | 257 archive entries | 414 / 428 index and voxel entries | 2 entries: one index/voxel pair |

Counts are archive entries, not equal units of geometry. The installed tile is
`terrain/svo/0640_3456_0128_0256`, covering the Skalitz test area. Its presence
does not prove every wall/roof correctly occludes light. Missing other tiles do
not by themselves explain the artifact inside this tile.

`world_voxels.configure_environment` deliberately selects mode 0 and enables
probe lighting; `voxel_lighting` expands source opacity without fabricating
albedo or normal channels. This is a fallback lighting path, not a native mode-1
bake. Switching the mode flag alone would not supply the missing data.

## Actual shader behavior

KCD2 TiledShading.cfi's ApplyGI implementation distinguishes:

- Mode 0: multiplies accumulated diffuse probe lighting by the GI texture and
  attenuates specular according to GI, smoothness and reflectance.
- Mode 1: replaces diffuse probe lighting with GI irradiance and adjusts
  specular using the ratio of GI and existing diffuse illumination.
- Mode 2: replaces both diffuse and specular with the GI textures.

Eye.cfx uses tiled forward lighting with deferred GI inputs, sun shadows,
local lights and optional three-point lighting. The normal eye path samples
probes and applies a separate eye-overlay occlusion texture. Its specular-overlay
variant disables probe sampling. Therefore a bright eyelid/tearline cannot be
attributed to an environment reflection alone without identifying the active
material variant and isolating direct/conversation lighting.

## What conversion already does, and what remains unverified

The cubemap converter translates nine source bake times to eleven target times,
resamples existing roughness levels and emits native-sized BC6H textures. It
retains source captured radiance; it does not recapture the converted scene.
File compatibility is not proof of matching physical light levels or matching
roughness filtering between engines.

Fresh probe audit: native Trosky has 683 EnvironmentLight entities with zero
visibility-bypass flags and zero explicit deferred clip bounds. The installed
world has 1,035 probes, zero visibility bypasses and 13 explicit clip bindings.
The source has 1,057 probes; differing counts also reflect world/layer selection.
These counts do not establish that any individual imported clip is wrong.

The installed exposure profiles cap EV Min at 4. Native default Trosky profiles
commonly use approximately 8, with other values in special profiles. This change
allows stronger adaptation in dark rooms; it does not correct the relative
balance of eye highlights and skin. The actual exposure at the screenshot was
not measured.

## Next verification boundary

1. Isolate the visible eye-rim material and direct/three-point light contribution
   with a fixed camera, time, pose and exposure; restore each diagnostic change.
2. Compare probe diffuse/specular and GI outputs in that same view before
   changing light multipliers or exposure.
3. For native mode-1 parity, generate the missing voxel surface channels from
   converted geometry/materials or validate an equivalent source conversion;
   then test native mode 1 with native probe integration settings.
4. Validate world coverage separately and reconsider the EV adjustment only
   after light transport and probe balance are correct.

The live MCP read failed, so these are verified packaged settings and shader
branches, not captured runtime CVars or GPU pass measurements. Henry's eye-rim
root cause remains unconfirmed.

Engine background: Crytek's official SVOGI documentation describes opacity-only
mode 0 and the extra albedo/normal data in advanced modes. KCD2-specific behavior
above was verified against the installed Warhorse shaders, not inferred solely
from upstream documentation:
https://www.cryengine.com/docs/static/engines/cryengine-5/categories/23756816/pages/25535599
