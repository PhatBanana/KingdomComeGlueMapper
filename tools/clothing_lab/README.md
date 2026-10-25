# Clothing & Body Test — developer tool

This standalone tool inspects the **actual converted assets** in a built or installed mod. It is deliberately separate from consumer Setup and is not bundled into the setup executable. It never installs, upgrades, or edits a game package.

## Open the 3D workbench

From the repository root, using the development environment:

```powershell
.venv/Scripts/python.exe tools/clothing_lab_app.py
```

Steam game locations are detected as starting values. Select a mod folder containing `Data/*.pak`, the KCD2 installation supplying the native rules, and the KCD1 installation for source-soul audits. All three may also be supplied with `--package`, `--target`, and `--source`.

The optional **Developer candidate** field, or `--overlay` on either the viewer or audit CLI, reads a separate repair overlay over that package. The game files are unchanged. This lets the viewer reproduce the same candidate used by the batch checklist.

The viewer supports:

- Male and female character presets, every registered clothing component, and custom layer stacks.
- Individual part visibility, textured/layer-colour/wireframe views, orbit, pan, zoom, front/back/side views, and separated layers.
- Declared body-layer replacement and per-equipment-part vertex hiding, with a side-by-side comparison against unhidden geometry.
- Available mesh LODs; missing requested LODs are errors, never silently replaced with LOD 0.
- A weighted arm-bend stress pose and saved PNG views accompanied by JSON selections, camera state, package signature, and findings.
- Audit results that open their exact component combination in the viewer.

The diffuse preview decodes streamed DDS mip families, including half-float clothing macro textures and their transparency. No game content is distributed with this tool. The locally bundled Three.js renderer is MIT licensed; see `ui/vendor/README.md`.

## Automated checks

Run every converted outfit through the structural and geometry checks:

```powershell
.venv/Scripts/python.exe tools/clothing_lab_test.py `
  --package "D:/path/to/built-or-installed-mod" `
  --target "D:/path/to/KingdomComeDeliverance2" `
  --mode presets --geometry --reports reports/clothing-lab
```

Enumerate **every KCD1 soul record**, resolve body/head/hair/beard references and both `clothing_id` and `clothing2_id` attachments, then validate converted outfits where present:

```powershell
.venv/Scripts/python.exe tools/clothing_lab_test.py `
  --package "D:/path/to/built-or-installed-mod" `
  --target "D:/path/to/KingdomComeDeliverance2" `
  --source "D:/path/to/KingdomComeDeliverance" `
  --mode souls --geometry --strict --reports reports/clothing-lab
```

Source mode always enumerates every shared database soul. Missing conversions are reported as `not_converted`, not passed or omitted. Broken source references produce `source_error`. Empty source bodies may be supplied by a world instance; the audit retains that distinction and does not invent a default body. Source clothing attachments are retained in each report. World-instance overrides, equipment changes driven by quests, and probabilistic inventory selection require a further native test.

The combination modes are:

| Mode | Coverage |
| --- | --- |
| `presets` | All converted character presets, optionally filtered by `--gender Female` or `Male`. |
| `souls` | All shared KCD1 soul rows, with explicit converted/unconverted coverage. |
| `singles` | Every registered garment of the selected body's gender. |
| `pairs` | Every unordered garment pair of that gender, including invalid pairs so slot conflicts are visible. |
| `layers` | Cartesian product of alternatives per declared part/layer signature, including an empty choice for each slot. Cross-slot conflicts are still validated. |

Combination modes require `--body <preset-id>` (shown in report JSON). Enumeration is deterministic. `--limit 250 --offset 0` bounds a batch, and the report supplies `next_offset` and the full `total`. The UI advances its cursor after a batch. A partial batch is never presented as exhaustive coverage. Large Cartesian products can require many batches; use singles and pairs first. The mixed-outfit mask warning is intentional: unrelated components can reuse hiding bit numbers with different meanings.

Reports go to `reports/clothing-lab` by default. Structural failures use `error`; uncertain geometric findings use `review`; `checked` means only the enabled checks found no issue. `enumeration_complete` describes whether all planned cases were visited. `complete` additionally requires every case checked without findings, no catalog errors, and no cancellation. `runtime_verified` always remains false.

The command exits **1** for structural/asset/source errors, **2** if the audit could not run, and **0** otherwise. Add `--strict` to also fail on review findings, missing conversions, or incomplete coverage. This makes it usable from CI without claiming a normal exit code proves native rendering correctness.

## What is simulated

Native role, gender, inherited archetype, equipment-part, hiding groups and body-layer definitions are read from the selected KCD2 `Data/Tables.pak`, with each table hash recorded. Layer comparisons use `body_layer.xml`'s `layer_order`, not the layer IDs: decoration layer 4 is above layers 5–7, while underwear layer 8 is near the body. Checks cover unresolved layers, same-slot conflicts, undefined hiding groups, cross-outfit masks, missing meshes/materials/textures, mesh indices and weights, and source references. Differences from native role templates are review findings because a converted layout can intentionally differ.

The geometry pass tests bounded surface-normal segments against actual garment triangles, filtering ray hits by material-subset UV alpha. A conservative spatial index reduces work without changing the segment result. It reports hidden skin without an opaque cover, clothing beneath visible skin, and higher layers intersecting lower ones. `Nodraw` material slots do not count as opaque coverage. These are **suspected** problems: seams, intended contact, wrinkles, and the bounded normal-ray policy can produce review findings.

This is not a reimplementation of KCD2's closed-source character manager. In particular, equip-slot arbitration, native cloth physics, cloth collision proxies, engine animation, material-atlas microdetail, iris/skin shading, and distant streaming selection are not reproduced. The synthetic stress pose is a viewer aid; automated geometry checks use the exported bind pose. Rendering a selectable combination does not prove the native inventory system can equip it. Shared armor-archetype findings call out that boundary explicitly.

## Whole wardrobe audit and isolated repair candidates

The developer matrix command enumerates every registered garment and every
same-gender garment pair, then checks each existing character preset. It writes
`checklist.csv`, `cases.jsonl`, `confirmed.json`, and `summary.json`. Rows retain
the exact component selection, representative body, native-table result,
geometry result, and an explicitly unverified runtime field.

```powershell
.venv/Scripts/python.exe tools/clothing_lab_matrix.py `
  --package "D:/path/to/built-or-installed-mod" `
  --target "D:/path/to/KingdomComeDeliverance2" `
  --build-layer-candidate reports/clothing-lab/my-layer-candidate `
  --output reports/clothing-lab/my-matrix
```

`--build-layer-candidate` creates a separate overlay for missing native layer
inheritance and unsupported upper-body partitions. It reads both `SkinElement`
and `VClothElement` layer definitions. Merging unsupported partitions preserves
the triangle count and material bindings. Unsupported native roles remain
listed in `repair.json`; they are not assigned invented layer numbers. The
original package is never changed. Pass an existing candidate with `--overlay`.
This candidate does not rebuild skin-hiding masks or repair equipment arbitration.

The matrix computes **exact symbolic counts** over full layer selections using
unary registration checks, part/layer occupancy, and armor-archetype exclusivity.
These counts are not rendered tests. Other engine equipment exclusions,
body-dependent masks, cloth simulation, and full-outfit geometry are outside
that proof. In particular, passing every pair cannot establish that a complete
outfit works.

For a tractable full space, `--full-layers Female` or `--full-layers Male`
enumerates every layer selection and runs bind-pose geometry checks on those
passing the native table checks. Results stream to `cases.jsonl.gz`. The command
refuses spaces above one million cases instead of silently sampling them.
Body, package signature, rule-table hash, all visited cases and geometry-run
counts are recorded. A completed audit can contain failures; command completion
is not an all-clear result.

Long pair runs can be split with `--pair-range START STOP` (zero-based,
exclusive stop). Such reports are marked incomplete. Resume completed rows
with `--resume-from reports/clothing-lab/previous-run`; specify this option
multiple times to combine non-conflicting batches. Output goes to a fresh
directory. Package signatures, rule-table evidence, validator contract version,
and exact selections must match. A truncated final JSONL write can be discarded; corrupt completed rows
are rejected. An unbounded final run with all batch reports fills gaps and
produces a complete checklist.

`clothing_lab.checklist.write_checklist(matrix, full_layers, repairs, output)`
generates a Markdown checklist and a CSV of exact selections passing both table
and geometry checks. It rejects incomplete matrix/full-layer reports and
mismatched candidate signatures. Unclothed baselines are counted separately.
Optional `source_report` and `captures` arguments include a completed soul audit
and developer-renderer examples, provided their candidate and rule hashes match.

## Regression tests

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_clothing_lab*.py" -v
```

Tests use synthetic, redistributable geometry for inheritance, source completeness, DDS reconstruction, transparent sleeves, hidden skin, penetration, native body replacement, Nodraw, collision-safe asset lookup, deterministic combinations, cancellation, and spatial-index equivalence. Optional Playwright/Edge tests exercise real WebGL output, masking, stress poses, capture, filters, and report navigation. No local game paths are required for these tests.
