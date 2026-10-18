# New Game comparison, 2026-10-18

Compared the working reference at
`D:/SteamLibrary/steamapps/common/Backup/kingdomcomegluemapper` with the installed
retail recipe 11 package. No installed archives or saves were modified by this audit.

## Startup mismatch

Follow-up correction: the actual native `Libs/concept/definitions.xml` describes
`IsNewGameModeDebug` as checking whether the game was started as NewGame or
NewGameDebug, with an `IsDebug` output. Its use in `new_game_debug.xml` alone did
not establish its complete behavior. The earlier causal diagnosis below remains
unconfirmed at runtime. Recipe 12 removes this ambiguity from our entry wiring by
using the native `GameStart.OnStart` event and separate region readiness instead.

In `Quests/GlueTravel/GlueTravel_kcd1.xml`, the reference connects
`gm_kcd1_character_creation_begin.True` directly to the initialization sequence.
The installed package instead evaluates `wh::rpgmodule::IsNewGameModeDebug`.
Its true output starts initialization; its false output sets the persisted
`gm_kcd1_character_creation_started` latch without initializing the campaign.
This gates the starter loadout, baseline stats, imported quest start and opening
dialogue together.

The installed menu calls `GlueMapperNativeNewGame`, whose Scaleform implementation
emits `FSCommand:onBasicButton` with `NewGame`. It does not select debug New Game.
The native Mod Tools `Data/Scripts.pak` module
`Quests/Final/Barbora/new_game_debug.xml` uses the same predicate to set
`isNewGameDebug`; it is explicitly the native debug-start detection module.
This initially suggested a mismatch between the menu route and startup guard,
but the native definition described above does not support that conclusion on
its own. The predicate's runtime return value was not instrumented during this
audit, so the cause of the reported failure remains unconfirmed.

`campaign_scene.attach_scene` inserts the guard through `campaign_start_policy`;
`setup_package_upgrade.finalize` also applies it to migrated packages. Existing
validation checks this wiring and treats it as valid. It does not test an ordinary
retail New Game or establish that the predicate is suitable for that route.

## Content present versus absent

- All 82 reference quest XML paths are present; the installation has 83.
- All 27 opening voice entries have identical payloads.
- Mother and father have identical entity GUIDs and positions in both level files.
- Of 119 reference voice paths absent from the installation, 116 are duplicated
  parent-dialogue recordings present byte-for-byte under `dialog/kcd1_travel/`.
  Raw archive entry counts therefore do not establish missing parent audio.
- Three Neuhof horse-sale recordings have no same-basename counterpart in the
  installed English archive. This is a separate content difference; it does not
  explain the opening quest failing to start.
- Parent interaction 14857's XML differs only in port ordering, not dialogue content.

## Confirmed archive dependency failure (2026-10-18)

The Mod Tools runtime log explicitly reports:

```
XML reader: Can't open file 'quests/gluetravel/entry/../world/../../../quests/final/barbora/open_world/boj_a_zraneni.xml'
Concept xml file: ... missing or invalid!
Unable to load concept graph xml quests/gluetravel/gluetravel_kcd1.xml
```

The setup's added world gameplay wrapper used parent-directory references into
Scripts.pak. Its Python audit normalized those paths, concealing the failure of
the runtime archive lookup. Rejecting the whole project explains why changing
the arrival gate alone did not restore clothes, quests or the opening dialogue.

Recipe 13 packages the selected native graph closure privately below
`entry/world/native`, with downward-only includes and flat child dependencies.
It does not replace native Barbora graphs. The same transformation runs during
existing-package migration; it preserves the world and lighting bake. The SDK
test package contains 373 wrapper/dependency graphs with literal paths verified
against the archive. That first repair exposed missing inherited utility types.

Recipes 14 and 15 collect explicit, empty and relative utility namespaces and
preserve the native library scopes. Recipe 15 validates 423 dependency graphs
against native built-in node types, with zero unresolved custom types. On
2026-10-18 the user confirmed the installed Mod Tools New Game startup fix
worked. The new log proceeds into gameplay rather than rejecting GlueTravel.
Reported movement, tutorial and dialogue warnings are separate follow-up work.

## Startup policy and remaining acceptance boundaries

The startup-policy change replaces debug-mode detection with a campaign-start signal
from the ordinary menu route. Preserve once-only initialization and existing-save
visitor protection: simply removing the guard would reintroduce stat/loadout
resets when travelling from Trosky. Migrate both clean-build output and resumed
packages, and test ordinary New Game, an existing-save visit, and a reload/return.
Saves that already took the false branch may have the initialization latch closed;
use a genuinely fresh test start, rather than resetting arbitrary existing saves.

This New Game confirmation does not certify every quest or dialogue branch,
retail runtime parity, or existing-save travel/reload behavior after this change.
