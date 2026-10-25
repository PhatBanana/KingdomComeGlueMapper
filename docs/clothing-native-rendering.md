# Native clothing selection and workbench parity

## Confirmed cause

On 25 October 2026, the public KCD2 Modding Tools runtime showed Bianca's
underdress in the torso slot cache, but `AttachmentsByName/clothing_torso`
contained only her outer dress. Both garments' hiding groups were active.
The lower garment hid body skin even though its sleeves were not drawn.
The developer workbench incorrectly rendered both garment meshes and therefore
concealed this defect. Distinct inventory archetypes alone did not solve it.

The green-dress stall trader is `ska_merchant4`. The previous `ska_woman27`
fixture was a different person and did not validate that trader.

## General conversion correction

After source fitting, native material conversion and coverage generation,
`clothing_native_composition.py` groups source garments by equipment region.
It uses KCD2's `body_layer.xml` order to select the regional owner, canonicalizes
the source skeleton palettes, and composes all required surfaces into its mesh.
Every source triangle and material subset is retained at each authored LOD;
shorter LOD chains retain their last level. Coverage bits and all constituent
hiding-group declarations are retained.

The overlapping source layers become one regional outfit item. Lower items
are removed from that preset and item table instead of claiming they can be
independently removed while remaining baked into the outer mesh. Shoes, headwear
and other non-overlapping regions remain separate. The source underwear
fallback keeps its existing appearance identity. This is source-outfit
composition, not arbitrary runtime recombination of independently equipped items.
There are no NPC-name, dress-name, coordinate or per-item scale exceptions.

Native material features also require identical vertex RGBA in the render
stream and the internal skinning buffer. Conversion now writes both through
the render-to-internal remap and rejects conflicting seam values. The previous
candidate had 21 affected mesh files. The new four-person candidate has 47
meshes and no such discrepancies.

Composed multi-materials deduplicate identical feature-slot declarations.
KCD2 scopes these declarations across the whole multi-material; repeating
them in each source submaterial produced native errors. Conflicting slot
meanings fail conversion and are also rejected by the workbench.

Coverage uses the actual converted surface and the finest texture alpha cut.
The trader's two dress textures have 1x1 alpha averages of approximately 0.47
and 0.72, below their 0.77 and 0.75 cutout thresholds. Requiring every mip to
pass incorrectly rejected every covering triangle and left skin visible
through the bodice. Bilinear footprints at the authored cut and conservative
triangle boundaries still preserve necklines and cutouts. Legacy KCD1
triangle-culling caches no longer override the converted surface. Texture
filtering and distant appearance still need native checks.

## Developer workbench correction

- Select the highest native layer per region; do not draw every selected item.
- Retain hiding groups from equipped but unselected lower layers.
- Apply the selected owner's `KeepBodyLayer`, not a discarded lower owner's.
- Honor native material two-sided flags instead of always drawing backfaces.
- Report render/internal colour-buffer disagreements as errors.
- Exclude discarded region layers from confirmed combination counts.
- Invalidate earlier matrix/checklist evidence using validation contract 4.

The masks-disabled view changes hiding bits only; it does not bring discarded
native attachments back into view. Native physics, animations and shader
appearance still require an engine test.

## Current bounded package

`reports/clothing-lab/native-regions-v8-20261025/` contains the private rebuilt
package, recovery baseline, source conversion receipts, and native screenshots.
It rebuilds Bianca, the affected stall trader, Father and `ska_guard2` from
their source soul records. Installation uses the verified transaction and
does not modify unrelated world/schedule resources.

- [x] Regression reproduces a discarded inner mesh with an active skin mask.
- [x] Region composition retains source triangles, materials and LODs.
- [x] Native material colour buffers agree for all 47 rebuilt meshes.
- [x] Installed through the package verification transaction.
- [x] Native v7 capture: Bianca's under-sleeves render during sweeping.
- [x] Native v7 capture: the affected trader's sleeves and arms render.
- [x] Native v7 inspection catches remaining bodice clipping; v8 corrects coverage.
- [x] Native v8 capture: trader arms remain visible and the large bodice skin patches are removed.
- [x] Native v8 capture: Father's coat and under-sleeves are present (front/animated seam coverage remains limited).
- [x] 342 focused tests pass: 87 clothing, 242 character, 8 material-effects and 5 appearance-upgrade tests.
- [ ] Review the trader's remaining nine bind-pose intersection vertices; do not certify all poses from the front screenshot.
- [x] Identify the olive long-sleeved outfit as `ska_woman9`, source `s2_cotte_007` / `#V_006`.
- [ ] Confirm the reported narrow silhouette against a native source-game comparison; do not treat buffer repair as a proven proportion fix.
- [ ] Rebuild and verify the entire remaining wardrobe with contract 4.
- [ ] Separately resolve the reported missing gate guards.

The native run used the public Modding Tools 1.5.5 executable in a window and
a fresh Skalitz new game. It did not load an existing save. Live attachment
inspection confirms `outfit_torso.skin` for Bianca and the trader. Useful native
captures are `native-regions-v7-20261025/runtime/bianca-before.png`,
`native-regions-v7-20261025/runtime/bianca-after-close.png`, and
`native-regions-v8-20261025/runtime/trader-front.png` under the report root.
The engine no longer reports duplicate feature slots for the composed outfits.
The installed candidate rebuilds these four people only; the shared converter
applies the correction to subsequent source appearance builds. This report
does not imply that every already-installed NPC has been rebuilt.

Earlier workbench screenshots and passing geometry counts are historical
evidence, not native visual approval of this package.

## Additional native candidate, 26 October

`reports/clothing-lab/native-regions-v9-20261026/` extends the installed v8
package by rebuilding `ska_woman9` and `ska_woman6` through the same converter.
The other four rebuilt fixtures remain installed. Its 16 new mesh files have
matching render/internal RGBA. The olive outfit passes the bind-pose geometry
checks; the layered green outfit retains the same nine conservative skin
intersection findings as the trader. These are reviews, not visual approvals.

The old olive dress had a blue material-feature byte mismatch at all 1,319
vertices (render 224, internal 255). Its alpha hiding bytes agreed. The repair
therefore corrects material-feature input, not a demonstrated dimensional shrink.
The selected source variant is `#V_006`, no `A_Shrink` is applied to the dress,
and all garment vertex positions are unchanged by this rebuild. Existing rig
fitting narrows measured torso sections by roughly 2–6 percent relative to the
source variant; a render-buffer repair alone cannot certify that silhouette.
No per-NPC or per-dress widening has been added.

The v9 native test used another fresh Skalitz game in the public Modding Tools
(35.13 seconds level load). Reflection selected `outfit_torso.skin` for
`ska_woman6` and the original single-garment `part3.skin` for `ska_woman9`.
The layered outfit's inner sleeves/hands rendered, and the olive outfit
rendered during sweeping. Captures are `runtime/woman6-sleeves.png` and
`runtime/woman9-sweeping.png`; both are limited by interior lighting and are
not silhouette approval. Fly mode was disabled and AI updates restored after
testing. The remaining proportion and seam reviews stay open.
