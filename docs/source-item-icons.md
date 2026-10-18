# Source item icons

Recipe 28 applies source inventory artwork during clean setup finalization and
saved-build upgrades, after character/material conversion. It replaces generic
presentation-template icons on identifiable imported items. Native game archives
are not edited.

`item_icons.py` resolves the KCD1 player-item icon index by source item GUID,
the converter's namespaced source GUID, or a character garment's source name
and localization key together. Ambiguous identities fail instead of selecting
another item from the same category. Generated composite outfits without a
single source identity retain their existing presentation.

`item_icon_atlas.py` follows the source `Libs/UI/ico_items.gfx` timeline through
its sprite, bitmap-shape and external subimage references. Inventory frames are
one-based. An authored empty frame is preserved as transparent artwork; an
unresolved reference is an error. Images are extracted from the user's own KCD1
atlas textures, centered with transparency in 64-pixel DDS textures, and reduced
proportionally only when necessary to fit that canvas.

The item row receives `IconId="gm_kcd1_item_<index>"`. The corresponding texture
is packaged at `Libs/UI/Textures/Icons/Items/gm_kcd1_item_<index>_icon.dds` in
`Data/gluemapper_item_icons.pak`. Item IDs, gameplay properties, models, inventory
ownership and quest logic are unchanged. Setup receipts include the generated
archive and all changed item-table archive hashes. No source artwork is shipped
in this repository.

Validation on 19 October 2026 resolved 927 imported item entries to 425 unique
icons in the current build. Extracted crossguard, beer jug and key images were
visually checked. Unit tests cover one-based indexing, empty frames, missing
references, alpha preservation, identity matching and idempotence. The full suite
passed 1,275 tests with 17 skips. The user subsequently confirmed the installed
icons work in the Mod Tools game. Retail rendering has not been separately
verified for this change.
