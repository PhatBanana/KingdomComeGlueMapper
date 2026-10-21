# Generic shop-guard work upgrade

The next work adapter recognizes `final/sa_shop2.xml:guard`. It resolves the
source area's `guardWork` links and converts back-only leaning posts to KCD2's
native `leaningSpot_back.use` activity. This is the source shop guard's work
pose, not a new garrison patrol or a grant of guard authority.

Actor names, towns, coordinates and work hours are not built into the adapter.
The first local fixture selects `ska_filip` and `ska_general_store_guard`:
their authored schedules use the same grocery-shop area, two wall posts and
0–1440 work intervals. These names only select the playtest subjects.

Each actor's existing idle schedule becomes a dispatch hub with the source
intervals. The posts have stable shared identities and native `MaxInstances=1`
occupancy. Two workers reference the same two posts rather than receiving
private copies of each location. The source helper alignment is transformed
into KCD2's `leaning_back` helper alignment; raw editor origins alone are not
used as animation contacts.

KCD2 owns movement, leaning, interruption and dialogue contexts. Its scheduler
may select either authored post on subsequent activity evaluations. The adapter
does not reproduce KCD1's exact post-selection cadence or its blanket situation
suppression. It does not change factions, quest initialization or NPC AI flags.
Multi-orientation and non-leaning source posts are rejected rather than assigned
an invented replacement activity.

Setup includes the adapter in its converter inventory. Recipe 43 upgrades older
completed packages, including recipe 42. Population conversion publishes native
animation collections and per-post transforms to both the level archive and the
mounted travel aliases, using the same animation installer as the test builder.
Already converted work and quest/service schedules remain protected.

## Build and verify

Use `tools/build_person_schedule_test.py --jobs` with both game roots, the current
level/travel PAKs, a fresh output directory, and the two `--person` selections
above. This produces staged replacement archives, not a standalone mod.

Automated checks cover source-link selection and pruning, helper alignment,
exclusive native occupancy, shared post reuse, source intervals, changed native
contracts, unsupported orientations, conflicting resources, animation collection
registration and refusal to overwrite a converted actor schedule.

## Runtime acceptance

1. Install the staged result through the package workflow and start a fresh
   session with the source profile active.
2. Observe each guard walking to a grocery-shop post and leaning against the
   wall with the correct facing. They must not occupy the same post together.
3. Start and finish a conversation; check that the activity can interrupt and
   resume without leaving the actor frozen or clipping into the wall.
4. Leave and return, and check both guards again. Review the log for movement,
   animation-queue and state-search errors.
5. Verify Johanka/Sarka's embroidery and unrelated quest NPCs remain functional.

Archive and automated checks do not establish that these runtime steps passed.
