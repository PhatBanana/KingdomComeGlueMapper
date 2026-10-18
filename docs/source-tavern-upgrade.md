# Source tavern upgrade

Recipe 26 adds the Skalitz tavern through source-driven adapters. Setup finalization runs the same migration for clean builds and supported saved builds. The selected actor is configuration; dialogue topic IDs, schedule intervals, shop stock and quest-item events are discovered from the source data.

The merchant resolver follows work links into source layers. Missing stock definitions go through the normal item dependency converter. Shop activity uses native scheduler opening/context effects during the source business hours; quest conversations are scoped to the selected actor and quest subchapter. Missing source voices are registered from the KCD1 abbreviation table under separate IDs, without replacing native voices.

Quest-item CreateInvItem/RemoveInvItem calls are lowered to native ownership state. Unsupported compound control flow, ambiguous holders, missing backup storage and missing item dependencies stop conversion. Ordinary inventory items retain their existing handling.

Bianca currently retains the source all-day work interval and 06:00–21:00 shop hours. Her broom and two authored sweeping routes are converted. Patron drink/meal orders, table wiping and closing announcements remain explicitly pending; this is not a complete conversion of sa_pub_v3.

Recipe 27 repairs ordinary inventory creation calls through the shared script translator: `Utils.CreateInvItem` becomes `ItemUtils.CreateInvItem`, preserving the source recipient, quantity and health. Managed quest items still pass through the ownership-state adapter. Generated shop entry sequences inherit the existing trade prompt, preventing internal graph names from appearing in the dialogue menu.

The dialogue-request adapter follows a bounded source chain: objective-start mailbox event, registered cutscene callback, immediate one-shot actor schedule patch, and guarded dialogue initiator. It resolves the source actor and conversation alias, waits for the current scene to finish, then enqueues the native conversation. It does not select a quest, actor or reward by a hardcoded ID. More complex source branches remain outside this adapter's supported scope.

Both clean setup finalization and saved-build upgrades apply these adapters. Recipe 26 remains accepted for migration to 27; the desktop setup explicitly includes the new modules in its converter bundle.

Validation: on 19 October 2026 the user confirmed the installed Mod Tools repair works after testing the ale handover, Saviour Schnapps reward and trade label. This confirms that feature, not all tavern schedules or retail parity. Existing saves may already have consumed old dialogue events; use a save before requesting the ale or a fresh New Game to exercise the repaired handover.
