# Building material import audit

Inspected 2026-10-12 against installed KCD1/KCD2 shader source and the current
developer mod. The material repair is implemented and a focused test package
is installed; whole-map and frozen-installer validation remain outstanding.

## Confirmed lossy conversion

`static_assets.convert_material_features` renames `[1] Diffuse` to `Opacity`
for Illum's SNDUVS permutation. It removes the existing Opacity texture.
The new slot is correct for KCD2, but removing the old input without converting
its contribution is not equivalent to KCD1's material.

KCD1 CommonZPass passes the tiled mask sampled in primary UVs and the second-UV
texture alpha to shadeLib's blending function. For positive BlendFactor:

```
source = saturate(pow(secondUV.alpha * tiledMask.red * (1 + factor), falloff))
target = saturate(pow(secondUV.alpha * (1 + factor), falloff))
```

The installed KCD2 shadeLib explicitly reads alpha as the blend channel when
SNDUVS is enabled. Its call supplies 1 for the separate alpha argument. Merely
copying BlendFactor, BlendFalloff and the source second-UV texture therefore
loses the tiled mask's influence.

Observed affected submaterials:

| Source material | Submaterial | Discarded input |
| --- | --- | --- |
| `6x15_roof_p_3.mtl` | `roof_01_diff.dds` | `textures/structures/roof/roof_01_mask.tif` |
| `6x15_basefloor_p_2.mtl` | `timbered_wall_01` | `textures/structures/wood/timbered_wall_01_whiteblend_mask.tif` |

These control roof/moss and timber/plaster layering. The user's KCD1 reference
shows patchy moss, grey shingles and pale plaster; the current converted
appearance previously did not match those layers.

## Verified preservation

The installed roof's 319 and wall's 217 referenced texture-family members
matched the selected source bytes, including streaming mips and split alpha.
These are reference checks, not counts of unique files. There were no missing
or mismatched members in that comparison. Raw texture copying does not explain
this particular loss; shader input conversion does.

The inspected source and target vertex shaders decode secondary UVs from the
same vertex-color component pairs using the same constants. The static mesh
importer rewrites material-name chunks, not those vertex streams.

## Implemented correction and remaining checks

A native data conversion must preserve the product of the tiled primary-UV
mask and the authored second-UV alpha. Baking that product into the native
second-UV alpha requires the mesh's primary-to-secondary UV correspondence;
resizing and multiplying the two images directly is not sufficient. RGB must
remain available for the existing second-UV colour modulation. Shared material
textures, mip generation and overlapping UV regions need explicit handling.

Negative BlendFactor values also have different semantics in the two shader
implementations: KCD2 uses the absolute magnitude and inverts the result.
They require separate conversion if encountered.

Source secondary diffuse sampling explicitly requests sRGB; the inspected
KCD2 opacity binding has no equivalent annotation. Verify the actual native
resource view/texture flags before claiming a colour-space defect or applying
gamma correction. The second detail map's new native input is a separate
compatibility change and is not proof that the moss mask was converted.

The converter now creates a separate secondary-UV atlas per geometry/material
pair. Source secondary UVs overlap in this roof, so multiplying into the old
texture cannot preserve different primary-UV mask samples at those overlaps.
The new atlas retains secondary colour and stores the combined mask in alpha;
the mesh's positions, primary UVs and physics chunks remain unchanged. RGB
filtering uses linear light, alpha is filtered independently, and output has
BC3 sRGB mipmaps. Negative source factors are folded into alpha. Unsupported
secondary detail mapping and non-identity mask/secondary texture modifiers
raise errors rather than discarding their contributions.

`outputs/BuildingBlend/Build06` supplies unique roof/wall asset paths and updates
12 placements. Two other material variants are unchanged. Original level and
terrain packages are retained in its backup directory. Package CRCs and
installed hashes were checked. The native client loads the converted assets,
and the user confirmed the improved appearance. This is not a full-map build.

Runtime isolation separates two remaining lighting effects from this repair:

- Disabling `gm_lighting_26456` and `gm_lighting_26457` removes the broad black
  exterior contribution, but a dark rectangular patch remains.
- With those probes still disabled, `e_svoTI_Apply 0` removes that rectangle.
  Compare screenshots `screenshot_261012_124935.jpg` and
  `screenshot_261012_125355.jpg` in the user's KCD2 screenshots directory.

These are temporary console diagnostics, not a permanent lighting solution.
They implicate the active voxel GI contribution but do not yet identify which
voxel data field or transform is incorrect. The active single-house voxel test
must be checked before drawing conclusions about the full-map voxel conversion.

Native EnvironmentLight exposes area-only, visibility-area and deferred-clip
options; its inspected script contains no player-entry lighting toggle. The
source house probes request deferred clipping without explicit entity links;
the current converter enables deferred clipping only for explicitly linked
probes. That discrepancy needs further verification against the native clip
association mechanism. Native Trosky also contains VisibilityArea entities,
but their script is under Entities/AI: their presence alone is not evidence of
a missing renderer interior/exterior trigger.

Local detailed evidence: `outputs/InteriorLightingAudit/building-texture-import.json`;
installed shader extracts under `outputs/InteriorLightingAudit/shaders/`.

## Secondary-UV authoring comparison

A follow-up read-only audit compared the installed KCD2 developer shaders with
the retail `IPL_Objects-part*.pak` materials. Among 1,041 material files under
`Objects/manmade/structures`, 13,450 Illum submaterial entries include only seven
with `%SNDUVS`. Filtering those entries to diffuse texture paths containing
`roof` finds 1,294 entries, none with `%SNDUVS`; 1,036 enable vertex colors and
338 enable blend layers. These are material entries, including repeated uses
and potentially unused assets, not counts of unique buildings or loaded draws.

This distinguishes shader support from native authoring practice: KCD2 still
supports secondary-UV color multiplication, but none of the sampled native roof
materials requests it. Native roofs also retain material self-shadowing: 674
entries explicitly store a positive `SelfShadowStrength`. New lighting is not
evidence that all legacy material shadow terms should be disabled.

Both CommonZPass implementations multiply albedo by `4 * secondaryRGB`. KCD2
keeps vertex color neutral when `%SNDUVS` is enabled, so its unconditional
`2 * IN.Color.rgb` multiplication is not, by itself, a second application of
the packed UV values. The native shader still separates surface color from
the lighting calculation.

The effective KCD1 roof secondary texture was read from
`Data/patch/ipl_patch_010701.pak`: it is a 512x512 BC3 sRGB texture. Its RGB
contains spatial weathering and shading-like variation; its alpha contains
the moss placement pattern. RGB pixels are not black (channel minima are
49, 52, 41). With the source sRGB decode, median per-channel albedo multipliers
are approximately 0.86, 0.85, 0.83. This texture can darken the surface, but its
contents alone do not prove that it is a directional lightmap or the cause of
the remaining sharp black boundary.

A subsequent runtime comparison kept the secondary alpha blocks and UVs while
replacing only RGB with a constant intended to neutralize the multiplier.
The sharp black roof patch remained. Disabling the upper environment probe
removed it while normal tree shadows and voxel GI remained enabled. The
original secondary RGB package was restored; removing `%SNDUVS` or the alpha
would also have removed authored moss information.

Local evidence is in `outputs/InteriorLightingAudit/RoofShaderCompatibility/`,
including native material records, current native shader extracts, source
texture statistics and separate RGB/alpha previews. The measured clip-volume
repair is documented in `roof-clip-repair.md`.
