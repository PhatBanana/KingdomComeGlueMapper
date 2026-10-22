# Stale section repair

Setup resume checks LOD validation separately from the package's file receipt.
A valid receipt proves the installed files have not changed since installation;
it does not prove that an older builder refreshed every internal marker.

When LOD validation is stale, setup searches the selected build workspace for a
saved section whose HLOD SHA-256 matches the previous marker. Resource tables
and the saved vegetation-group fingerprint must also match. It can then restore
only the imported LOD ratio bytes and group ratios, preserving current geometry
and native resources. The legacy forge-loft furniture edits are replayed through
their registered implementation before comparison. Every other HLOD byte must
match; arbitrary geometry changes are not accepted as a harmless stale marker.

For the reported loft package, the wheelbarrow/basket translations and removal
of the decorative ladder explain the entire mismatch. All existing LOD values
are already correct. Repair changes only `terrain/gluemapper_lod_ratios.json`
inside `level.pak`, then updates that archive's receipt hash. It never runs the
nonlinear LOD conversion a second time. New loft builds maintain this marker
when applying their registered geometry edits.

Repair runs in the same private-copy transaction as other setup updates. A
failure or cancellation retains the previous package and receipt. Unrelated
file hashes are retained and verified, not regenerated to hide unknown changes.
Repeating a completed repair is a no-op. Current-recipe packages skip the full
gameplay finalizer after repair; older recipes still perform their required
gameplay upgrades. Direct finalizer callers can pass `repair_roots=(workspace,)`
to resolve a stale section before running those upgrades.

Keep the original build/cache available. If no saved section matches the old
marker, or the encoding version or geometry is unsupported, repair stops with
an explicit error instead of guessing the encoding or rebuilding the whole map.
This repair currently covers LOD validation; it is not a blanket bypass for
other failed section validators. Tests cover marker-only repair, damaged ratio
bytes and group ratios, invalid evidence, native-data protection, cancellation,
repeat runs, and setup's section-only resume path. Runtime gameplay is a separate
validation boundary.
