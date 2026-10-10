# Working Sandbox export versus KCD1 travel — 2026-10-11

## Evidence and scope

The user confirmed that the control-map NPC attacked and killed the player.
The preserved log contains `HitTarget` events from `gmtest_trosky_ska_fricek`
against `Dude`. The NPC displayed the native bandit appearance, not Fritz.
This is a successful Sandbox combat test, not yet a matched retail/save test.

Compared the actual exported `KCD2Mod/Data/Levels/fritz_editor_control` with
the installed `KingdomComeDeliverance2/Mods/kingdomcomegluemapper/Data/Levels/kcd1_travel`.
The installed KCD1 `level.pak` SHA-256 matches both copies in
`outputs/BuildWork/fritz-local-camp`. This is the camp build that needs correction.
Raw entry inventories, hashes, selected entities, normalized scheduler rows,
whdata and waiting links are saved in
`outputs/BuildWork/fritz-editor-control/export-comparison-raw.json`.
Runtime evidence: `game-mode-native-appearance.log` in the same directory.

## Concrete differences

| Contract | Working editor export | Installed KCD1 package | Action |
|---|---|---|---|
| Land-to-player runtime link | `waitinglinks.xml` connects `sa_land` to player GUID `00007777-0000-0000` with `playerLinkRerouter`; player is also listed under `StreamableTargets` | Neither record exists | Add the compiled player binding and streamable-target declaration, preserving existing links. Copying only the editor TagPoint is insufficient: the exporter resolves its target to the player. |
| Smart-object animation helper collections | `smartobjecthelpersetanimations.xml`, 5,389,404 bytes, 730 collections | Absent from the level and all installed mod PAK entries inspected | Include the native exported support file. The control copy is byte-identical to native Trosky's. Its absence is confirmed; its responsibility for the combat lock is not. |
| NPC home | Static `home` link to `FritzHome`, then `home_area` to land | `_!home` scheduler activity with `AILinkHome=true`, plus an extra `_!home` entry in static waiting links; home area is the custom camp | Preserve the distinction between scheduler syntax and static links. Native `tpod_bandit_3` has `_!home` in EntityLinks and no static WaitingLinks originating from that actor. Our raw `_!home` waiting-link record is not native-export parity. Use the control's plain home contract for the first matched test. |
| Scheduler-only links | `_,schedulerWait`, `^delegate` and player activities are compiled into scheduler rows, absent from static waiting links | These authoring labels are additionally copied into static waiting links | Make generic link conversion distinguish scheduler authoring links from persistent static links. Do not indiscriminately copy every EntityLink into WaitingLinks. |
| Hangover service | Land has `hangoverSpotsHub` link to an empty TagPoint | Missing | Add for basic land-service parity; no evidence this explains combat. |
| Player schedule | `playerWait`, `animationAction`, plus `event_pocestny_playerIsPoisoned` | First two present, poisoning event excluded | The two core activities match. The extra event is not evidence of a combat requirement. |
| Faction | Native `trosecko_enemies_poachers_campPodseminsko` | Custom local faction `gmtravel_bandit_ska_fricek_faction_3` | Keep this as an explicit test variable. Both use brain `4b914d1c-724a-a92d-3e6b-d183d35b8b98`, social class 38 and combat level 0.3. |
| Player/startup | Editor-created `Dude`; direct Sandbox game mode | Transferred retail player and travel concept graph | Match player/save/perks and launch mode before claiming a cause is isolated. |

## What already matches or is present

- The NPC's `schedulerWait` parameters match exactly after resolving GUIDs to
  names. Both use an idle-position delegate targeting `sa_land`.
- The two core player activities match, including animationAction priority 60
  and Instant urgency. The player scheduler smart-object type also matches.
- Land uses the same native smart-area template. Both register land with
  SmartAreaManager version 2 and set the appropriate AI LevelPath.
- Both have the crime interruption smart-object types and debugger connection.
  The control's carrot host is a GeomEntity; the importer uses SmartObjectHolder
  with the same smart-object type. This is a structural difference, not a proven
  failure.
- Both have a separate `recast.pak`. The control has 3 entries; KCD1 has 736.
  Base `rdnavmesh_1.nav` settings (first 56 bytes) match exactly. Base NAV sizes
  are 19,192 and 95,208,840 bytes respectively. This establishes presence and
  matching settings, not runtime walkability at the camp.
- KCD1's global PAK contains its correctly named per-level scheduler mount path.
  The scheduler is not simply absent from the package.

## Packaging and conclusions

The official export uses both stored and deflated ZIP entries. The importer uses
stored entries throughout. Both archive forms were readable; this comparison
does not establish compression as the cause. The missing exported content and
link-compilation differences are more specific findings than a general PAK-mode
hypothesis.

The successful minimal control has no guards or level-exit network. These remain
dependencies of particular behaviors, but they are not prerequisites for this
observed attack. Likewise, the control logged the RPG-generation diagnostic and
still attacked: that warning alone cannot explain the original lock.

Next: implement the missing player binding and native helper collections in the
generic world builder, correct static-versus-scheduler link emission, then test
a simple home/idle bandit on the KCD1 map using the same player. Retain the current
raw editor export as an unchanged reference. Do not call the combat lock fixed
until retail exchanges of attacks, disengagement and re-engagement pass.

This comparison did not change or install any runtime package.
