# Talburg bed and tower repair

The reported bedroom is near (2336.42, 2785.89, 105.21). Its source bed
123716 was excluded because its quest-controlled layer does not end in state0.
The separately imported bedding remained visible without its frame or sleep
contract. Restore the four reviewed beds (123712, 123714, 123716, 123718) from
that exact layer in both visual extraction and bed conversion. Other quest
layers remain excluded; this is an explicit imported-world furnishing choice,
not a claim that every source quest layer is initially enabled.

The investigated tower candidate is mesh1770 in the installed building namespace. Its three
external LOD roots carry vertical translations of roughly 42, 89 and 131 metres,
although their local geometry bounds already fit the base mesh. The converter
now aligns a detached LOD only when the root name/orientation match, its geometry
fits the base bounds and the displacement exceeds the whole mesh extent. Vertex
streams, materials, physics and local mesh bounds are preserved.

`tools/build_talburg_repair.py` stages these repairs from the reviewed installed
baseline, verifies unrelated archive entries and records input/output hashes in
`repair.json`. The staged package is under `outputs/TalburgRepair01/package`.
It contains a replacement level, mounted AI tables, the repaired LOD archive and
a new furniture asset archive. Installation requires the game to be closed.

Validation: all 1040 local unit tests pass. The staged level retains every
existing entity and adds four visual models plus four linked native bed/trigger
pairs. Package checks preserve 1007 unrelated level entries, 3378 travel entries
and 5706 LOD entries. Other beds may have separate clearance or
quest-state limitations; this repair does not establish that every bed works.

## Runtime result: floating tower still unresolved

The four packages were installed and hash-verified, and the game was restarted.
Live entity queries confirmed `glue_item_123716`, `gm_world_bed_123716_bed` and
`gm_world_bed_123716_trigger` exist. Successful sleep entry/exit and visual bed
acceptance have not yet been confirmed.

The user's subsequent courtyard screenshot on 16 October 2026 still shows the
floating tower. Therefore the external LOD translation correction did not solve
the reported visual defect. Keep this issue open; do not describe the tower as
fixed or the inferred source as conclusively identified. Next investigation
must identify the rendered floating instance and its actual loaded geometry,
including other mesh copies, embedded nodes and authored placement transforms.
The installed package and passing converter tests establish only the changes
described above, not a successful tower repair.
