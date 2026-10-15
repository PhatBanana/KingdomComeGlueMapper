# Starting clothing audit — 15 October 2026

## Finding

Henry's original outfit is authored in KCD1, but the converted New Game path
does not apply it. Live attachment-manager inspection confirms the current native
player has body/head/hair and underwear, with no equipped shirt, hood, boots or
trousers. This establishes an equipment-initialization gap independently of the
recent lighting diagnosis.

## Source and installed evidence

- Patched source `rpg/soul` identifies `dude` as
  `43144483-f3bb-fab8-9ceb-f77e3020598a`. Its initial clothing preset is
  `40f91af6-8aa6-fa06-c171-785c048b0893`, named `Henry_default`.
- The placed source player in `Data/Levels/rataje/level.pak:whdata_0` explicitly
  uses that same preset in `StaticData/InitialClothingDescription/PresetId`.
  This is not inferred from a similarly named NPC or a screenshot.
- The preset contains one each, equipped: `boots_002`
  (`00000000-0000-0000-0000-00000000001c`), `hood_004_down_ptacek`
  (`42e146c8-f2d1-1db1-c44c-7482b0f307b2`), `shirt_002_green`
  (`4e6ec506-03c3-d8fd-e1ec-f6882ea314b4`) and `pants_005`
  (`4f07bb72-5fa2-8f1e-dd38-3cd78b4785a6`). The initial weapon preset is empty.
- Installed `kcd1_travel/level.pak:whdata_0` retains the native KCD2 player
  identity `4c2dcffb-dea1-6263-72d7-b39f4db2d8b5`, with no source outfit override.
  `region_travel.py` intentionally preserves that identity for cross-region
  travel. New Game requires a separate once-only equipment initialization.
- Installed `gluemappertravel.pak:Quests/GlueTravel/GlueTravel_kcd1.xml` connects
  `gm_kcd1_character_creation_initialize` to source starting stats/skills and
  hunger, but contains no equipment/inventory initialization operations.
- `campaign_initial_loadout.resolve` can resolve the source preset;
  `equipment_sequence` generates CreateItem/EquipItem operations. Repository
  references show the latter is only called by tests, not by a runtime builder.
  `SoulAdapter.plan` discovers dependencies but `SoulAdapter.convert` remains
  unimplemented. Dependency discovery therefore does not equip the player.
- Installed container-item tables define the boots, hood and green shirt under
  their source IDs and reference converted clothing components. A scan of the
  installed root mod PAK XML found no reference to the source trousers ID.
  Existing item definitions alone do not prove their visual assets work on Henry.
- Read-only runtime evidence is retained locally at
  `outputs/StartingClothingAudit/Dude.xml`; its only clothing attachment is native
  underwear. No equipment was added or removed during this audit.

## Required repair and acceptance

Resolve the selected source player instance's initial preset, import its complete
item/clothing dependency closure, and apply the resulting equipment through the
protected New Game initialization before the opening conversation. Use the generic
adapter and registered item mapping, not a hard-coded list for Henry. Verify
clothing compatibility with the native body and facial setup.

Test all four worn pieces on a fresh New Game, including the opening dialogue.
Then verify save/load and region return do not grant duplicates or replace gear
earned during play.

## Repair installed

`build_campaign_initial_loadout.py` now resolves the explicitly selected source
instance, imports missing items through the existing item/clothing converters,
merges localization, and emits native CreateItems/EquipPlayersItem nodes through
`campaign_initial_loadout.bind_player_before`. Item descriptors connect creation
to equipping; source amounts and equipped flags are preserved. The binding selects
an existing protected New Game edge rather than a level-load event.

The developer installation receipt is at
`outputs/StartingClothingFix02/installation.json`. The missing trousers were
converted and the other three registered items reused. The outfit is applied
before starting-stat initialization. Six targeted tests pass, including preservation
of the New Game gate and unrelated restoration edge. The interior probe repair
was installed at the same restart. Fresh New Game visual verification, fit and
save/load duplication checks are still pending; installation is not runtime proof.

## First runtime comparison

The user's inventory comparison confirms that all four items are created and
equipped. It also exposes incorrect scarf colour, visible body intersections and
initial condition below 100. The wearable converter retained legacy Illum shader
permutations and visibility data; unlike fixed NPC outfits, it had not invoked
the native character-material/vertex-feature upgrade. It now uses that existing
upgrade, clears legacy hiding membership, and replaces covered torso/leg/foot
body layers. Source geometry and authored colour settings remain the inputs.
CreateItems now supplies explicit Health=1 and Condition=1 instead of the native
-1 defaults. The appearance update is staged in
`outputs/StartingClothingAppearance01`, with baseline hashes and exact changed
archive entries recorded in `install-plan.json`; visual acceptance is pending.
This update was subsequently installed with the game closed and the game
relaunched; `installation.json` records all five replacement/additional PAK hashes.

The reference also shows a main-level difference and door/trunk keys absent from
the converted inventory screenshot. These have not been established as clothing
conversion defects or repaired by this appearance update. The strength/speech
values differ between the screenshots, so matching choice paths is necessary for
a meaningful level comparison.

## Second runtime comparison and repair

The next user screenshot confirms all four items now start at condition 100.
The scarf remained green, cloth looked glossy, and the shoulder intersected.
Source hood colour variants support a half-turn hue scale: blue is zero,
red is -0.888889 and yellow is 0.905556. The generic appearance conversion
now maps these normalized values to 180 degrees rather than 360; this scale
is inferred from authored variants and still requires visual confirmation.

The native clothing material donor's MacroSpecularScale=0.75 introduced a
micro-reflectance floor even when imported specular was dark. Converted Illum
materials now use scale 1 and neutral Specular because the original material
constant is already included in the baked map. Converted male sleeved upper
garments also use the native MaleBodyUpperArms hiding group to retain hands
and forearms while masking the upper arm under the garment.

`tools/build_wearable_repair.py` rebuilds source-ID-selected wearables and
updates their owning PAKs without registering duplicate component tables.
`outputs/StartingClothingAppearance03/installation.json` records the five
validated installed PAKs and backup baselines. All 15 focused clothing,
initial-loadout and localization tests pass. Appearance and fit remain
pending in-game verification; no level/stat or quest-key fixes are claimed.
