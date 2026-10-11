# Stable appearance and stash repair

The imported KCD1 female base mesh contains limbs rather than a complete torso.
Keeping that mesh underneath a dress cannot supply missing shoulders or chest
geometry. The generic female appearance builder now attaches the complete KCD2
female body with its matching native material/UVs, retaining source skin colour.
Imported heads, hair, garments and item identities remain unchanged. Native body
LOD meshes are included when available. This is a deliberate native body
substitution, not a claim of exact KCD1 body-shape preservation.

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

Validation: focused body/material and stash identity tests, official mod-tools
CharacterComponent deserialization, and an archive comparison confirming no
entries removed. The repair changes only the character component table, character
and chest assets, and the stash entity in the level mission. Terrain is unchanged.
The reported nearby ground hole is not proven to be caused by the floating stash
and remains a separate visual investigation. Shoulder seams, dress clipping,
chest placement and shop operation require in-game acceptance.
