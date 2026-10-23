# Source work speech coverage

`campaign_work_speech.requests` finds executable monologue requests in a selected
source behavior tree, excluding editor metadata. It records the original speaker,
message completion contract, enclosing gates, and loops. It does not turn quest
barks into random town conversations or invent polling intervals.

Call `assess(request, dialogue_model)` when reporting a partially converted job,
or `require_supported` before enabling its speech. A registered dialogue alone
does not establish that its repetition semantics survived conversion. These checks
currently reject nonzero source sequence timeouts and unresolved sequence flags.
The ordinary dialogue exporter does not lower either of those fields as an ambient
repetition contract. Additional actor, recording, activation, cancellation and
dialogue-effect validation is still required even when this check passes.

The installed KCD1 `final/so_pub_table_2.xml:wiping` requests `bartender_wiping`
repeatedly while its table-cleaning animation runs, inside the detailed-LOD path.
Its connected source topics are 21967 and 28046. The entry has timeout 120;
the nine terminal variants have timeout 900 and flags 1. The native game has
dialogue `Cooldown` and `CooldownTimeType` fields, but the source timeout units,
clock and flag interpretation have not been established. Consequently the wiping
animation may be converted independently, while this speech remains explicitly
pending. Enabling its loop with zero cooldown would not preserve the source.

A further read-only audit located the source `C_FunctionIsSequenceAvailable`
runtime check. It compares a signed 64-bit elapsed clock with the sequence's
runtime duration, including a negative-duration sentinel and an enabled flag.
The table-to-runtime duration conversion and the meanings of the nonzero source
flags remain unresolved. Different callers also obtain their clocks through
different fields. This evidence does not justify treating the source timeout as
milliseconds, seconds or game time. The unsupported branches therefore remain
disabled; the verified zero-timeout/zero-flag market branches below are separate.

Regression coverage: `tests/test_campaign_work_speech.py` checks executable-only
discovery, source-scope retention, cooldown/flag rejection, speaker/alias ambiguity,
and the distinction between a supported request and runtime verification.

`lower_request` now emits the actual native mailbox leaf for supported imports.
It requires a verified native `monologRequestRead`/`monologRequestExecution`
consumer, exactly one registered native `Dialog` alias, and a complete importer
validation record bound to hashes of both the source model and native document.
The record must certify conditions/effects and participant/recording/activation
validation, with no pending work. It retains synchronous `OnProcessed` waiting
or the source's explicit instant operation. Its caller must retain source work
gates and cancellation; this API does not schedule new conversations by itself.

Further retail inspection found `inspection_walk_architect` (17 sequences) and
`event_pillory_crier` (five sequences) with zero timeouts and flags. Their source
placements belong to the monastery and Rattay, respectively, so they are not
activated as invented Skalitz jobs. Sweeping, shop calls, begging and camp barks
instead select source metaroles. KCD2's native speech consumer accepts metaroles,
but name presence in `rpg/metarole.xml` alone does not establish registered
dialogue, source speaker selection or recordings. For example,
`ZAMETANI_OBECNE_ZENA` is defined in the native table without a corresponding
reference in the native scripts archive. Sweeping's source 10-second GameTime
request loop is known; its metarole-to-dialogue registration is still required.

Remaining prerequisites before enabling that slice are source actor/metarole
resolution, connected native dialogue and recordings, preserved source selection
conditions/effects, verified nonzero timeout units and clock where used, and
native activation/cancellation inside the existing job. No new hourly loop or
default cooldown is substituted for these contracts.

## Source metarole registration stage

`campaign_work_metaroles` now resolves source soul/role/metarole/topic memberships,
excludes source test branches and unregistered actors, and registers isolated
native roles/metaroles through Storm. Shared recordings are selected by the
actor's original `rpg/v_soul_character_data.voice_id`; the first available voice
is never substituted. Type-4 source branches require explicit proof of source
`dialog:monologRequest` dispatch, matching participants and native in-game
monologue mode. Other type-4 branches remain rejected by the general exporter.

Actual installed actors include five `MERCHANT_VYVOLAVANI` members. Topics 26093
and 26219 retain unresolved nonzero timeouts. Topics 26856 and 26857 have zero
timeouts/flags and source conditions/effects supported by the existing emitter.
`setup_work_speech.upgrade` now registers these for the three matching compiled
market workers, with actor-specific roles, original voice selection, English
recordings/subtitles and the available source facial tracks. Missing source facial
tracks are listed explicitly; their original audio is retained.

This uses the project's established native market-service adaptation. It clones
`profession/seller/so_seller.xml:seller_market`, changing only the requested
metarole. The native movement, `seller_disableMarketCries` guard, RandomGate,
blocking monologue function, LOD handling, service contexts, 15-second GameTime
wait, cancellation and priorities are retained. It does not claim the original
KCD1 idleState=3/approach/semaphore cadence; it uses the already adopted native
seller cadence. Eligibility is tied to the actual actor-owned compiled seller
schedule and original source merchant metarole membership.

The native `dontPlayDialogAnimations` lane retains the job's pose. Source ADLG
gestures are explicitly omitted as a presentation adaptation. Command 8 is not
silently omitted: static inspection of the KCD1 retail command factory proves it
constructs `C_CommandHearing`. Source `dialogue_hearing` maps merchant int_param=5
to bark50; the converted response uses native HearingOverride=50. The converter
requires the source range table and a same-range native dialogue example, and
rejects delayed/targeted or unsupported hearing values. Static proof records DLL
hash, factory/RTTI addresses, not any redistributed binary bytes, in
`docs/work-command8-proof.json`.

The saved-package receipt validates private resources and owned bindings, rather
than treating unrelated changes to the shared mission, entry graph or Storm index
as corruption. All package rewrites use replacement files so resuming a build
never edits the previous package through its hardlinks. Static/package validation
is not live playback verification; reports retain `runtime_verified: false`.
