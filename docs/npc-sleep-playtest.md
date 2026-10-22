# Native NPC sleep extension

Setup recipe 48 adds timed native bed activities through the shared population
upgrader. Eligibility comes from the selected source profile, human actor,
source daycycle and home/bed links. There is no NPC-name selector. Existing work
and quest activity links remain intact; the new sleep choice has priority 2,
below the converted quest activities. Actor initialization is unchanged.

## Clock policy

- Preserve authored sleep intervals, including intervals spanning midnight.
- For a prologue-style single all-day work activity, infer sleep from human
  KCD1 daycycles of the same social class. Reject malformed clocks and samples
  shorter than four or longer than twelve hours. Use a circular average of
  bedtime and a mean duration; the averages describe game data, not real-world
  sleep requirements.
- Apply a stable per-soul offset, bounded by the source spread and capped at
  45 minutes. Rebuilding or loading does not rerandomize it.
- Divide guards sharing an authored workplace into day/night duty cohorts.
  Unassigned guards use a coarse source-position group. Use observed daytime
  sleep samples for night duty and nighttime samples for day duty. This is an
  invented daily rota, not a complete patrol or shift-handover controller.
- Preserve multi-activity schedules that contain no sleep instead of guessing
  which authored activity to replace.

## Place selection

Follow the source Home link. Prefer its bed assigned to this sleeper, then its
unassigned beds ranked by source sleep quality. Never take a bed reserved for
another sleeper. If no home bed is usable, offer converted camp, shelter, tent
or sleeping-bench objects within 300 metres of the converted actor placement.
Fallback objects must have no preferred sleeper, be unlinked or linked only to
a hostel, and lie outside authored private-home boundaries.

The fallback classification is inferred from authored links and home geometry;
it does not prove legal access or path reachability. It does not create beds,
change home ownership or enable arbitrary ground sleeping. Native bed resources
permit one occupant at a time. A pool of candidates does not guarantee there is
an available reachable bed for every NPC.

Mum and Dad both link to the forge home, but that home's source links include
no `Bed` entity. Both currently receive public fallback candidates. Matthias,
Fritz and Matthew have no Home link; these are different source-data cases.
Missing linked beds do not establish that visible bed furniture is absent.

## Validation and limits

The 22 October 2026 real-data conversion selected all 55 people in
`q_skalitz_normal`: three authored sleep clocks and 52 generated clocks. All
55 have converted bed candidates. Repeating the sleep adapter produced
identical output and reports; all prior compiled activity links were preserved.
The setup work-upgrade path was also exercised on a private copy of retail.
Its staged overlay is `D:\BuildKCDMod\sleep-20261022`, with baseline hashes and
validation in `validation.json`. It preserved all 3,597 existing activity links,
matched the mounted scheduler alias and produced byte-identical archives on
repeat application. The overlay is not a standalone full mod package.
On 22 October 2026 it was installed into retail over its verified chopping
baseline, with installed hashes and the ownership receipt verified. Rollback
copies and the transaction journal are under `retail-install/` in the stage.
The receipt retains its baseline recipe version and records this targeted
update separately as `npc_sleep_playtest`; it does not claim a full recipe-48
rebuild. On 22 October 2026 the user confirmed that the installed sleep update
was working. This is user-reported retail playtest evidence for the observed
behavior, not proof that every NPC and lifecycle case below has been exercised.
Other adapters' added/preserved reporting may change on repeat;
the sleep report itself is stable.

Eighteen focused tests cover circular averaging, authored-clock precedence,
stable variation, guard cohorts, midnight boundaries, home preference, public
fallback bounds, private geometry, shared beds, quest/work preservation,
missing beds, repeat application, corrupt graph rejection and later work
upgrades retaining the sleep extension. The repository
suite passed 1,731 tests with 17 skipped on rerun. The preceding run hit a
Windows file-lock error while an unrelated shader-cancellation test cleaned up
its temporary `compile.log`; the sleep tests passed in both runs. The local setup executable at
`outputs/sleep-setup/KingdomComeGlueMapper-Setup-0.3.16-win64.exe` passed its
frozen self-test. This is a local build, not a published release.

The implementation validates KCD2's exported native bed reservation, stance,
sleeping context and periodic behavior. Exhaustive wake-up, interruption
cleanup, crowding and save/load checks remain pending. Source clothing changes,
locking doors and full household routines are outside this extension.

## Retail acceptance

1. Install the staged overlay over its recorded baseline using the normal
   transactional installer, with the game closed and rollback retained.
2. Observe a worker approach their linked home bed during their sleep window,
   enter the lying animation and leave for their existing work when it ends.
3. Observe a homeless worker or a worker with an unlinked home bed use an
   available public fallback. Check navigation and animation clearance.
4. Occupy the preferred bed and confirm no double occupation or endless
   reservation retry occurs; check an alternative candidate.
5. Check two guard cohorts at night and during the day. At least one cohort
   should remain available for its pre-existing duty schedule.
6. Interrupt sleep through dialogue and combat; verify the NPC gets up,
   releases the bed and responds normally. Check quest priority too.
7. Save/reload and leave/return during sleep. Inspect logs for new state-search,
   reservation, pathing or animation-queue errors.

Generated reports retain `runtime_verified: false` for newly produced outputs;
the confirmed playtest applies to the installed stage identified above.

Both clean builds and existing-package upgrades run the same population
conversion through setup recipe 48. The frozen setup includes all four sleep
modules. It applies to every eligible person in the selected source profiles,
with no 55-person cap or named-NPC exceptions. Later job upgrades can replace
an importer-owned idle daytime activity while retaining the sleep extension.
