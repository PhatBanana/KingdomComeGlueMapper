# Water layer selection

The initial-world import flattened all source water records onto shared layer 0,
including explicit later quest-state water. Skalitz's sv_state1 marsh volume
(bounds X 787.701..820.117, Y 3485.041..3509.847) consequently appeared in the
initial village as a broad puddle.

`water_layers.select_water` excludes explicit nonzero state suffixes before
conversion. Shared, state0, and unclassified layers remain eligible. In
particular, a layer called `setup` contains 57 water physics volumes; an
initial-state name whitelist would wrongly discard them without editor ancestry
evidence. This is not a complete reconstruction of quest-layer activation.

`build_water_probe` applies selection on new imports. `travel_bridge_package`
also repairs older packages using source water ID, exact bounds and geometry.
The repair removes complete water records, updates their tree block sizes and
file length, and atomically replaces the archive to detach inherited hardlinks.
Retained materials, geometry, physics and non-water records are unchanged.

Validation on the installed map: four of 282 water records removed (Skalitz
state1, two infirmarium state2 records, Neuhof massacre state1). All retained
record bytes match the baseline. Repeating repair changes nothing. All 511
unit tests passed. A fresh KCD2 launch showed the Skalitz dirt surface without
the previous broad water patch from the same overhead viewpoint; lighting time
changed across restart, so the captures are not a matched-lighting comparison.

Local backup and binary evidence: `outputs/WaterLayers/Map02/`. The post-install
Skalitz audit retains all 6,483 previously matched initial ground placements,
with 13 initial water records and no matched later-state water. Other sites have
binary validation but have not yet been visually checked. Water material-role
conversion and drainage-channel shader fidelity are separate remaining work.

The user subsequently confirmed the extra puddle is fixed and supplied a KCD2
close-up showing the drainage channel's wet sheen. No additional wet-material
change was made; broad material fidelity remains outside this layer fix.
