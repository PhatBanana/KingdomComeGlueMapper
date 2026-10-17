# Backup versus clean setup audit, 18 October 2026

Reference: `D:/SteamLibrary/steamapps/common/Backup/kingdomcomegluemapper`.
Candidate: the retail setup package copied into `KCD2Mod/Mods/kingdomcomegluemapper`.
The candidate has recipe version 1. Its local manifest permits the development
build as well as retail; its gameplay archives have not been restored from backup.

## Confirmed omissions

The backup's `kcd1_travel` mission contains 16 NPC placements. The candidate
contains five: coachman, innkeeper, Theresa, Peshek and Zdena. Eleven exact
entity GUIDs are absent, including `ska_motherOfHenry`, `ska_fatherOfHenry`,
`ska_blanka`, `ska_fricek`, `ska_kunes`, `ska_matus`, `ska_matej`, `ska_sarka`,
`ska_woman5`, `ska_guard2` and `vra_vanek`.

The mother is missing at all of these levels: mission placement, soul/role and
appearance registration, and opening scene wiring. This is a package omission,
not evidence of a shader failing to render an otherwise spawned mother.

The reference travel project includes `gm_kcd1_character_creation`, its once-only
state/entry wiring, source baseline stats/skills, quest-start state, and initial
loadout operations. The candidate has the travel/services project and an
`open_world` node instead. It lacks `gm_imported_scene/q_skalitz.xml` and
`gm_imported_scene/gm_kcd1_character_creation.xml`.

| Feature | Backup evidence absent from candidate | Existing implementation to integrate |
| --- | --- | --- |
| Opening scene and mother | Actor, quest, dialogue and scene bindings | `campaign_scene_test`, `campaign_dialogue`, `campaign_dialogue_runtime` |
| Opening initialization | Baseline operations and initial-loadout package | `build_campaign_initial_state`, `build_campaign_initial_loadout` |
| Additional people | Ten `gm_person_*` packages and associated registrations | `build_quest_people_test`, source appearance adapters |
| Voice and facial data | `Localization/English.pak`: 294 OGG files plus index; 32 facial entries | `build_actor_dialogues_test`, `build_dialogue_facials` |
| Quest interactions/items | Additional quest/combat graphs, quest-item and placeholder-item resources | Existing quest/combat/item adapters; preserve their graph dependencies |
| Character props/work | `gm_character_props.pak` and additional actor schedules | `build_playable_slice`, `world_character_props`, profile/schedule builders |
| Starting/wearable surfaces | Initial-loadout, wearable-material and surface namespaces | Source item/material conversion; clothing composition remains unfinished |

`build_recipe.run` currently assembles gates, containers, horse shop, test
supplies, smithing, prayer, workshop supplies and the New Game menu. It does
**not** assemble the above opening. Registering a New Game destination is not
equivalent to rebuilding the previously staged campaign content.

## Files that must not be copied blindly

- The backup's miller-assets and player-chest PAKs have no unique virtual paths
  absent from the candidate's root Data archives. Their separate filenames alone
  do not establish missing functionality.
- The two reviewed building-blend models already go through `static_assets`
  using `build_recipe.reviewed_blend_mesh`. Compare generated mesh/material
  behavior before reintroducing the older override package.
- Tower external-LOD alignment is now in `static_assets.mesh_bytes`.
  The four Talburg bed source IDs are already selected by `initial_entity`.
  The old Talburg repair expects obsolete mesh numbers and a separate LOD PAK;
  calling it unchanged on the clean build would be incorrect.
- Generated geometry/texture namespaces and shard boundaries changed. The raw
  missing-path total is not a count of missing in-game objects.
- The backup opening codec test overrides the shared native movie registration.
  Keep movie selection separate from restoring the mother conversation.
- Conflicting virtual-path overrides are recorded explicitly. Audit order must
  not be treated as proof of engine mount priority.

## Shader dependency outside either mod

The development installation has loose `Illum.cfx`, `CommonShadowGenPass.cfi`
and `ModificatorVT.cfi` overrides, all different from retail's shader archive.
Neither compared mod contains shader-named archive files. Shader generation and
retail mounting require a separate build stage and same-scene retail validation;
this inventory does not establish that shaders explain every roof/GI defect.

## Setup acceptance requirements

1. Reproduce the opening builders from original game inputs and explicit,
   versioned bindings. The user's backup is evidence, not a distributable asset
   dependency or a substitute for the clean build.
2. Preserve current travel, services and save-protection fixes when merging
   opening graphs. Do not replace the current level/travel PAK wholesale.
3. Verify NPC mission identity, SoulList registration, appearance assets,
   dialogue/audio dependencies and scene entry wiring together.
4. Check initialization, complete/skip movie paths, two-round mother choices,
   gameplay handoff and save/load in retail. Inventory presence is not gameplay
   acceptance or proof of full campaign conversion.
5. Validate the shader package against retail with the same roof/wall scene.
6. Retain the current container, gate, smithing and prayer stages and expose the
   additional stages in setup progress/resume metadata.

## Reproduce the inventory comparison

```powershell
.venv/Scripts/python.exe tools/audit_package_parity.py `
  --reference D:/SteamLibrary/steamapps/common/Backup/kingdomcomegluemapper `
  --candidate D:/SteamLibrary/steamapps/common/KCD2Mod/Mods/kingdomcomegluemapper `
  --output outputs/backup-setup-audit/parity.json
```

The tool reads ZIP directories and NPC mission records, normalizes case and
slashes, and compares virtual paths across shards. CRC/size is an inventory
comparison, not cryptographic verification. It does not change either package.
The focused test covers reshuffling assets into different shards and detecting
conflicting overrides. Setup integration of the omitted opening remains pending.

## Setup call-path and streaming follow-up

The setup-generated installations in both `KCD2Mod/Mods` and
`KingdomComeDeliverance2/Mods` were inspected against the supplied backup.
`setup_mods.worker` calls `desktop_setup.worker`; fresh builds execute
`conversion_plan`, `build_campaign`, the travel bridge, then `build_recipe.run`.
The recipe's nine stages omit the opening/actor builders listed above.
`package_opening` stores original inputs under `GlueMapper/CampaignSource`;
that is not executable opening quest conversion.

Streaming is not wholly omitted. The final conversion stage calls
`prepare_spatial_hlod`, which calls `rebuild_spatial_hlod`. Packaging follows
external `_lod1` through `_lod6` siblings and applies texture-family streaming
generation and checks. Tower LOD alignment is already in `static_assets`.

| Inventory metric | Working backup | Setup development copy | Setup retail copy |
| --- | ---: | ---: | ---: |
| Travel HLOD nodes | 7,226 | 7,226 | 7,226 |
| Travel nonnegative proxy references | 4,102 | 4,102 | 4,102 |
| Root Data external LOD model paths | 5,849 | 6,967 | 6,967 |
| Root Data numbered texture mip paths | 123,880 | 116,693 | 116,693 |

Evidence: `outputs/backup-setup-audit/streaming-summary.json`. These counts do
not establish equivalent proxy contents, switch distances, coverage or runtime
streaming. The lower mip count is not proof of broken families: removed actors,
changed namespaces and different textures also affect it. The parity inventory
contains 318 absent paths attributed to spatial-streaming archives and 1,583
attributed to the world-LOD archive; asset identity must be mapped before calling
these missing scenery. Do not copy those archives wholesale into the new build.

Two completion gaps permit false confidence: `setup_resume.map_receipt` checks
only recipe status and travel-bridge presence, without comparing recipe versions
or required features; `verify_package` checks receipt/layout/hash integrity, not
campaign feature parity. A complete recipe currently means its listed stages
ran, not that the working development mod was reproduced.

The checked-out appearance adapter also still creates one native Coat-based
outfit item from assembled regions (`character_person_appearance`), and the
previously discussed `clothing_material_upgrade`, `equipment_region_resources`
and actor equipment repair modules are absent from this checkout. Those newer
changes cannot be reached by this setup as it stands. Their absence does not
establish whether they were committed elsewhere or only existed locally.

No packages were changed by this audit. Runtime LOD transitions and texture
residency remain unverified.

## Setup integration changes, 18 October 2026

Recipe version 2 now calls the existing opening, actor registration, initial-state,
starting inventory, quest-item, schedule, profile-system, CDF prop, conversation
area, dialogue, combat and facial converters in dependency order. The combat
import includes controller registration and its bootstrap documents, matching
the main campaign compiler's source lookup. Each stage consumes the preceding
package. Completed overlay archives are moved into the assembled package rather
than retained as another copy at every stage.

Install and resume reject older recipes or receipts missing required stages and
validations. Replacing a travel bridge invalidates its old gameplay/menu receipt.
Final checks cover actor souls, opening initialization, combat modules, HLOD
indices and references, generated LOD/mip siblings and packaged texture families.
These checks do not prove equivalent rendered appearance or a playable campaign.

The source-backed run in the supplied setup job's `gameplay-validation` folder
passed all 15 gameplay stages. The assembled result contains 11 selected actors,
6,967 external LOD paths, 122,129 numbered mip paths and 13,536 validated texture
families. The original setup had 116,693 numbered mip paths. Across the backup's
5,849 LOD files, 5,846 have matching vertex/index/subset stream signatures in the
new package, sometimes at different generated paths; three differ. This is
geometry evidence, not equivalence of materials, transforms or LOD transitions.
The remaining path/content differences still require asset-level reconciliation.

The shader stage follows Warhorse's [shader-cache build procedure](https://warhorse.youtrack.cloud/articles/KM-A-82/Building-shader-cache)
in the build workspace. The SDK/game files are read-only inputs. The validation
run compiled 29,914 combinations and generated all four archives. The retail
`Shaders.pak` hash still matches its input hash after compilation.

**Recipe 3 packages shaders inside the mod.** The installer does not replace files
in the game's `Engine`, `Data` or `Bin` directories. **Launch mod** in the setup Library prepares
one linked private launch root inside Mods, with the compiled archives from
`ShaderCache/Engine`. Normal Steam launching retains the original Engine archives.
Warhorse's [installation guide](https://warhorse.youtrack.cloud/articles/KM-A-56/Installing-mods)
identifies shader PAKs as outside normal Data mod mounting; the custom launcher
handles that early Engine loading requirement. A bounded retail startup mounted
all four archives and exited cleanly; see [loading evidence](mod-shader-loading.md).
Same-scene visual validation remains outstanding; this is not shader parity.

The map installer now retains its previous mod only as temporary rollback during
the swap; a successful install does not accumulate full mod backups. No full
gameplay-package installation was performed for this validation. The released setup EXE
has not been rebuilt with these source changes.
