# Asset contract gate

A **developer-only offline checker** for converted render and stream assets. It
reads a mod package's `Data/*.pak` files in place with `zipfile`, compares them
with statistics measured from the retail KCD2 install, and reports contract
violations without launching the game. It has no consumer Setup integration,
is absent from installer payloads, and never extracts, installs or changes a
package, the game or saves. Standard library only.

## Run it

From the repository root (replace the paths):

```powershell
python tools/asset_lab_test.py audit "D:/path/to/package/map" `
  --target "D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2" `
  --native-cache outputs/asset-lab/native-stats.json `
  --output outputs/asset-lab-audit
python tools/asset_lab_test.py inventory "D:/path/to/package/map" --output outputs/asset-lab/inventory.json
python tools/asset_lab_test.py run scenario.json --output outputs/asset-lab-run
```

`audit` writes `audit.json` (full evidence), `audit.html` (searchable, with the
largest-streaming-pieces table) and `junit.xml`. `run` writes `results.json`,
`report.html` and `junit.xml`. `inventory` lists what exists and gives no
verdict. A package argument is a mod folder holding `Data/**/*.pak`, or one `.pak`.

Scanning the retail install takes about a minute (75 paks). `--native-cache`
stores the measured statistics and reuses them while the install's pak
directories are unchanged. A package audit then takes about twenty seconds for a
100 GB package, because only member headers, material XML and mesh chunks are read.
`--check <id>` (repeatable) limits the run; `--max-findings` limits the findings
listed per check, and counts stay exact.

## Checks

| Id | What it checks |
| --- | --- |
| `dds_piece_budget` | The largest DDS stream piece, whether a pak member or the top mip level its header implies, against the largest piece present in retail data. Also a hot-spot table of the 25 largest pieces. |
| `dds_structure` | DDS header sanity, plus base/part completeness: the resident tail size, every streamed `.N` mip present with exactly the mip's size, the split flag, orphan parts. |
| `dds_slot_format` | The texture format per name suffix (`_diff`, `_ddna`, `_spec`...) against what retail uses for that suffix. |
| `cgf_structure` | Chunk table, stream sizes and counts, index range, triangle lists, subset ranges, finite positions for every `.cgf`. |
| `material_contract` | Shader exists in retail data; each `StringGenMask` flag is declared by the shader's `.ext` or observed with it in retail; flags the extension hides; permutations no retail material uses; texture references resolve in the package or retail data. |
| `material_proxy` | A material binding the authored `collision_proxy` texture must use `Nodraw` (red planes, bug 38). Surface types and texture-less `*proxy*` materials that retail renders through `Nodraw` but the package renders through another shader. |
| `hlod_structure` | `terrain/hlods.dat` against `hlods.xml` block sizes, finite values, non-degenerate matrices, ordered boxes, mesh ids inside the level's `terrain.dat` mesh table. |
| `hlod_retail_ranges` | Matrix scale, box extent and duplicate placements against the ranges in retail level data. |

## Statuses

Each check ends in one of:

- `FAIL`: an error finding. Exit code 1.
- `REVIEW`: only review findings. Exit 0 unless `--strict`.
- `UNSUPPORTED`: nothing was found but part of the check could not run (no
  `--target`, a layout that is not modelled). **Never a pass.** Exit 0 unless `--strict`.
- `ERROR`: the check crashed. Exit 1.
- `PASS`: the modelled scope was clean.

The report's `verdict` is `FAIL`, `REVIEW`, `INCOMPLETE` or
`NO_FINDINGS_IN_MODELLED_SCOPE`; it is never a bare pass, `native_runtime_verified`
is always `false`, and the eight **explicit contracts** (the engine's true stream
limit, memory residency, shader compilation, mesh-material binding, cubemap
families, `.cgfm` pairing, terrain/SVO data, rendering correctness) are listed with
status `UNSUPPORTED` in every report.

## Thresholds come from retail data

Nothing is hard-coded as an engine truth. The retail scan measures, at run time:
the largest stream piece (64.0 MiB at the time of writing, labelled
`observed-not-proven`), the formats per texture suffix, shader extension flags,
every flag and permutation retail materials use, which surface types retail
renders only as `Nodraw`, and the scale, extent and duplicate ranges of retail
`hlods.dat`. A rule retail itself breaks in more than 1% of a folder is reported
as `review`, not `error`. The numeric `GenMask` attribute is not judged: retail
disagrees with its own `.ext` files in all but 46 of 26,000 materials, so the
flag names are the contract. The few policy parameters (1% exception rate, 20
retail observations before a suffix is judged, 95% of 20 materials for a proxy
class) are constants at the top of `checks.py` and `native.py`.

## Scenarios

`run` takes JSON files that build a package from generated members and assert on
check results. Synthetic DDS members need no game data:

```json
{
  "name": "4096 RGBA16F top level exceeds retail",
  "members": {"o/old_diff.dds": {"dds": {"width": 4096, "height": 4096,
                                           "format": "R16G16B16A16_FLOAT", "payload": false}}},
  "target": {"contract": {"max_member_bytes": 67108864}},
  "checks": ["dds_piece_budget"],
  "assertions": [{"check": "dds_piece_budget", "status": "FAIL", "codes_include": ["piece_over_retail_max"]}]
}
```

`target.contract` is an explicit retail-statistics contract (any section of the
statistics, see `native.synthetic`); members may also be `text` or `base64`.
A scenario with no assertions is an error.

## What it cannot show

It does not verify rendering, shader compilation, memory pressure, or that the
largest retail piece is the engine's true limit. A piece below the maximum is not
proven safe; a piece above it is a conservative gate. See
[docs/asset-emulator-validation.md](../../docs/asset-emulator-validation.md).
