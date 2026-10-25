# Source clothing fitting and composition

This conversion is shared by source-person appearance builds. It contains no
NPC-name, soul-ID, outfit-ID, coordinate, or per-dress scale exceptions. The
developer workbench remains under `tools/clothing_lab`; consumer Setup has no
new clothing-test UI.

## Cause and conversion rule

The previous male fixed-outfit path joined the selected source garments without
applying their authored underlayer fitting shapes. The female path applied
`#A_Shrink` across an entire inner dress whenever another torso layer existed.
That also shrank exposed undersleeves. The affected female source mesh's shrink
shape moves some vertices by approximately 100 mm.

`tools/clothing_fitting.py` now:

1. Resolves each source garment's coverage through KCD1
   `armor_archetype2body_subpart` and the actual `body_layer.layer_order` values.
   Mesh filename suffixes and numeric layer IDs are not ordering rules.
2. Resolves the selected source variant and source material cutouts. A higher
   torso garment can cover a lower garment's leg subparts where the tables
   specify that relationship.
3. Applies the authored fitting morph only at covered vertices. Exposed sleeves,
   hems, and cutouts retain their selected source shape. Shared render/internal
   vertices must agree; malformed masks fail conversion.
4. Carries proven pre-fit coverage through deformation. Male fixed outfits keep
   this membership when merged and when their native material features are
   written. Female garments retain coverage conditional on the covering garment.
5. Recomputes fitting masks for authored source LOD meshes instead of applying a
   vertex array from another topology. Native animation/LOD certification remains
   separate from this conversion operation.

Fitting uses the finest converted-equivalent alpha mip to define a garment's
physical cut. Requiring every distant mip to agree was found to leave large
unfitted bands near UV islands. Body visibility retains its separate conservative
opacity checks. Mixed ordering across shared body subparts is not given an
arbitrary global winner; it still needs a per-subpart solution and review.

## Native equipment and body coverage follow-up

`clothing_equipment.NativeEquipment` resolves source archetype **names** against
KCD2's `armor_archetype` table and reads occupancy from
`armor_archetype2body_subpart`, `body_subpart` and `equipment_part`. It does not
copy numeric IDs or invent an outer layer. The inner and outer source dresses
previously both used the native simple-dress archetype; drawing one at layer 9
did not give it a different equipment slot. Their distinct named native
counterparts now supply both the archetype and layer. The same resolver is used
by person appearances and wearable item conversion. Renamed types retain the
existing visual-family default with an explicit fallback reason in evidence;
missing/ambiguous region assignments fail.

Female visual families are classified by source equipment regions, including
meshes without modular filenames. No named dress or actor is special-cased.
The lab validates native equipment occupancy separately from the visual family,
including exclusive-slot collisions between different archetype IDs.

Source bodies also have authored fitting shapes. The composition pass now
applies `A_Shrink` to body vertices beneath opaque clothing, preserving exposed
vertices. This removed the remaining male skin-intersection diagnostic samples
in the five-outfit candidate. It does not generate a new shrink scale. As with garment fitting,
this is a baked outfit candidate; changing outfits at runtime needs separate
validation and compatible fitted/mask variants.

Merged male outfits retain body regions and hide only covered surfaces. Masks
use actual converted alpha, exclude already-hidden garment triangles, preserve
uncertain welded seams, and retain boundary vertices adjacent to uncovered
triangles. Female ordering comes from source subpart contracts, not filename
layer suffixes. Coverage is rebuilt independently for each authored mesh LOD.
The vertex boundary check does not prove continuous coverage inside triangles.

The lab now follows triangle visibility for diagnostics and does not call an
inner shirt behind opaque outer clothing visible skin clipping. It records the
actual loaded model and effective LOD for every part. A part with only a base
mesh retains that mesh at farther requested LODs; a missing base or broken
non-contiguous LOD chain still fails. The selected fixtures' clothes mostly have
only base meshes, while heads/hair supply their own LODs. This is explicit in the
report, not evidence of generated garment LODs.

## Validation on 2026-10-25

Current developer overlay signature:
`b8f2b80c6ec239cc7eb818596f652758a6003d80c9c67944ab16d16e5b35abcd`.

- [x] Resolved source layer contracts for all 381 male/female clothing records
  in the previous pass (354 male, 27 female; table coverage only).
- [x] Resolved native equipment contracts for all 27 female source records:
  22 exact archetype-name matches and 5 recorded visual-family defaults.
- [x] Rebuilt five source outfits using the shared converter: `ska_blanka`,
  `rato_innkeeper1`, `ska_woman27`, `ska_guard2`, and `ska_fatherOfHenry`.
- [x] Validated those five outfits at requested LODs 0, 1 and 2: 15 cases,
  zero catalog errors and zero asset errors. Effective per-part LODs are recorded.
- [x] Captured front, back, side, synthetic 60-degree forearm bend, requested
  LOD 2, and masks-on/off views for all five rebuilt outfits. Reviewed the
  assembled female sleeves and male front views. A separate body-on/off render
  confirms the guard's skin-coloured boot details and Father's apron-top strip
  belong to the clothing; they remain when the body component is disabled.
- [x] Eliminated shared-archetype conflicts in the layered female fixture and
  hidden-skin-without-cover/body-region-replacement findings in all five cases.
- [x] Passed 129 targeted tests, including native occupancy, arbitrary source
  filenames, exposed seams, coverage at different LOD topologies, body fitting,
  actual triangle visibility and opaque outer-cover diagnostics.
- [ ] Resolve the remaining layered female intersection candidates.
- [ ] Replace or validate male fixed-outfit registration against independent
  native equipment contracts. It still spans several regions under one Coat role.
- [ ] Rerun the full combination matrix on a fully rebuilt package.
- [ ] Verify KCD2 equip/unequip, native animation and cloth simulation.

| Source outfit | Equipment checks | Geometry at requested LODs 0 / 1 / 2 | Status |
| --- | --- | --- | --- |
| `ska_woman27` | Pass | No findings | Checked by the developer validator |
| `ska_blanka` | Pass; distinct dress occupancy | 3 skin samples and 22 inner/outer garment samples flagged at each requested LOD | Review |
| `rato_innkeeper1` (`gluemapper_rattay`) | 6 fixed-outfit layer differences | No skin coverage/intersection findings | Review |
| `ska_guard2` | 6 fixed-outfit layer differences | No skin coverage/intersection findings | Review |
| `ska_fatherOfHenry` | 6 fixed-outfit layer differences | No skin coverage/intersection findings | Review |

These are normal-ray diagnostic samples, not measured visible pixels or proof
of a native animation defect. They remain in the report. None of these cases is
certified by the KCD2 runtime. The old confirmed-combination CSV belongs to its
original package signature and has not been re-certified by this candidate.

Local evidence (generated game assets are excluded from Git):

- `reports/clothing-lab/equipment-overlay-v4-20261025/geometry.json`
- `reports/clothing-lab/equipment-overlay-v4-20261025/source-equipment.json`
- `reports/clothing-lab/rendered-equipment-v4-20261025/capture.json`
- `reports/clothing-lab/rendered-equipment-v4-20261025/body-isolation.json`
- `reports/clothing-lab/rendered-equipment-v4-20261025/`
- `reports/clothing-lab/equipment-candidate-v4-20261025/`
- `reports/clothing-lab/equipment-regressions-v4-20261025/`

The developer overlay replaces existing component definitions by identity,
including entries in shared tables. It does not add duplicate definitions. This
candidate has not been installed. To inspect it in the developer tool:

```powershell
.venv\Scripts\python.exe tools/clothing_lab_app.py `
  --package "D:\SteamLibrary\steamapps\common\KingdomComeDeliverance2\Mods\kingdomcomegluemapper" `
  --target "D:\SteamLibrary\steamapps\common\KingdomComeDeliverance2" `
  --overlay "reports/clothing-lab/equipment-overlay-v4-20261025"
```

The **masks disabled** comparison intentionally reveals normally hidden surfaces.
Acceptance uses the assembled masked view, geometry diagnostics and ultimately
the native runtime. Arm-bend preview poses are synthetic deformation checks;
they are not KCD2 animation or cloth simulation.
