# Fritz in native Trosky

Build with `tools/trosky_bandit_test.py --kcd1 <installed KCD1> --kcd2 <installed KCD2> --output <fresh output>`.

This standalone mod uses the existing `character_bandit_clone` helper and
`tpod_bandit_3` template with `ska_fricek` appearance. It retains native bandit
soul fields, faction, equipment and the same isolated schedulerWait baseline
used in the original KCD1 comparison. It does not load the travel bridge or
the later KCD1 camp faction patch. It is a native-region control, not a full
camp-schedule transplant.

The builder finds `tsla_nomad`, the native region-travel coachman, and selects
a road footprint 80–100 metres away, preferring 90 metres. It checks road
triangle coverage and terrain slope and grounds both actor and idle marker.
The revised position is `2620.8781,1615.0510,94.73598`, northwest of the coach.
The original 12-metre placement was too close to the camp. Existing native
entities, level services, quests, navigation and layers remain intact.

Use only `gluemapper_fritz_trosky_test` in `Mods/mod_order.txt` for the test.
The installed `kingdomcomegluemapper` folder stays intact. To switch back with
the game closed, put only `kingdomcomegluemapper` in that file; do not delete
the order file while both mods are installed, because that may enable both
conflicting Trosky level overrides.

Load a Trosky save from before the encounter, approach the travel coachman,
and reproduce the on-foot attack/block sequence. Record whether Fritz attacks,
whether Henry can respond, and whether mounting changes the lock. Use a
separate test save. A pass narrows the investigation toward destination world
registration; a failure also leaves clone, scheduler and character conversion
as candidates. Neither result alone establishes the engine cause.

2026-10-11 build: `outputs/BuildWork/fritz-trosky-control`. All 303 unit tests
passed, as did five tables through the official GeneratedDatabase reader.
Packaged verification found only four changed native level resources:
objects_mission0.xml, whdata_0, waitinglinks.xml and tables/ai/scheduler.xml.
The native mission was unchanged except for the added NPC and position marker.
Installed files were verified against build SHA-256 hashes. Live combat is
pending user testing.

The relocated build is `outputs/BuildWork/fritz-trosky-road-test`. All 303
tests passed again; the previous test installation was backed up before the
verified replacement was installed. Load the pre-encounter Trosky save so an
already-saved NPC position does not supersede the new placement.
