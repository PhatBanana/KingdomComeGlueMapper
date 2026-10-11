# World pickups

The Python world builder registers authored KCD1 `PickableItem` placements and
initially populated `ItemSlot` placements as native KCD2 `ItemSlot` entities.
Source NPC-only items and inactive quest layers retain their original restrictions.
A slot linked to an existing placed item is deduplicated before conversion.
Static furnishings are not made collectible merely because they have a mesh.

The current source installation produces 1,773 placements covering 173 item IDs:
81 reuse existing native/mod definitions and 92 receive new typed definitions.
The new definitions cover weapons, bows, ammunition, clothing, food, misc items,
documents and potion items. Source-only entries retain their source item GUIDs.
Names, descriptions, drop geometry, materials, textures, weapon/armor statistics,
book text and document illustration textures are imported. Inventory icons use
native presentation templates; original numerical atlas indices are not portable.

Source parent transforms and slot-local item transforms are composed before
placing native slots. The 1,703 corresponding decorative entities are removed
only after every item dependency resolves. Seventy pickups had no old visual.
Any failed definition or dependency aborts staging rather than dropping items.

Native slots have borrowed-item saving enabled and restock/destock disabled.
Ownership uses native `bOwnedByHome`, so theft behavior depends on which homes
have been registered in the imported world. This does not import every source
owner, home or quest controller. Source links remain in the audit report.

## Build paths

`tools/world_items.py` is shared by the normal `region_travel.py` build and the
incremental test builder:

```powershell
python tools/build_world_items_test.py --source <KCD1> --target <KCD2Mod> --mod <installed-mod> --output <fresh-output>
./tools/validate_database_tables.ps1 -ModToolsPath <KCD2Mod> -TablesPath <fresh-output>/validation
```

The incremental builder stages replacements and a separate asset PAK inside the
same mod. It never installs or launches the game. Its report records original
package hashes, produced hashes, item dependencies and every pickup placement.
Installation must check those baseline hashes and happen while the game is closed.

## Validation boundary

The user confirmed the installed pickup test build working on 2026-10-12 after
launching the developer client at the original Skalitz starting location. This
confirms that playtest; it does not establish every equipment or save/reload case.

Asset-free tests cover source restrictions/deduplication, stable identities,
failure without visual removal, local transforms, native persistence properties,
and preserving empty bow attachment sockets. Native database deserialization
checks the generated registrations. Neither proves runtime pickup persistence,
clothing fit, bow animation or reading behavior.

The four source-only potion entries retain their basic food values, but their
special consumable/weapon buffs need a separate conversion; those source records
are recorded in `secondary_gameplay_pending`. Document text/images are imported;
skill-book rewards and source quest progression are not claimed as converted.
These entries are registered and placed rather than omitted.

In-game acceptance should include taking bread/cheese at the Rattay inn, taking
a source-only item, checking inventory text/model, dropping and retaking it, and
loading a save after pickup to check it does not respawn. Equipment, documents,
ownership/theft and more distant streamed placements need their own checks.
