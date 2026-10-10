# Generated world-system control

`tools/generator_control_map.py` builds `fritz_generator_control` using the
working `fritz_editor_control` export as its physical fixture. It regenerates
the scheduler, persistent link network and whdata through
`tools/control_world_compile.py`. That compiler has no NPC-name or region-name
rules. Unsupported scheduler syntax fails explicitly.

This is a bounded world-system compiler experiment. It does not yet exercise
the entire production KCD1 importer or regenerate terrain/navigation. The new
compiler is not yet wired into the travel build. Those boundaries must remain
explicit when interpreting a successful fight.

Before packaging, all three generated XML files must match the editor export
semantically, ignoring XML formatting and collection order. All three passed.
The geometry, navigation, soul records, native bandit equipment and animation
helper collections remain the reference fixture. The original export remains
unchanged. The existing modding-tools character asset package is required.

## Standalone entry correction

The first standalone run loaded the level and NPC but logged:
`warning: No spawn points; using default spawn location!`
The user was falling. Sandbox had supplied its editor camera position in the
reference test, whereas the game executable's SinglePlayer OnClientConnect
creates the player at the origin when no SpawnPoint exists.

The generator now emits a native enabled SpawnPoint derived from the saved
editor View/ViewerPos (512,511,33.7 for this fixture). It does not teleport the
player via a test script. Loose per-level table files are also emitted for
standalone table discovery. The original three parity checks run before this
standalone-only spawn addition.

Evidence:
- `outputs/BuildWork/fritz-generator-control/comparison.json`: initial build.
- `outputs/BuildWork/fritz-generator-control/initial-falling.log`: failed entry.
- `outputs/BuildWork/fritz-generator-control-spawn/comparison.json`: corrected build.
- Modding-tools `generator-control-spawn.log`: corrected runtime session.

Launch uses the modding-tools KingdomCome.exe with `-devmode`, a separate log,
and `+map fritz_generator_control`. The game reads the generated PAK directly;
Sandbox must not re-export over it before testing.

Acceptance: player starts on the floor, approaches the bandit, exchanges attacks,
can disengage and re-engage, and neither side stalls in the reported combat
lock. File parity and a successful level load do not establish this result.
No retail travel package was changed for this test.

## Live result — passed basic combat, 2026-10-11

After the spawn correction, the user confirmed: "yep it works" and "attacking
does not freeze". The preserved `combat-working.log` in the corrected build
directory records HitTarget events in both directions: Dude to the test bandit
and the test bandit to Dude. The corrected session has no missing-spawn warning.

This establishes working attack exchange for the generated minimal AI setup in
the modding-tools game executable. It does not yet establish that the KCD1 world
is fixed, that the production importer uses this compiler, or that disengagement
and re-engagement have been separately verified. Keep this fixture as the
positive control when integrating the contracts into the KCD1 builder.

## KCD1 builder integration

`region_travel.build` now calls `world_runtime_contracts.apply` after registering
the destination actors and activities, before writing the destination PAK. This
merges the native land-to-player link, streamable-player declaration, rerouter
and hangover service, and exported animation-helper collections. It removes
scheduler authoring labels from the static link network while retaining their
compiled scheduler rows. Existing quest, soul and shop data are preserved.

The bandit camp helper now uses the successful control's plain static `home`
contract alongside its existing schedulerWait. The camp area, location and
hostile faction are retained. Therefore those remain differences from the
minimal control, and the KCD1 combat outcome still requires a live test.

Build: `outputs/BuildWork/kcd1-control-contracts`. The 47 focused tests passed;
all 15 generated database tables passed the native GeneratedDatabase serializer
under PowerShell 7. The Windows PowerShell 5 invocation could not initialize the
serializer and was superseded by the successful PowerShell 7 check.

For the next retail test, load the pre-travel Trosky save and enter through the
coachman so the destination starts with the rebuilt world contracts. An existing
save made inside KCD1 may restore prior NPC state and is a separate persistence
test. The isolated Trosky test mod must be disabled for this travel test.
