# Container conversion

The container importer translates the initial-world KCD1 `Stash` family to
native KCD2 storage. Temporary unowned access is intentional until homes and
NPC ownership are converted. Inactive quest layers remain inactive.

## Source clothing support

Container loot uses the original item GUIDs. Missing wearables are imported
with their KCD1 meshes, materials, colour parameters and available morph
variants. Equipment roles are selected from source garment archetypes, then
assigned native KCD2 equipment slots and layers. The source material-type
number is not treated as a native equipment-slot enum.

Supported paths include male and female clothing, armour, helmets, gloves,
boots, jewellery and horse equipment. Native definitions already present in
the installed item registry are reused. This is not a blanket replacement of
native items with KCD1 models.

The current dependency run resolves all 589 item types referenced by the
audited stash inventory presets. It produces 312 additional wearable
components. Twenty source entries reference morph names absent from their
mesh: those use the original base mesh, and the missing request is recorded
in the dependency report. They do not silently select another variant.

Every generated `PresetItem` includes both its registered native `Name` and
original item GUID. GUID-only entries passed schema validation but produced
blank loot screens in the development game. The correction covers all 174
generated inventory tables (2,208 item entries), and the user confirmed the
starting-home fruit sacks work after the correction. The converter rejects
items without a resolved native name. This is a sampled gameplay check,
not whole-map acceptance or a save/load test.

The skin converter preserves render geometry and maps source weights to the
native skeleton. An explicitly enabled correction handles uniformly offset
internal bind-position buffers, with a 25 cm limit; nonuniform discrepancies
still fail. This does not establish that every garment fits every native body
or layers correctly with every outfit. Runtime fitting remains a separate
acceptance check.

## Build and evidence

1. `tools/container_audit.py` reads active source placements, inventories,
   locks, phases, ownership and service references.
2. `tools/container_items.py` resolves item, wearable, model, material and
   localisation dependencies before container registration.
3. `tools/build_world_containers.py` stages native stashes, inventory presets,
   key dependencies, original models and phase models in bounded asset shards.
   It preserves the existing shared personal-storage registrations.

The staging builder does not install its output. Its localisation archive is
an addition to the installed archive and must be merged, not copied over it.
The pre-conversion level is required as the baseline; repeated registration
of the same source container fails.

Reports distinguish generated data from runtime verification. Native loot
generation is not seed-identical to KCD1. The current translation retains
direct rows and weighted preset choices, with explicit quantity ranges.
Restock intervals are translated to integral native days; sub-day intervals
round up and are identified in the report. Source random-selection semantics
and restoration after save/load require further acceptance testing.

Source merchant generation, home/NPC-generated contents, confiscation and
campaign-driven transfers are additional contracts. A converted physical
stash is not evidence that those services are active. They must not be
reported as completed solely from entity or item-definition counts.
