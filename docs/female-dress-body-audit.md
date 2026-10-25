# Female dress and arm visibility audit — 24 October 2026

The report of missing arms has a confirmed failure in converted pickup dresses.
The report of unusually thin arms in some NPC outfits still needs a rendered
comparison of the affected outfit. These are separate findings.

## Confirmed pickup layer defect

The current installed package contains 76 female component roots: 20 person
outfits and 56 pickup garments. Fifty pickup dress definitions in
`Data/gluemapper_containers_00.pak` use a torso element with
`KeepBodyLayer="false"`.

Both the imported female body and the shipped native female body include the
arms and hands in their torso element. Replacing that element with a dress
therefore also removes the skin exposed by its sleeves. Male imports use
separate torso, arm, hand, leg and foot elements, so the same torso replacement
does not remove their independent arms and hands.

The shipped KCD2 `CharacterComponent.xml` provides corroborating registration
evidence: `F_SimpleDress` inherits its torso layer from `F_Dress`, whose torso
`SkinElement` has `BodyLayerId="5"` and `KeepBodyLayer="true"`. The converter
looked up the native layer number but replaced the native body-retention policy
with a rule intended for split male bodies.

`world_item_clothing.py` now retains the female body beneath converted garments.
`setup_female_clothing.py` repairs the existing owned female pickup torso
definitions without rebuilding their textures or meshes. It checks the affected
archive against the package receipt and writes through setup's atomic archive
replacement, preserving hard-linked saved checkpoints. The scan is repeated on
resume, so an old upgrade marker cannot hide newly restored converter output.
Native definitions and male layer policy are unchanged.

Four regression tests cover the actual converter's emitted female/male
registrations, ownership filtering, idempotent saved-package upgrade, unrelated
archive entries, hard-linked checkpoint preservation and refusal to modify a
changed archive.

This corrects a registration defect; it does not certify every dress's fit or
replace the broader clothing coverage work. Retaining body geometry can expose
intersections that the erroneous whole-body removal previously concealed.

## Person outfits and thin arms

The 20 installed female person outfits already retain their body layer. Their
coverage generator, rather than whole-layer replacement, hides vertices beneath
the clothing. The installed complete body has 3,210 vertices; 437 are primarily
weighted to upper-arm, forearm or elbow joints. Across the imported outfits,
273–434 of those arm vertices have membership in an equipped garment's hiding
group. Those counts vary with the outfit, but are not by themselves evidence
of erroneous hiding: long sleeves should conceal most of the underlying arms.

The female body and fixed outfits share the anatomical landmark warp. For the
source female body's arm vertices, the measured warp Jacobian singular values
range from about 0.804 to 1.220. That allows local compression of about 20% in
one direction, not proof of the specific visual defect. The applied source
`A_Chest` morph changes no arm vertices, so a chest-fitting adjustment would
not address the reported arms.

Two further compatibility boundaries remain:

- Pickup female garments do not currently apply the shared anatomical warp used
  by converted female person bodies and fixed outfits. Their bind-space fitting
  therefore needs comparison when a converted item is equipped on either body.
- The fixed-outfit coverage stage allocates bits 4–7 within the torso element.
  Those indices also carry native female hiding semantics. Arbitrary mixing of
  converted outfits and native clothes has not been verified as a complete
  coverage contract. Whole-body retention alone cannot resolve that contract.

No general scaling, guessed limb thickening or blanket removal of coverage has
been applied. An affected NPC's live clothing-manager selection and arm/sleeve
appearance are still required to identify the remaining visual fault.

Local read-only evidence is in `reports/female-dress/installed-components.json`
and `reports/female-dress/affected-dresses.json`, with source and installed body
meshes retained only in that ignored directory. No proprietary assets are
included in this change, and the audit did not change the installed mod.
