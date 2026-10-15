# Particle lighting audit — 15 October 2026

## Result

Live testing isolated a disabled lower interior environment probe. Restoring
its authored active state corrected the white sweeping debris; the user also
confirmed Henry's eyelid rims were fixed in conversation. No particle-library,
head-material or shader override was required for these confirmed results.

The dust cloud became difficult to see after the lighting correction. Its
visibility and smoke elsewhere remain unverified; the eye screenshot does not
establish that every particle effect is fixed.

## Local evidence

- `tools/world_environment.py` resolves environmental effect names against the
  target's native particle catalog. It does not install KCD1 particle libraries.
- Inspected `Libs/Particles` definitions in SDK and retail `IPL_GameData.pak`
  match byte-for-byte for the selected libraries containing sweeping and Vranik
  smoke effects. The audit enumerated 118 matching effect nodes per target.
- No particle library, material or texture path overrides were found in the
  installed mod's top-level Data PAKs. This does not exclude level-local resources
  or effects created dynamically through scripts.
- Native `workBehaviors.housework.sweeping` uses `cloud_b_diff`, a brown-tinted
  Color, DiffuseLighting=0.2, DiffuseBacklighting=0.6 and ReceiveShadows=true.
  Its straw child uses DiffuseLighting=0.2, DiffuseBacklighting=0.5 and
  ReceiveShadows=true. These are target-authored values, not copied KCD1 values.
- KCD1's corresponding dust used `smoke_a_diff` and DiffuseLighting=0.6;
  its straw child used 0.5. Replacing the target definition with the source
  settings would undo an intentional native difference.
- The referenced cloud, straw and smoke DDS headers exist in the SDK's
  `IPL_Textures-part1.pak`. This existence check does not establish live mip
  residency, successful shader compilation or the exact effect seen onscreen.
- Native `Materials/particles/cloud_b_nm.mtl` and `smoke_a_nm.mtl` use the
  `Particles` shader. Native reference head material `m_head_000_b00.mtl` instead
  has `HumanSkin` and `Eye` submaterials. The specific offending eyelid surface
  has not yet been identified; it must not be assumed to use a particle shader.

Raw local findings: `outputs/ParticleLightingAudit/audit.json`.

## Runtime evidence and persistent repair

Native particle shader inspection shows that its ambient contribution samples
the selected environment cubemap. Correct opaque SVOGI lighting does not establish
correct particle illumination. The eyelid surface was not independently isolated;
the shared probe diagnosis is supported by the live visual result, not by treating
eyes as particles.

The lower probe (`gm_lighting_26456`, source `skalice_forge_probe_2`) was authored
active but disabled in the developer baseline. Its influence box reaches the
floor; the active upper probe's box starts above the floor. Temporarily removing
the outdoor/global probe removed the excessive brightness. Restoring all original
probes and enabling the lower interior probe corrected the debris and eyelid rims.
The native GI/shadow settings were restored to 1, reflex lights restored, and the
temporary soft-particle diagnostic restored to its original value. Bounded test
emitters were stopped. The accepted live change is only lower-probe activation.

`tools/probe_activation.py` reconciles disabled converted EnvironmentLights against
active source layers. It restores an authored active probe only after validating
its complete BC6H cubemap payloads, including both specular and diffuse textures
at all eleven native times for dynamic probes. Missing bakes, source-disabled
probes and deferred layers remain disabled. Bounds, links, multipliers, priorities,
textures and geometry are preserved. No room/entity ID is encoded in the repair.
`travel_bridge_package.combine` runs this reconciliation on incremental builds.

The staged repair at `outputs/ParticleLightingAudit/ProbeActivation02` restores one
probe, validates 22 cubemaps and preserves five missing-bake disables. Archive
verification confirms all entries outside `objects_mission0.xml` are unchanged.
The running session uses the verified live activation; the staged PAK requires
installation with the game closed. A fresh-launch visual check is still required.

The probe correction was subsequently installed with the game closed and retained
through the clothing and inventory-exit repairs. The user confirmed the eyelid
appearance fixed; broader smoke-effect coverage has not been exhaustively tested.
