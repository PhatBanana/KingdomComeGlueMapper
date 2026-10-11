# Stable appearance and stash repair

The standard KCD1 `s2_body` contains limbs rather than a complete torso. Its
source companion `s2_body_v2` supplies the upper torso in the same source texture
layout and proportions. Both body and clothes pass through the shared rig warp.
The earlier complete KCD2 body substitution protruded through the source dress
in the user's live test and has been replaced.

`clothing_coverage.py` resolves the exact source mesh/material pair in
`clothing_raycast`, validates its triangle counts and reads the visible/opaque
triangle masks. It generates native conditional hiding groups for each garment:
outer layers can hide covered body and inner-garment vertices, while exposed
regions remain available. Mesh triangles, UVs and weights are retained. Removing
the covering item deactivates its group rather than requiring deleted geometry
to be regenerated. The fallback underwear activates the same body coverage as
the matching source undergarment.

Coverage is generated with bounded surface-normal rays (6 cm inward, 12 cm
outward) against opaque triangles after fitting. This is an explicit conversion
policy, not a reproduction of the proprietary KCD1 runtime. The source chest
fit and covered inner-garment shrink morphs are baked into this fixed source
outfit. Arbitrary wardrobe swaps and runtime fitting-morph changes are not yet
validated. Four independent covering garments are supported; outfits exceeding
that allocation and missing source opacity records fail explicitly.

The horse shop's stash previously inherited the nonvisual shop marker's position
at `(3550.2366, 1516.1052, 131.51202)`. Its actual KCD1 linked stash is at
`(3588.7971, 1514.8624, 128.45)`. The builder now resolves that link, imports the
authored chest01 model/materials/animations, and preserves the stash's generated
shop stock and destination GUID. The chest is fixed at its authored transform.

Existing test installations can be patched without rebuilding scenery, quests
or voice data:

```powershell
python tools/build_stable_visual_fix.py --source <KCD1> --target <KCD2> --mod <installed-mod> --output <fresh-D-drive-output>
```

The command stages three PAKs and a baseline/output hash report; it does not
replace files used by a running game. Install only with the game closed and
after verifying baseline hashes. Existing saves may retain old entity transforms;
test the corrected placement with a fresh developer level load first.

Validation: coverage/mask, rig conversion and stash identity tests, plus official
mod-tools CharacterComponent and ClothingHidingGroup deserialization. The same
conversion was built for Zora and Theresa's different source outfits. The targeted
patch updates Zora only; it preserves other installed characters, quests, audio
and terrain. Future female appearance builds use the shared coverage converter.
The reported nearby ground hole is not proven to be caused by the floating stash
and remains a separate visual investigation. Shoulder seams, dress clipping,
chest placement and shop operation require in-game acceptance.
