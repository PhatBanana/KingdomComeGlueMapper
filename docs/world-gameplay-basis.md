# KCD1 world gameplay baseline

The comparison target is retail Trosky. A native NPC brain and interrupt host
alone do not supply the world's gameplay graph, surrender dialogue, services,
or regional bindings.

`tools/world_gameplay_basis.py` is called by the normal region-travel builder.
It attaches an `open_world` gameplay module beneath the destination Level,
with the native `LevelHolder -> module -> SmartObjectHolder` link convention.
The module's lifecycle belongs to the KCD1 destination. It does not replace
the game's Barbora project or enable Trosky story quests in KCD1.

## Implemented registrations

18 native systems are referenced from the installed game's Scripts.pak:
combat, injuries, reactions to the player, reputation, NPC sleep, greetings,
farewells, friendly/enemy reactions, statistical perks, perks, weapon-holstering
requests, generic action prompts, battle and punishment barks, shops, repairs,
and sharpening. These resolve to 372 native graph files in the tested install.
Their scripts, dialogue decisions, string keys, and outcome messages are not
rewritten. This is registration evidence, not proof that every service works.

The build creates destination-owned `open_world` and `surrenderHolder` entities.
Both CryEngine EntityLinks and the exported waiting-link network contain:

- Destination LevelHolder -> open_world: `module`
- open_world -> itself: `asset['openworld']`
- open_world -> surrenderHolder: `asset['surrenderDH']`
- sa_land -> open_world: `punishment_openworldQSO`

The player aliases come from the native project. Selected graphs inherit any
native project enum types they use. No Trosky entity coordinates or unresolved
links are copied into these service entities.

The native combat subtree includes the surrender chat prompt and dialogue,
including `crime:mercyDialogueResult` messages. Displaying an Alt hint alone
would leave the AI waiting for a result; the complete native subtree is used.

## Dependency report and remaining conversion

`travel-build.json`, under `stations.kcd1.entry.gameplay_basis`, inventories all
50 native open-world definitions, their input ports and inherited asset
dependencies, registered status, and hashes of the selected dependency files.
The build fails if a selected system gains an unresolved asset, campaign input,
missing definition, or parent wiring requiring an adapter.

Full Trosky parity is explicitly **not yet verified or implemented**. The other
32 definitions include both useful systems needing conversion and debug/story
systems that should not run unchanged. Outstanding work includes:

- Crime punishment: KCD1 guards, jail/teleport locations, faders, time-skip and
  arrest cutscene holders, with the native completion messages.
- Fleeing: valid KCD1 escape/exit destinations and guard connections.
- Companions: native horse and dog graph dependencies and persisted ownership.
- Hunger/tiredness, tutorials, codex and other campaign-gated services: replace
  Trosky story prerequisites with appropriate destination/save-state contracts.
- Teachers, bathhouses, minigames and regional services: bind the actual KCD1
  actors, locations, inventory and service holders.

Do not treat an unregistered entry as permanently blocked; it is an adapter
work item. Do not enable it by silently defaulting its missing inputs or copying
Trosky's spatial dependencies.

## Verification boundary

Automated tests cover destination bindings, preservation of existing graphs and
world data, and rejection of unresolved dependencies. Native Definition and
asset-scope closure is audited against the installed game. XML checks do not
substitute for the engine's Skald compiler or runtime behavior.

Retail acceptance still requires entering KCD1 through coach travel, exchanging
attacks, making an NPC surrender, seeing the native interaction prompt, and
exercising mercy/refusal so combat can end or resume normally. Repeat after a
save/load and a return trip. The earlier control-map result proved ordinary
attack exchanges, not surrender or these additional world services.
