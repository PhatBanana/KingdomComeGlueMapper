# Source work ownership audit

`tools/source_work_coverage.py` separates profile actor membership from ownership
of that actor's authored work area and selected workplaces. Its setup-facing API
is `audit(source, profiles, source_level='rataje')`. It returns a report and never
activates jobs, writes a game package, or removes source links.

The report uses source `whdata_1` GameProfile/GameLayer membership and persistent
entity identities. An area in `objects_mission0.xml` is global, not automatically
a local job. Layers without an owning profile remain unknown. No actor-name
whitelist, settlement-name comparison, or arbitrary distance threshold is used.

For `CompoundWorkCamping`, the audit validates the source `CompoundWork2_main`
one-hop `compWork` search and its `$compWork.srcBeh == $__behaviorName` filter.
Only matching links are considered candidates. Reservation, requestability,
dynamic timing callbacks, concurrent speech, and LOD/time-change handling are
not replaced by an idle or bench activity.

## Actual Skalitz profile result

The proof is `reports/jobs-completion/source-work-ownership.json`, generated from
the installed KCD1 source for `q_skalitz_normal`. Its 55 actors have 46 resolved
source work assignments: 35 have a work area owned by the selected profile, ten
have unresolved ownership through global areas, and one has all selected
workplaces owned exclusively by other profiles. These are ownership counts,
not completed or runtime-verified job counts.

The last assignment is `vra_vanek`, whose source
`Work[('CampingLeader')]` points to `VranikCamp` (`41698803F623ABF4`). The source
filter selects exactly two resources:

| Resource | Persistent identity | Owning profiles |
| --- | --- | --- |
| Bench, EntityId 114342 | `484B6791409AD2E6` | `q_infiltrationandcapture_vanek` |
| Chair, EntityId 124485 | `4A2DEE6647A092FF` | `vra_vranik_state1`, `vra_vranik_state2`, `vra_vranik_state3` |

Neither belongs to `q_skalitz_normal`. Counting this as a missing Skalitz camper
would misclassify a later-campaign assignment. A complete runtime adapter needs
the appropriate source profile/quest activation, not unconditional opening-game
activation of Vranik work.

## Installed Vanyek dependency audit

The installed actor `713eaac2-427f-4c31` has native links for schedulerWait, home,
intro, departure, sleep, and lesson. No Work/CampingLeader link survives as a
compiled activity. No `CampingLeader` or `VranikCamp` string was found in the
installed root Data PAK XML/Lua scripts during this audit.

An explicit source Home link does survive: actor to
`gm_person_home_vra_vanek` (`db9b89aa-15ed-920b`, EntityId 39897), then `home_area`
to `gmtravel_location_VranikCamp` (`f623abf4-8803-4169`, EntityId 13198). The home
hub is at source position `883.94312,945.3924,111.14446`. This comes from the
source Home link imported by `character_person_world.py`, not an inferred Work
fallback. Native home consumers include property, stash, mourning, and trespass
reactions. No unconditional go-home action or current active reaction was proven.
The remote Home metadata therefore does not establish the cause of Vanyek's
observed movement, and it was not removed.

His schedulerWait PositioningDelegate is the local imported idle TagPoint at
`772.93317,3471.1392,52.499729`. That point's `^delegate` targets `sa_land`, the
world-wide native smart area; it does not target Vranik. The imported Storm role
contains only the actor's generated role, without a CampingLeader job.

Seven regression tests cover profile filtering, global/unknown ownership,
source search drift, conflicting identities, and nonmutation. This audit used
archive reads only; no game controls, installation, or runtime job verification
were performed.
