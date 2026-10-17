# Regional travel loading

The coachman route uses `wh::game::SwitchLevel`, preserving the current player
and save. New Game uses a different initialization path and must not be invoked
when travelling with an existing character.

Both custom routes now explicitly select the loading screen registered on the
installed native `trosecko` route (currently ID 2). This selects loading-screen
presentation; it does not introduce a new readiness condition. The engine's
`LevelChanger` observer owns loading completion. The current development log
shows it waiting with category mask 16275, becoming ready, and then transitioning
from `LEVEL_LOAD_ENDING` through `LEVEL_LOAD_COMPLETE` to `RUNNING`.

The destination graph's resident-station `entry_ready` flag is not a renderer
readiness signal. Do not use it or an arbitrary delay to dismiss a loading screen.
No global streaming settings, timeout changes or shader-cache deletion are needed
for this patch.

The former `GlueTravelHorseRecovery` Player hook is no longer included in new
builds. It retried after initialization and save restoration, then repositioned
and unhid the owned horse beside the player. Native companion ownership and
scheduling remain intact. The old Lua source is retained only as an exact
migration signature for removing it from existing packages. Removal preserves
the native Player script and subsequent animation/fishing wrappers.

Validation: unit tests cover native route registration and loading-screen
selection, rejecting missing native metadata, exact legacy-hook removal, repeat
migration, Windows line endings and executable Player lifecycle preservation.
A fresh in-game coach journey still needs validation: loading-screen visibility,
arrival streaming, player inventory/quests, owned horse and saddle inventory,
return travel and save/reload. Existing load logs alone do not prove a repaired
coach journey or the absence of arrival pop-in.
