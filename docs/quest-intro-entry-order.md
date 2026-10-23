# Source introduction timing audit

The introductory worker has two different source locations: its guarded
first-entry placement and its later sitting destination. The compiled scheduler
has a delegate at the seat. Whether positioning before worker initialization
contributes to the reported delay still needs runtime evidence.

A proposed change moving that delegate to the source entry marker was withdrawn.
The source worker's persistent phase guard skips relocation on subsequent entry;
a static delegate would not express that guard and could send the actor back to
the arrival location on every reacquisition. No verified native contract was
found that makes this a safe first-entry-only migration. No timing or positioning
code change from this audit is retained.

For the installed Vanyek introduction, the current delegate is at the source
`vanekSitting` pose, while the source initializer uses `vanekTeleport`. The proposed
migration was exercised in memory only and never installed. Passing migration
tests alone did not establish source-equivalent runtime behavior.

The reported appearance at noon is **not established as a clock cutoff** by this
audit. Installed intro, departure, and lesson activities all allow 00:00–24:00.
Intro activation depends on the started parent quest, started practice objective,
and pending/not-departed state. The temporary faction also depends on the parent
quest, not the time. The native fallback `schedulerWait` waits ten game seconds,
not two hours. The opening clock uses `AdvanceWorldTime(TimeOfDay=10h00m)` once;
no arbitrary time override, periodic retry, or new teleport was added.

A fresh-game observation of the actual quest and worker states is needed to
establish the cause of the noon observation. The existing persistent source
initialization remains unchanged.

## Competing activity audit

The installed `vra_vanek` entity (`713eaac2-427f-4c31`, compiled scheduler ID
`5490242535869557442`) has exactly six compiled activity links:

| Activity | Priority | Availability |
| --- | --- | --- |
| schedulerWait | 0 | 00:00–24:00 |
| intro | 55 | 00:00–24:00 |
| departure | 55 | 00:00–24:00 |
| sleep hub | 2 | 00:00–06:19 |
| sleep hub | 2 | 20:47–24:00 |
| lesson | 55 | 00:00–24:00 |

The sleep hub's ten bed destinations have the same two night windows and no
daytime links. Every actor link has zero time variation. There is no authored
competing job ending at noon in this installed scheduler graph.

The imported soul uses native `npc_basic` and has no legacy activity/time
fields. Its Storm roles rule adds only its unique imported-person role. The
native brain's `npc_basic_scheduler` and `npc_basic_switch` subbrains both have
timeout zero. The original KCD1 `vra_vanek` soul contains just `activity_0=work`,
`time_0=0:00`; its other eight schedule entries are empty.

This audit examined installed package data, not a running game's serialized AI
state. No KingdomCome game process was running during the bounded log check.
The ordinary installation-root log was stale. Following `setup_launch.py` into
`runtime/launch_with_shaders.ps1` located the actual log under
`Mods/.kingdomcomegluemapper-runtime/kcd.log` (23 October, 16:57:08; 49,137 bytes).
It records `Requesting native New Game for level 1001`, loads `kcd1_travel`, later
loads `SkipTime.gfx`, and exits through `WM_CLOSE` with code zero. Thus the latest
recorded session was a New Game, but this retail log has no Vanyek, swordOne,
or GlueMapper intro diagnostic entries and cannot establish worker ownership
at the reported 10:00–12:00 transition. No launch helper was executed to inspect it.

## Independent faction, seat and scheduler audits

The controller and the source worker both select `Civilians`. The generated
`TemporaryFactionEffect` targets the correct imported SoulAsset, which resolves
through the project entity and waiting links to Vanyek. Its native faction is
registered in the imported faction tree. Its lifetime follows the started parent
quest; this path contains no asynchronous faction-transfer acknowledgement or
authored delay. These are package checks, not confirmation of the actor's actual
runtime faction.

The source marker's name suggests a table seat, but its authored helper class is
`sitGround`. The exported native `so_sitPlace` has the exclusive `use` resource,
and the registered `Sit_1Place_Ground_Var1` collection contains both sit-down and
stand-up transitions. The native monologue handler already preserves the
user-controlled animation. A missing table-standing animation is therefore not
demonstrated by the source or destination assets. No rendered animation or brush
collision result is claimed by this audit.

The native scheduler debugger, `Libs/CryHttp/static/scheduler.html`, displays
"failed previously" for the `OneTimeUse` result even when the link itself is not
one-time-use. This establishes that failed-activity suppression is a real engine
state. It does not establish its reset interval, whether time skipping resets it,
or whether this particular actor entered it.

The scheduler is native `npc_basic_scheduler`, registered as subbrain type 9.
No exposed execution wrapper establishes that `PositioningDelegate` requires
travel before the worker's `OnInit`. The different entry and seat poses are not
sufficient evidence for removing or relocating that delegate.

Likewise, the absence of a `StreamableTarget` entry for the imported actor is not
a demonstrated defect: native mission NPC, SmartObjectHolder, TagPoint and
CutsceneHolder asset links use the same non-streamable mission-entity pattern.

## Remaining evidence boundary

The initial, uninstrumented retail log could not distinguish a worker that never acquired its
activity from one that entered and failed while calling the seat. Existing
`LogToConsole` messages at Info level did not appear in that log. No fix should
invent a two-hour timer or change faction, positioning or urgency to conceal
this uncertainty.

An opt-in worker trace can record initialization, source placement, seat entry,
worker success/failure and seat exit, including actual position and available faction fields, using the
native AI Lua callback contract and retail-visible `System.LogAlways`. It must
preserve the original child outcomes, protect diagnostic calls, bound output,
and write a separate package. Worker tracing alone cannot establish when the
Skald eligibility expression changes; graph-to-retail logging still requires
separate verification.

The implemented helper is `tools/trace_campaign_intro.py`. It reads the selected
worker from `quest-introductions.json`, rejects a worker that differs from the
current emitter, and validates the instrumented XML against native AI schemas.
It preserves the original seat call and result callbacks; `seat_exit` alone does
not mean success. Each event is bounded to eight messages per loaded entity, with
independently protected position, faction, world-time and world-hour getters.
Both `ExecuteLua` and NPC `LuaWrapper` now use native `entity` context. Earlier
trace versions used the horse wrapper's `data.this.id` resolver; failure of that
lookup could silently suppress wrapper events. Missing context now emits a
bounded fallback event, and getter failures are included in the log. The separate
`soul_faction_id` field uses `entity.soul:GetFactionID()` and is not assumed to
report a temporary faction effect. The builder never updates the input package
or setup recipe.

For this audit, the installed worker was validated and a separate overlay was
built at `D:/BuildKCDMod/intro-trace-20261023`. The eight diagnostic tests and 21
existing introduction tests passed. That initial build preceded the version 2
overlay installation and retail observation described below. Its manifest records the original worker digest, trace
digest, native evidence paths and remaining limitations.

The useful observations on the next bounded run are:

- `initializer_enter` at the opening hour: the activity has reached its worker.
- `first_entry_complete`: the source first-entry nodes have completed; the
  sampled entity transform may not yet reflect the placement.
- `seat_enter` followed by `worker_fail`: a worker failure occurred after seat
  entry; the trace alone does not identify the engine's internal failure cause.
- `seat_exit` without a result callback: the seat call exited or was interrupted;
  this is not evidence of successful sitting.
- No initialization event: check trace loading and activation/acquisition before
  concluding that a timer withheld the worker.

Compare successfully read faction fields with the imported faction registration, and
logged world hour with the user's observation. Do not infer a two-hour retry
policy solely from a failed event and a later successful start.

## Follow-up: arrival was observed after Wait / Skip Time

The user clarified that the noon arrival followed the Wait / Skip Time menu.
This does not establish a noon cutoff or prove that the same delay occurs while
time passes normally. The wait may advance a timed condition, or change native
scheduler/action/LOD execution; the observation alone cannot separate them.

The source introduction, generated introduction and native seat all use
`OnInit canSkip="1"` and `Behavior canSkip="1"`. The actual `so_sitPlace.use`
tree contains no explicit fast-forward branch. Other native behaviors do branch
on `IsFastForwarded`: for example `mucirna_vypaleniSemina.CowerGround` returns
success in that mode instead of its ordinary `ExactMove`. That example proves
fast-forward execution paths exist, not that this is Vanyek's failure mechanism.

Version 2 of the opt-in trace samples native `IsFastForwarded` at initializer
entry and immediately before the original seat call. Both diagnostic branches
only log and succeed; they do not gate or replace the game behavior. These are
mode samples, not continuous monitoring or a claim that fast-forward always
means the Wait menu. This version was installed for a bounded retail run. Its separate build is
`D:/BuildKCDMod/intro-trace-timeskip-20261023`.

## Observed retail trace and next branch diagnostics

The preserved log is
`D:/BuildKCDMod/intro-trace-timeskip-20261023/retail-evidence/kcd-200729.log`.
It records initializer entry at `world_hour=11.821` (approximately 11:49),
`world_time=128955`, at position `771.134,3381.17,59.6119`. The native mode sample
is `initializer_fast_forward_false`. First-entry and initializer completion
events report the same time and position. Eleven game seconds later,
`worker_success` reports `world_time=128966`, `world_hour=11.8241`, and position
`772.933,3471.14,52.4997`, matching the source arrival marker. No `seat_enter`,
`seat_fast_forward_*`, or `seat_exit` event appears. All faction readings were
`unavailable`; this does not establish a missing faction assignment.

These events establish that this worker initialized and returned success, not
that the actor sat down. The late position update also means a completed
initializer trace marker must not be described as immediate visible placement.
The missing seat mode event used `ExecuteLua`'s already-working entity context;
the old wrapper lookup issue alone cannot explain every absent seat event.
The original `Parallel successMode="Any"` allows a successful branch to end the
worker, so branch-local events are needed before attributing this success to
the seat or the proximity bark gate.

Version 3 adds `body_enter`, `bark_branch_enter`, `bark_branch_success/fail`,
`distance_gate_child_enter`, `dialog_gate_child_enter`, and `seat_branch_enter`
before `EntityContextElement`. A diagnostic `FuseBox StatusPropagation="Child"`
wraps the original bark branch; result callbacks log and retain Success/Fail.
All original child attributes, ordering, callbacks, phase guards and waits can
be recovered exactly by stripping the trace additions in the regression test.
Twelve diagnostic tests pass, including preservation of the new `Initialized`
acknowledgement and custom event set. The context/error-logging repairs and these new
branch traces have not been installed or observed in retail as part of this
audit. They make no production timing, movement, or scheduling changes.

The version 3 overlay was built from the verified recipe 57 private package
`D:/BuildKCDMod/intro-preparation-proof-20261023-v2` into
`D:/BuildKCDMod/intro-trace-branches-20261023`. Its native AI schema validation
passed; the input package was read only. This does not establish retail behavior
of the new preparation guard or branch diagnostics.
