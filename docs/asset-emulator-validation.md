# Asset contract gate validation

Date: 2026-10-27. Developer tool: [Asset contract gate](../tools/asset_lab/README.md).

This is not native-runtime verification. Every statement below is about what the
tool reads from converted and retail files. Nothing was launched or rendered, and
thresholds are retail observations, not proven engine limits.

## Verified implementation

- [x] Standard-library command line tool; no game, renderer or Setup involvement.
- [x] Reads package paks in place (`zipfile`), including retail archives whose local
  headers store backslashes; never extracts, writes or modifies a pak.
- [x] `inventory` (no verdict), `audit` (all checks) and `run` (JSON scenarios).
- [x] JSON evidence with pak directory fingerprints, searchable HTML and JUnit.
- [x] Retail statistics are measured at run time from the supplied KCD2 install and
  cached by the install's pak-directory fingerprint. No retail number is hard-coded.
- [x] A rule that retail itself breaks in more than 1% of a folder is reported as
  `review`, not `error`.
- [x] Without `--target`, every check that needs retail data is `UNSUPPORTED`, never `PASS`.
- [x] Parts a check cannot model (cubemap families, missing mesh table, `.cgfm` companions)
  keep that check from passing and are listed in the report.
- [x] The eight explicit contracts are reported `UNSUPPORTED` in every report.
- [x] A crashing check is `ERROR` and exits 1; counts stay exact when listed findings are capped.
- [x] Nothing in this tool is imported by Setup or bundled into the installer.

## Rules, with their source

| Check | Rule | Source of the rule |
| --- | --- | --- |
| `dds_piece_budget` | No stream piece (pak member, or the top mip a header implies) larger than the largest retail piece | `793bdfb` (134 MB level crashed the Skalitz gate-guard dialogue; largest retail piece is 64 MB). The maximum is measured from retail, not coded |
| `dds_structure` | Resident tail equals the sum of the unstreamed mip sizes; `.N` is exactly mip `split - N`; the split flag is set; no orphan parts | `texture_streaming.validate_family`, and checked against 26,131 modelled retail families |
| `dds_slot_format` | A format retail never uses for a suffix with at least 20 retail families is a review finding | Retail histogram. The sRGB zone bake (`issues/srgb-ab`) was the same family of fault |
| `cgf_structure` | Chunk table, stream counts and widths, index range, subsets, finite positions | Hand-run `cgfcheck.py` from the GPU-lock triage; retail passes it for all 51,166 `.cgf` files |
| `material_contract` | Shader known; `StringGenMask` flags declared or observed; DependencyHide; permutation seen in retail; textures resolve | Retail `Shaders.pak` `.ext` files and 32,556 retail material leaves. `fix_illum_shader.py`/`fix_instanced_shader.py` exist because of this class |
| `material_proxy` | A `collision_proxy` texture needs `Nodraw`; retail-Nodraw surface types and `*proxy*` names should not be drawn | `ef8f35a` / `designer_collision_repair.hide_proxy` (bug 38). Surface and name classes are derived from retail |
| `hlod_structure` | Block sizes, finite values, non-zero determinant, ordered boxes, mesh ids inside the level's own mesh table | Hand-run `hlodscan.py`; retail hlods have the same structure |
| `hlod_retail_ranges` | Scale, box extent and duplicate counts inside the retail range | `hlodscan.py` hard-coded `1e-3..50`; retail has scales to 100 and boxes to 6,081 m, so the range is measured instead |

### Where retail contradicted the ad hoc checkers

- The old scale limit (50) and the huge-box rule (2,000 m) would flag retail content.
  Retail `hlods.dat` has scales up to 100 and boxes up to 6,081 m, so these are now
  retail-derived ranges and a violation is only a review finding.
- The numeric `GenMask` attribute does not match the `.ext` masks in retail (46 of
  about 26,000 resolvable materials agree), so it is reported but never judged.
- Retail has Illum materials that bind a `collision_proxy` texture (26 versus 2
  Nodraw), so that rule reflects the bug 38 evidence in the mod rather than a retail invariant.
- 155 engine-asset DDS families break the resident-size rule in retail, all under
  `engineassets/`, so a mod finding in such a folder is `review`.
- A `hlods.dat` must be checked against the `terrain.dat` mesh table of its own level;
  the package also holds a retail-style `Levels/trosecko/level.pak`.

## Tests run

| Check | Result | Meaning |
| --- | --- | --- |
| `tests/test_asset_lab.py` | 38 passed | Synthetic-blob contracts: DDS family rules and damage cases, header faults, the pre- and post-`793bdfb` float texture shapes, member-size boundary, slot-format judging, CGF faults, ext parsing, material and proxy rules, HLOD faults and ranges, mesh-table reads, pak head/tail reads, status semantics, retail statistics measured from a synthetic install and cached by fingerprint, end-to-end audit exit codes and reports, scenarios |
| Full `tests` suite | see below | Regression run on the worktree |

Tests use generated DDS, CGF, HLOD and material blobs and a generated miniature
retail install. No game data is in version control. The synthetic float-texture
regression builds the header of the pre-fix writer output (4096x4096 RGBA16F, one
170.7 MB file) and of the post-fix output (2048x2048, 42.7 MB) and checks that the
first fails and the second passes against a 64 MiB contract.

## Audit of the 10-22 package

Run on `jobs/20261022-160453-a9a40cd-main-fresh/package/map` (149 paks, 40,209
texture families, 22,826 `.cgf`, 19,361 material leaves, two `hlods.dat` files)
against retail KCD2 at `D:/SteamLibrary/.../KingdomComeDeliverance2` (75 paks,
304,834 texture members, 51,166 `.cgf`, 32,556 material leaves, 3 retail level hlods).

| Check | Status | Result |
| --- | --- | --- |
| `dds_piece_budget` | PASS | Largest package piece 44,739,388 B (42.67 MiB, the unsplit 2048x2048 RGBA16F chain) against retail 67,108,864 B (64.0 MiB, `objects/intermediates/creektool/grass_merged_tweaked_diff.dds.8`). 1,100 pieces are at least half the retail maximum; none reaches three quarters |
| `dds_structure` | REVIEW | 18,570 families modelled and clean apart from 167 families with an unused streamed part (`.N` beyond the header mip count); 21,639 cubemap families are not modelled |
| `dds_slot_format` | REVIEW | 6 groups: `*_diff` and `*_spec` as RGBA16F (757 each, the float clothing bakes), `*_bgs` as RAW32 (1,097), `*_mask` as RAW8 (124), 6 `*_spec` RAW8, 1 `*_ddn` DXT1 |
| `cgf_structure` | PASS | 22,826 files, 64,471 meshes, 51.3 M vertices; no fault. 0 `.cgfm` companions |
| `material_contract` | FAIL | 1 unknown shader, 3 unknown generation flags, 3 groups of hidden flags, 142 permutations used by no retail material; 0 unresolved textures |
| `material_proxy` | REVIEW | 0 `collision_proxy` textures drawn; 2,840 texture-less `*proxy*` materials and 294 proxy-class surface materials use Illum |
| `hlod_structure` | REVIEW | kcd1_travel: 171,347 brushes, 0 faults, mesh ids below the 10,455-entry table; the retail-style trosecko hlods has 452 brushes far outside their node (retail has the same) and its mesh table is not in the package |
| `hlod_retail_ranges` | PASS | Scales 0.026 to 21.7, extent to 4,095 m, at most 3 duplicates; all inside the retail range |

Verdict `FAIL`: the failure is the material findings below, not a size or
structure rule. Details: `D:/KCD/Builds/glue/issues/emulators/asset-findings.md`.

## Remaining boundaries

- [ ] The true engine stream and page limits. 64 MiB is only the largest piece retail contains.
- [ ] Aggregate memory, GPU residency, and how many valid pieces load together.
- [ ] Shader compilation and ShaderCache permutation presence.
- [ ] Which mesh draws which material; proxy materials are judged from materials alone.
- [ ] Cubemap, texture-array and unknown-format DDS family structure.
- [ ] Split `.cgf`/`.cgfm` pairing.
- [ ] `terrain.dat` sectors, vegetation tables, SVO and navigation data.
- [ ] Rendering correctness: colour space, mip content, normal-map encoding.

A production guard remains a separate, small change: a package-wide piece budget in
`setup_pak_limits.validate`, as `npc_effects.MAX_FLOAT_SIZE` guards one writer today.
