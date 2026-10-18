# Source tavern upgrade

Recipe 26 adds the Skalitz tavern through source-driven adapters. Setup finalization runs the same migration for clean builds and supported saved builds. The selected actor is configuration; dialogue topic IDs, schedule intervals, shop stock and quest-item events are discovered from the source data.

The merchant resolver follows work links into source layers. Missing stock definitions go through the normal item dependency converter. Shop activity uses native scheduler opening/context effects during the source business hours; quest conversations are scoped to the selected actor and quest subchapter. Missing source voices are registered from the KCD1 abbreviation table under separate IDs, without replacing native voices.

Quest-item CreateInvItem/RemoveInvItem calls are lowered to native ownership state. Unsupported compound control flow, ambiguous holders, missing backup storage and missing item dependencies stop conversion. Ordinary inventory items retain their existing handling.

Bianca currently retains the source all-day work interval and 06:00–21:00 shop hours. Her broom and two authored sweeping routes are converted. Patron drink/meal orders, table wiping and closing announcements remain explicitly pending; this is not a complete conversion of sa_pub_v3.

Validation: the canonical build completed setup finalization at recipe 26. Original recordings, stock, native item ownership and schedule links are packaged. In-game conversation, trading, ale handover and navigation still require a fresh New Game test. Existing saves may already have consumed old dialogue events.
