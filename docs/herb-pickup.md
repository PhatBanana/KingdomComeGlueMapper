# Herb pickup conversion

Herb harvesting is registered through `pickable_area_material`, whose
`material_name` fields actually contain vegetation CGF paths. Each row selects
a `pickable_area_desc`, which supplies the harvested item GUID and harvesting
settings. Native `PickableArea.lua` offers `inr_herbGathering` and calls
`Minigame.StartHerbGathering`. This is separate from loose-item `PickableItem`
interactions. The global `pickableAreasDisabledInGeneral` can suppress picking.

Both vegetation conversion stages now save `Data/herb-model-map.json` from
their actual source group to emitted CGF mapping. Campaign packaging uses this
map to generate `Data/gluemapper_herb_pickup.pak` inside the existing mod. Its
single additive table is
`Libs/Tables/item/pickable_area_material__kingdomcomegluemapper.xml`.
Native descriptors and inventory items are reused only when their IDs agree.
Conflicting or missing contracts are logged without inventing replacement items.
Decorative models do not receive harvesting registrations.

`herb-pickup-report.json` records registrations, unresolved contracts and source
pickable models absent from the converted mapping. Runtime success remains false
until tested in game. Legacy builds can recover provenance from the original
vegetation/instances reports using `recover_report_model_map`; it checks every
generated path and preserved group signature against the installed terrain.
The weaker signature-only fallback reports ambiguous groups rather than guessing.

## Development test, 2026-10-11

The user's alpha.4 build reports were checked against all 508 installed vegetation
groups. The patch registers 29 generated models. No registered descriptor has a
missing or conflicting native inventory item. Two poppy plane variants and weed
are absent from this converted group mapping and are logged, not silently counted
as supported. KCD2's GeneratedDatabase reader accepted the generated XML.

Only the development mod was patched; retail was not modified. The development
client was subsequently relaunched at the user's request. Its log confirmed the
herb patch mounted and `kcd1_travel` reached `RUNNING`.

## Runtime acceptance

On 2026-10-11 the user confirmed: "herb picking is working" in the development
client. This establishes a successful live harvesting test, not exhaustive
coverage of every registered species. Generated reports retain `runtime_verified:
false` by default because generation itself does not perform a gameplay test.

Still check individual species, precise inventory quantities, harvested-state
persistence after save/load, experience/perks and respawn. Retail gameplay has
not been verified for this patch.
