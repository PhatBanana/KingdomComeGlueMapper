# Native KCD2 and converted-world streaming comparison

Inspected the installed archives on 15 October 2026. The current forest GI
lighting is restored and remains installed. This audit makes no lighting changes.

## Spatial groups and distant representations

Compiled `terrain/hlods.xml` contains:

| Level | Nodes | Maximum depth (root = 0) | Nodes with proxy references |
| --- | ---: | ---: | ---: |
| Native trosecko | 5,087 | 6 | 4,876 |
| Native kutnohorsko | 6,915 | 7 | 6,089 |
| Converted kcd1_travel | 12,885 | 2 | 0 |

Native levels include Cluster, Layer, Prefab, Interior and Vegetation node
types. The converted level includes only Cluster and Vegetation. Native
levels also ship separate HLOD geometry archives. Per-model external LODs
are not replacements for those group proxies. This is a concrete implementation
gap relevant to distant-object transitions, but not proof of the cause of a
particular texture-residency delay or the intermittent merged-mesh state error.

Only the root has a Hash attribute in both sampled native trees. Therefore
missing per-child Hash attributes are not, by themselves, evidence of a bug.

## Texture packaging

Sampled native texture families place small base DDS files in
`IPL_Textures-part0.pak`, with numbered mip payloads in `Textures-part*.pak`.
For example, `textures/ceramic/ceramic_diff.dds` has a 828-byte base file;
the matching normal base is 1,508 bytes. Native archive separation is observed
packaging, not evidence that mod archives require those exact filenames.

The imported dependency resolver follows DDS siblings, including split alpha
payloads, and the vegetation builder preserves source texture-family members.
However, enumerating existing members does not validate a complete mip chain.
The mod archive scan found two families with numbered levels 1-7 and 9 but no 8:

- `glueveg/setup_vegetation/t11_plants_grass_merged_diff.dds`
- `glueveg/setup_vegetation/t12_plants_grass_merged_ddna.dds`

The repair investigation found that the vegetation and terrain importers omitted
`Data/patch` archives. Applying those after base/HD archives supplies coherent
replacement families. The rebuilt grass families use the patched source data
throughout; copying just a similarly named mip from a different namespace was
rejected because its overlapping pixels differed. This corrects the preliminary
base/HD-only diagnosis that the source installation might itself be incomplete.

Across 52 mod Data archives, an index of DDS paths found 86 base textures larger
than 1 MiB without numbered mip siblings, totalling 1,147,503,232 bytes on disk.
These include generated character textures and building blends. This is not
resident VRAM usage, nor proof they all load together. Several bases contain
embedded mip chains. Their streaming layout and headers should be upgraded
and measured against native texture families; reducing resolution is not the
only possible remedy.

## Implemented conversion and installed test build

- `texture_streaming.py` validates base, numbered and separate-alpha payload sizes,
  rejects gaps and duplicate assets, and writes native streamed DDS layouts.
  Generated RGBA masks receive missing lower mips with independent channel
  filtering. Existing top-level pixels are preserved. BC, RGBA8 and RGBA16F
  samples match the installed KCD2 resource compiler byte-for-byte.
- `campaign_package.write_asset_shards` uses the shared streaming/validation path.
  Vegetation and terrain imports now apply patch archive precedence and validate
  each imported family before copying it.
- `rebuild_spatial_hlod.py` reads the source's authored far-object definitions,
  imports their meshes/materials/textures, builds bounded spatial groups, and
  writes proxy indices into **parent** render-record blocks, as native KCD2 does.
  Source layer identity is recovered before assigning near objects to a group.
- `prepare_spatial_hlod.py` is the final spatial stage in desktop conversion,
  before campaign packaging. Native RC is optional: the tested writer supports
  the generated formats directly, without requiring an editor install.

Texture installation evidence is in `outputs/StreamingUpgrade/Installed01/installation.json`;
the corrected hierarchy is recorded in `outputs/StreamingUpgrade/Topology04/installation.json`:
48 generated textures have external mip slices, two grass families were repaired,
4,102 source proxies were imported, and all 1,650,392 original near records were
preserved byte-for-byte. The corrected hierarchy has 7,226 nodes. Thirty-six inactive source
state groups were excluded. Seventeen overlapping brush groups remain near-only
and are explicitly listed in `Spatial03/report.json`; their membership has not
been guessed. Two imported cubemaps remain outside this 2D DDS repair path.

The 48 textures previously held 1,091,923,840 bytes in their base files. Their new
base files total 107,552 bytes, with larger mip levels in external slices. This is
an archive-layout comparison, **not measured VRAM savings or an FPS claim**.

The installer rewrites every existing copy of a replaced texture and adds new
mip/proxy dependencies, avoiding reliance on mod archive ordering. It preserves
all unrelated level entries and hashes the existing SVO packages before/after.
Hardlink backups and a rollback journal are retained. The lighting bake is unchanged.

Runtime testing is required before claiming that the user's intermittent pop-in
is fixed. A successful load or absence of streaming log errors alone does not
establish visual transition quality. Test slow approach, departure and return to
the affected buildings and forest; inspect mip clarity separately from geometry
switches. Original inventories are in `outputs/StreamingAudit/2026-10-15/`.

## Runtime correction and acceptance

The first generic binary hierarchy failed the in-game test: flat tree proxies
appeared close to the camera and houses failed to appear. Its log contained
210 parent/child HLOD switching violations. Vegetation was incorrectly nested
inside arbitrary Cluster tiers. The corrected converter separates the Main
layer from the native three-tier vegetation grid (1024m, 256m, 64m groups).
This follows the tier-indexed vegetation switching distances in native KCD2.
The corrected run has zero parent/child switching violations.

The user confirmed that the tree/house rendering regression was fixed after the
corrected topology was installed. This is visual acceptance of that regression,
not proof that every original pop-in symptom is resolved. The corrected run still
logged startup HLOD mesh-readiness timeouts. Seventeen overlapping authored brush
groups remain near-only; upper vegetation tiers have no synthesized coarser proxy.
Those limits remain open. Lighting and mip repairs were retained throughout.
