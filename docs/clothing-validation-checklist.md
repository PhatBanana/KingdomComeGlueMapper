# Clothing combination validation checklist

**Superseded by native selection evidence (25 October 2026).** KCD2 draws
one clothing mesh per region, while the earlier viewer drew every selected
layer. The old checked combinations below do not establish visible coverage.
Contract 4 now models native selection, material culling and render/internal
colour-buffer parity. See [the native discrepancy report](clothing-native-rendering.md).

This is a developer audit of the **converted package**, not certification by the KCD2 runtime. A checked combination below has exact native role/gender/layer matches, no reported slot/archetype conflicts, and no findings from the enabled bind-pose geometry checks. It was not tested in native animation or cloth physics.

The subsequent [source fitting and composition correction](clothing-fitting-conversion.md)
and native equipment/body coverage follow-up have their own candidate, render
evidence and remaining review findings. The counts
and confirmed CSV below continue to describe the original signature, not that
new candidate.

This is historical evidence from an older validator contract. The current
version 3 checked exclusive native subpart/layer reservations in symbolic
counts. Its historical registration-only rerun covered all 407 garments, 48,865
pairs and 61 presets; see the linked follow-up for its separate signature and
15-case geometry check. The confirmed CSV below has not been recertified under
the new contract and must not be used as current native-equipment approval.

Package signature: `7c0360e1d72ae865526a2db1f32993ca560ff745eb65730d099205254a30fdef`.
Native rule-table hashes:

- `Libs/Tables/Character/CharacterComponent.xml`: `49c6cf8a544927a330c23880d3b392cf327931a46ed524bb8cb3c3c1be81261e`.
- `Libs/Tables/Character/ClothingHidingGroup.xml`: `6bc7b44981980758ee4afec44f69eea905641ce5b3188aa558846c4ac2483f28`.
- `Libs/Tables/item/body_layer.xml`: `8c1867c25608baf73e01316669c33be177e777c0c41fb548c2bb860aeb8ea011`.

## Completed checks

- [x] Enumerated all 407 registered garments and all 48,865 same-gender pairs.
- [x] Inspected every existing converted character preset on its own body.
- [x] Enumerated all 284,284 female layer selections on the named representative body.
- [x] Ran geometry on 1,023 table-compatible full female selections.
- [x] Counted the male full-layer registration space exactly using compressed constraint states.
- [x] Fixed missing native VCloth layer inheritance and unsupported upper-body region partitions; retested the isolated candidate.
- [x] Added regression checks requiring converted UV alpha even when a source opacity cache exists.
- [x] Excluded unused partition vertices from geometry findings and distinguished native masks from private outfit masks.
- [x] Applied native `body_layer.xml` ordering instead of comparing layer IDs numerically; reran the matrix.
- [ ] Rebuild existing garment/body hiding buffers using the opacity fix. The layer candidate does not contain that rebuild.
- [ ] Resolve the 3 item tables without a supported native region repair.
- [ ] Resolve the remaining dress/archetype, mask compatibility, and geometric review findings.
- [ ] Test all male full-outfit geometry, all body variants, all LODs and animated poses.
- [ ] Verify clothing selection, rendering and cloth physics inside KCD2.

## Matrix results

| Gender | Garments | Pairs enumerated | Pairs receiving geometry checks | NPC presets |
| --- | ---: | ---: | ---: | ---: |
| Female | 116 | 6,670 | 510 | 20 |
| Male | 291 | 42,195 | 26,622 | 41 |

Pairs failing the registration policy are recorded as rejected or needing review; they are not rendered as valid outfits. Singles and pairs use one explicitly recorded representative body per gender. Presets use their own bodies.

## Confirmed by the enabled checks

**363 distinct clothed selections** passed both the table contract and the enabled geometry diagnostics. The separate 1 unclothed baseline record(s) are excluded from this count.
The complete checkbox-equivalent list, with exact selections, is [clothing-validation-checklist-confirmed.csv](clothing-validation-checklist-confirmed.csv). A role name alone is not a confirmation: different items using that role can have different geometry and masks.

| Checked | Gender | Body / source actor | Clothing roles | Exact case |
| --- | --- | --- | --- | --- |
| [x] | Female | ska_woman27 | F_SimpleDress, F_Veil, F_Shoes | `preset:gm_person_40697da2289e5f8044c1e6f24f7ae3b7_root` |
| [x] | Female | ska_jana | F_SimpleDress, F_Shoes, F_Veil | `preset:gm_person_4309fdd2183182c6897a9ba2197eb69e_root` |
| [x] | Female | ska_woman9 | F_SimpleDress, F_Shoes | `preset:gm_person_485b33cd43e9fd2d5dde5183ab2079b8_root` |
| [x] | Female | ska_tonka | F_SimpleDress, F_Veil, F_Shoes | `preset:gm_person_48c0a9dc9fbfbc47bf7f517dfbce198b_root` |
| [x] | Female | ska_beranMrs | F_Veil, F_Shoes, F_SimpleDress | `preset:gm_person_4a83509363e4b5690822454234d1b89e_root` |
| [x] | Female | gluemapper_theresa | F_Shoes | `single:gluemapper_theresa_part3` |
| [x] | Female | gluemapper_theresa | F_Veil | `single:gm_person_423f39d836d15d7adc9125fb39052997_part3` |
| [x] | Female | gluemapper_theresa | F_Veil | `single:gm_person_45b59446f55de3ed2588226fed8d2aab_part3` |
| [x] | Female | gluemapper_theresa | F_Veil | `single:gm_person_48c0a9dc9fbfbc47bf7f517dfbce198b_part4` |
| [x] | Female | gluemapper_theresa | F_Veil | `single:gm_person_4a83509363e4b5690822454234d1b89e_part3` |
| [x] | Female | gluemapper_theresa | F_Veil | `single:worlditems_cloth_44641203_1426_4db8_90f7_8638e3e9fbba` |
| [x] | Female | gluemapper_theresa | F_Veil | `single:worlditems_cloth_48cb2661_3c3a_99bc_b09b_3b6a79c9f5a9` |
| [x] | Male | gluemapper_rattay | Cap, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000024+worlditems_cloth_4038ccc9_976c_efd3_014c_0cc80a6695b5` |
| [x] | Male | gluemapper_rattay | Cap, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000024+worlditems_cloth_40af7f97_143c_95a5_5e0b_01efbfac29b6` |
| [x] | Male | gluemapper_rattay | Cap, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000024+worlditems_cloth_417fd467_dbb9_0016_6e6d_89ce0b507fbe` |
| [x] | Male | gluemapper_rattay | Cap, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000024+worlditems_cloth_42f8d0ed_63d9_a104_cf0a_de415f6aa8b3` |
| [x] | Male | gluemapper_rattay | Cap, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000024+worlditems_cloth_4573af03_8382_d87c_93aa_5dbb6fc79698` |
| [x] | Male | gluemapper_rattay | Cap, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000024+worlditems_cloth_491e4460_878a_20aa_3d69_5a9d88d75795` |
| [x] | Male | gluemapper_rattay | Cap, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000024+worlditems_cloth_4a9c8bc3_759d_f9a4_87f8_77cd31481e9b` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000025+worlditems_cloth_4038ccc9_976c_efd3_014c_0cc80a6695b5` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000025+worlditems_cloth_40af7f97_143c_95a5_5e0b_01efbfac29b6` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000025+worlditems_cloth_417fd467_dbb9_0016_6e6d_89ce0b507fbe` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000025+worlditems_cloth_42f8d0ed_63d9_a104_cf0a_de415f6aa8b3` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000025+worlditems_cloth_4573af03_8382_d87c_93aa_5dbb6fc79698` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000025+worlditems_cloth_491e4460_878a_20aa_3d69_5a9d88d75795` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_00000000_0000_0000_0000_000000000025+worlditems_cloth_4a9c8bc3_759d_f9a4_87f8_77cd31481e9b` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_09d799a2_2253_4a46_89cc_142affcb1ede+worlditems_cloth_4038ccc9_976c_efd3_014c_0cc80a6695b5` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_09d799a2_2253_4a46_89cc_142affcb1ede+worlditems_cloth_40af7f97_143c_95a5_5e0b_01efbfac29b6` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_09d799a2_2253_4a46_89cc_142affcb1ede+worlditems_cloth_417fd467_dbb9_0016_6e6d_89ce0b507fbe` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_09d799a2_2253_4a46_89cc_142affcb1ede+worlditems_cloth_42f8d0ed_63d9_a104_cf0a_de415f6aa8b3` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_09d799a2_2253_4a46_89cc_142affcb1ede+worlditems_cloth_4573af03_8382_d87c_93aa_5dbb6fc79698` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_09d799a2_2253_4a46_89cc_142affcb1ede+worlditems_cloth_491e4460_878a_20aa_3d69_5a9d88d75795` |
| [x] | Male | gluemapper_rattay | KettleHat, ArmPlate | `pair:worlditems_cloth_09d799a2_2253_4a46_89cc_142affcb1ede+worlditems_cloth_4a9c8bc3_759d_f9a4_87f8_77cd31481e9b` |
| [x] | Male | gluemapper_rattay | ArmPlate, BascinetOpen | `pair:worlditems_cloth_4038ccc9_976c_efd3_014c_0cc80a6695b5+worlditems_cloth_40bafc6f_ea0f_d9d2_57f7_0da666d60083` |
| [x] | Male | gluemapper_rattay | ArmPlate, KettleHat | `pair:worlditems_cloth_4038ccc9_976c_efd3_014c_0cc80a6695b5+worlditems_cloth_40d19389_b8e6_8f54_cf74_f3715b0cea8c` |
| [x] | Male | gluemapper_rattay | ArmPlate, Cap | `pair:worlditems_cloth_4038ccc9_976c_efd3_014c_0cc80a6695b5+worlditems_cloth_40dac35d_5df7_e4b3_ba7c_ca2c9c706f93` |
| [x] | Male | gluemapper_rattay | ArmPlate, BascinetVisor | `pair:worlditems_cloth_4038ccc9_976c_efd3_014c_0cc80a6695b5+worlditems_cloth_413a23a3_3d34_de11_abeb_2dfc9af846a9` |
| [x] | Male | gluemapper_rattay | ArmPlate, Cap | `pair:worlditems_cloth_4038ccc9_976c_efd3_014c_0cc80a6695b5+worlditems_cloth_4143839b_d46c_0c4f_6bb5_764c742bdba9` |
| [x] | Male | gluemapper_rattay | ArmPlate, KettleHat | `pair:worlditems_cloth_4038ccc9_976c_efd3_014c_0cc80a6695b5+worlditems_cloth_415cb852_5910_50cf_9802_4375257dd3b5` |
| [x] | Male | gluemapper_rattay | ArmPlate, Cap | `pair:worlditems_cloth_4038ccc9_976c_efd3_014c_0cc80a6695b5+worlditems_cloth_41be015c_6d05_d058_f5d8_62c17ac8c3a2` |

The table shows 40 cases; the CSV contains all 363.

## Exact full-space counts — registration only

These are exact algebraic counts of the listed constraints, not individually rendered outfits. They exclude geometry, body-dependent private masks, native equip arbitration, and any additional engine exclusions. Passing every pair does not prove a complete outfit works.

| Gender | Full Cartesian space | Pass listed registration constraints |
| --- | ---: | ---: |
| Female | 284,284 | 21,868 |
| Male | 11,322,351,653,437,440,000 | 771,978,521,825,280 |

## Repaired registrations

The isolated overlay repairs **44 components**. The installed package is unchanged. Region joins retain all source triangles and material bindings. The converter now applies the same native-layer policy to future builds.

| Component | Native role | Correction |
| --- | --- | --- |
| `worlditems_cloth_00000000_0000_0000_0000_000000000020` | GambesonLong | waist inherits layer 5 |
| `worlditems_cloth_400b4bb0_a1d0_9bec_1b90_5b2bfcb9e9af` | GambesonLong | waist inherits layer 5 |
| `worlditems_cloth_401ad7c8_4a34_0ef9_7117_9e4ce2044e9a` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |
| `worlditems_cloth_412e44fb_0e4c_0e80_b763_0b6493b13fa0` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |
| `worlditems_cloth_414d7408_c2b3_e891_a652_88d1d9c9da8a` | Waffenrock | Recombined arms, waist into torso; 2648 triangles retained |
| `worlditems_cloth_416efb7c_8e5f_3518_89d2_5b9af35ad7b6` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |
| `worlditems_cloth_41fe34ab_46ea_6c34_da68_f1e66f46fb89` | Cuirass | Recombined waist into torso; 7087 triangles retained |
| `worlditems_cloth_422c924d_eed3_9183_f47f_3b62e6b66ea1` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |
| `worlditems_cloth_4277266f_8712_e8bf_8020_7a8b857f5795` | Waffenrock | Recombined arms, waist into torso; 2648 triangles retained |
| `worlditems_cloth_42960eae_d460_e350_5a80_e1689724269d` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |
| `worlditems_cloth_42a18a5a_b2d0_07eb_14c7_ed9f665ca695` | Waffenrock | Recombined arms, waist into torso; 2648 triangles retained |
| `worlditems_cloth_42fc11fb_bf16_152b_c94b_6493adf24686` | Waffenrock | Recombined arms, waist into torso; 2648 triangles retained |
| `worlditems_cloth_4327d9fc_2c1b_2d1b_e60d_63a202c133b9` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |
| `worlditems_cloth_4350ad68_f244_477a_f4af_f8e0019041ad` | Waffenrock | Recombined arms, waist into torso; 2648 triangles retained |
| `worlditems_cloth_440074cf_4d3d_5d80_2944_f49d91d642a1` | Cuirass | Recombined waist into torso; 12809 triangles retained |
| `worlditems_cloth_44342f54_fc71_f435_c68a_d6382d1e0ca2` | Cuirass | Recombined waist into torso; 6082 triangles retained |
| `worlditems_cloth_4439d7db_c440_9576_cd07_2d531afa7bb6` | Cuirass | Recombined waist into torso; 7087 triangles retained |
| `worlditems_cloth_4526668a_3a05_6aa2_f9f9_280de886c48f` | Waffenrock | Recombined arms, waist into torso; 2648 triangles retained |
| `worlditems_cloth_45bdd999_3050_c096_8e2a_56dec9e231a5` | Waffenrock | Recombined arms, waist into torso; 2648 triangles retained |
| `worlditems_cloth_45e28f40_6882_6a01_e281_25733f761f9f` | Waffenrock | Recombined arms, waist into torso; 9624 triangles retained |
| `worlditems_cloth_4621b468_38bc_79ed_f0ce_9219543d7fa9` | Waffenrock | Recombined arms, waist into torso; 9624 triangles retained |
| `worlditems_cloth_463645bd_4e9e_ed5d_e63d_d373f28b5eb2` | Waffenrock | Recombined arms, waist into torso; 2648 triangles retained |
| `worlditems_cloth_475aeca0_ddcb_ca9e_069d_e33b01b6edb8` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |
| `worlditems_cloth_47af49ef_bdd7_2e07_2fc8_d53b6b4faea9` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |
| `worlditems_cloth_496cad42_be32_9556_9dc2_137b629c1191` | Waffenrock | Recombined arms, waist into torso; 2648 triangles retained |
| `worlditems_cloth_49d89f9b_31a9_1b5d_a389_7e7545fa4590` | Waffenrock | Recombined arms, waist into torso; 2012 triangles retained |
| `worlditems_cloth_4a7fff4d_37d9_74a6_7d7a_8e237b32069b` | Waffenrock | Recombined arms, waist into torso; 2648 triangles retained |
| `worlditems_cloth_4ab8c97d_6977_4b6c_4d66_86b471549483` | Cuirass | Recombined waist into torso; 4607 triangles retained |
| `worlditems_cloth_4afcb01c_c7a9_7310_68e3_22943098f8a3` | Waffenrock | Recombined arms, waist into torso; 2648 triangles retained |
| `worlditems_cloth_4c249176_daf9_7b59_507d_90b3d6ec59a2` | Waffenrock | Recombined arms, waist into torso; 2648 triangles retained |
| `worlditems_cloth_4c8f4d4b_72d3_c337_ed0c_41225e7b2382` | Cuirass | Recombined waist into torso; 12809 triangles retained |
| `worlditems_cloth_4c98b6b4_9645_27f9_8b50_4bd4b63a09b4` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |
| `worlditems_cloth_4d3eb06c_581c_72a2_acf5_07c56cbb47b4` | Cuirass | Recombined waist into torso; 12809 triangles retained |
| `worlditems_cloth_4d879617_b6f3_24c3_1dc5_dfc50ac4d09d` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |
| `worlditems_cloth_4d8ce20d_2002_b4c5_596c_e3302a96299d` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |
| `worlditems_cloth_4db0679c_af60_b7df_e7af_58886f6354a6` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |
| `worlditems_cloth_4e1c3929_0e6d_e0c2_61e0_363f8e7ac289` | Waffenrock | Recombined arms, waist into torso; 9624 triangles retained |
| `worlditems_cloth_4e992c69_fcd2_57a1_5be3_5c2e03fcc0ba` | Cuirass | Recombined waist into torso; 7087 triangles retained |
| `worlditems_cloth_4f210bf5_0eab_7d8f_1c3b_fbb4615a1dae` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |
| `worlditems_cloth_4f4e5326_5e10_5a3e_bf80_e38e381c19a2` | Waffenrock | Recombined arms, waist into torso; 9624 triangles retained |
| `worlditems_cloth_4f8dc7eb_f1c4_f01a_dc3e_170d4288cd9d` | Cuirass | Recombined waist into torso; 5636 triangles retained |
| `worlditems_cloth_4fa636da_dda1_7b97_36fb_537cb4800e9d` | Waffenrock | Recombined arms, waist into torso; 2648 triangles retained |
| `worlditems_cloth_4fc17391_b9ec_aedc_997e_0e0b9e094898` | Waffenrock | Recombined arms, waist into torso; 9624 triangles retained |
| `worlditems_cloth_88e3f8f2_e820_40e5_9fc5_82024ded0c5e` | MailShort | Recombined arms, waist into torso; 2312 triangles retained |

Unresolved source item tables:

- `libs/tables/character/charactercomponent__worlditems_cloth_4156d594_be4a_71c2_8ede_4d517ac668a5.xml`: Unresolved native region repair: worlditems_cloth_4156d594_be4a_71c2_8ede_4d517ac668a5
- `libs/tables/character/charactercomponent__worlditems_cloth_44135951_cf1c_f2fd_15f0_0f0ea223a584.xml`: Unresolved native region repair: worlditems_cloth_44135951_cf1c_f2fd_15f0_0f0ea223a584
- `libs/tables/character/charactercomponent__worlditems_cloth_4d72afbc_18ac_6ef6_50f1_b9e1f6774b82.xml`: Unresolved native region repair: worlditems_cloth_4d72afbc_18ac_6ef6_50f1_b9e1f6774b82

## KCD1 source coverage

Enumerated 5,025 shared KCD1 soul records. Only records with an existing converted character preset can receive converted-geometry checks.

| Result | Source records |
| --- | ---: |
| checked | 5 |
| not_converted | 4,969 |
| review | 51 |

Source evidence: `reports/clothing-lab/souls-v2-20261025/20261025-081236-634928.json`. Unconverted records are not confirmed clothing combinations.

## Developer renderer examples

These actual packaged outfits were opened in the standalone WebGL workbench and captured from front, back, and side, plus the masked/unmasked comparison. Captures are visual evidence for these cases only; they do not certify every matrix row or native KCD2 rendering.

- `ska_woman27`: 6 meshes loaded · 0 asset errors · checked. Captures: `reports/clothing-lab/rendered-20261025/ska_woman27-front.png`.
- `ska_blanka`: 6 meshes loaded · 0 asset errors · review. Captures: `reports/clothing-lab/rendered-20261025/ska_blanka-front.png`.
- `gluemapper_rattay`: 13 meshes loaded · 0 asset errors · review. Captures: `reports/clothing-lab/rendered-20261025/gluemapper_rattay-front.png`.

## Evidence and reproduction

- Detailed pair/preset cases: `reports/clothing-lab/order-v2-final-20261025/cases.jsonl`.
- Complete matrix checklist: `reports/clothing-lab/order-v2-final-20261025/checklist.csv`.
- Full female case stream: `reports/clothing-lab/order-v2-female-full-20261025/cases.jsonl.gz`.
- Isolated candidate provenance: `reports/clothing-lab/layer-candidate-20261025/repair.json`.
- Developer commands and limits: [Clothing & Body Test](../tools/clothing_lab/README.md).

The raw reports and candidate meshes stay in ignored local `reports/`; only this checklist, its confirmed-selection CSV, and source code are suitable for the repository. No copyrighted game assets are included in this report.
