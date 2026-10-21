# Generic town-walking bench breaks

The CityWalk adapter now resolves the source walking start point's one-hop Seat
query, pruning parent and inventory links. Only authored benches enter the pool;
nearby furniture is not selected by distance. Source behavior identity and links
select the conversion, without NPC names, gender restrictions or town coordinates.

Walking destinations remain available. Bench choices target the existing converted
StanceSmartObject seats and KCD2's native so_sitPlace.use behavior. The shared use
resource has MaxInstances=1; several NPCs reference the same seats rather than
receiving private copies. The native behavior owns the sitting stance, dialogue
contexts, completion and cleanup. Its ordinary wait is 15 game seconds, with
native context/synchronization exceptions. No animation update loop is injected.

The native scheduler chooses the next eligible activity. This does not enforce
strict walk/sit alternation or reproduce KCD1's bench/shop branch probabilities.
Shop browsing, weather shelter and source look-target selection remain pending.
Unsupported source seat families and missing converted benches fail explicitly.

Recipe 44 includes this adapter in setup and supports older recipe migration.
Existing importer-owned walking pools can be extended after checking their stable
identity, owning actor, source clock, native walking edges and destination geometry.
Unexpected activities are rejected. Actor schedules, quests, factions and existing
seat transforms are retained. Reapplying the extension does not duplicate links or
seats, and reports retain unrelated unfinished jobs.

## Validation and retail test

Automated tests cover source seat selection, shared occupancy definitions, native
lifecycle requirements, clock preservation, repeated extension and refusal to
change modified/quest schedules. These are structural checks, not runtime proof.

The initial real-source setup fixture uses ska_jan and the bench linked to the
Skalitz city-walking start point near (786.21, 3498.54, 51.93). This NPC name and
location are test selections only. The stage is outside retail and contains
replacement level/travel archives; it is not a complete standalone installer.

For live acceptance, install the staged pair with rollback and start through setup:

1. Observe Jan approach and sit at the authored bench with correct alignment.
2. Observe later walking activity; a scheduler evaluation can choose a seat again.
3. Start and finish dialogue, checking clean interruption and resumed activity.
4. Exercise two eligible walkers sharing the bench and verify no seat overlap.
5. Check schedule-end/leave-and-return behavior and movement/animation errors.
6. Confirm embroidery, shop guards and quest NPCs still work.

Do not report live acceptance until those observations have been made.

## Sitting-animation correction

The first retail test reached the bench but did not visibly sit. Read-only live
queries showed Jan at a seat's transform with a `bench` link to that seat; he also
resumed walking. This establishes activity selection, not a successful sitting
transition. The converted seat rows used `Hash=0`, despite carrying a native
helper collection containing SitDown and StandUp animations. Trosky's matching
bench rows reference that collection's nonzero hash.

The common seating converter now selects the unique native collection hash for
converted `Sit_1Place_` chair and bench helpers. It still writes the imported world
transform and enables local runtime validation, without copying native world
collision results or projected positions. Missing, zero or ambiguous collection
references fail validation. Bed and other activity helper policies are unchanged.

The corrected real-package candidate changes only smartobjectanimations.xml and
its travel-archive alias. It validates 3,070 converted chair/bench references;
mission entities, scheduler routes and seat geometry are byte-for-byte unchanged.
The user confirmed the corrected retail test works on 22 October 2026. This is
user-reported acceptance of the observed sitting behavior; multi-actor contention
and all interruption cases have not yet been observed in this test.

Setup applies the adapter to every eligible person in its selected source
profiles, including existing importer-owned CityWalk pools. Jan is only the
initial test subject. People without an authored CityWalk seat link are not
assigned arbitrary benches, and quest-owned schedules are not overwritten.
