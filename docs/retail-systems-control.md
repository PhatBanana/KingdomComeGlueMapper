# Retail world entry comparison

The optional `fritz_systems_control` package tests a small world in the retail
game through two entry paths. It is added to the existing single
`kingdomcomegluemapper` mod, preserving the Rattay destination and native
Kuttenberg dialogue. The new coach option is **Travel to Test world**.

Fritz uses the imported KCD1 identity and appearance with the native KCD2
bandit records from the successful Trosky clone test. The standalone editor
player has been replaced with the native retail shared player registration.

The control retains the full native Barbora project and its saved-state paths,
including open-world, horse and profession systems. Its 50 immediate
open-world systems depend on 2,353 graph files, checked against the installed
retail files. Native linked services and prefab ports are resolved from editor
source. The authored source contains 223 native objects plus local homes,
Fritz, entry and navigation objects; prefab instances expand during export.
Native source coordinates are replaced by small local fixtures on flat terrain.
Story schedules are not run in this control. This is not a claim that every
native story quest, regional activity or gameplay dependency has been verified.

## Build evidence

Build source: `outputs/BuildWork/fritz-systems-control-retail`.
The official Sandbox/RC pipeline exports physics, navigation, scheduler,
prefab services and animation helpers. A documented package step adds the
custom Level's `ConceptModules` registration, omitted by the editor export.
Both entry methods use that same packaged level without runtime repair scripts.

The revised export no longer reports residents sharing a home area or private
areas lacking a home binding. Other editor diagnostics remain, including
shader-cache CRC mismatches and missing native animation GUIDs. These have
not been established as the combat failure's cause. File validation alone is
not a gameplay result.

Two outfit/item IDs in the older isolated Fritz package conflicted with the
existing KCD1 bandit clone. The control gives those cloned records independent
IDs and rewrites their references. Existing outfit rows are preserved.

## Live protocol

1. Launch retail KCD2 with `-devmode`, load the existing **pre-travel Trosky
   save**, and note inventory, equipment, perks and current health.
2. Talk to the Trosky coachman and choose **Travel to Test world**. Fritz is
   placed 30 metres from the arrival point, on the flat ground. Check his
   appearance and your inventory/perks before combat.
3. In the console, run `exec gm_combat_log_start.cfg`. Test attack exchanges,
   blocking, disengaging/re-engaging, and surrender/mercy prompts when they
   occur. Record any lock and whether either participant can still attack.
4. Preserve `kcd.log` and the RPG event log before the next run.
5. Reload the **same pre-travel Trosky save**. Bypass the coach route using:

   ```text
   map fritz_systems_control
   ```

6. Check the player profile again and repeat the combat sequence. A direct
   `map` command may recreate the player or reset campaign state. If inventory
   or perks differ, this is a different initial-state test, not proof that the
   coach is faulty. Do not disable Warmonger or force hostility to make it pass.

The launcher `tools/launch_retail_control.ps1` defaults to the normal retail
menu. `-Mode Direct` starts the same level immediately for a separate fresh
startup comparison. It checks the installed level hash and preserves the
previous game log on D:. It does not alter saves or enable invulnerability.

Reload the Trosky save to leave the test world; no return coach is authored in
this test fixture.

## Retail failures and packing correction (2026-10-11)

Both retail entry paths loaded the control, then crashed. Coach entry failed
while approaching with a sword; direct startup failed while looking around.
The two dumps have different exception locations in WHGame.dll:

- Coach entry: RVA `0x4295ae`, invalid pointer read. The enclosing function
  references `[CCompiledRenderObject] Compile failed, PSO creation failed`.
- Direct startup: RVA `0x4a60c4`, null write. Candidate return addresses in the
  captured stack lead through renderer code referencing compiled objects and
  compute skinning. This is a bounded disassembly/stack inspection without
  engine symbols, not a fully symbolized crash diagnosis.

Neither report indicates GPU device removal. These crashes do not establish
that a combat service or the coach transfer is the cause. Evidence is retained
under `crash-approach-sword` and `crash-direct` in the build output.

The package adapter previously rewrote all 33 level entries as ZIP_STORED to
change only `whdata_0`. The official export contains 24 deflated and nine
stored entries, with native local headers, extra fields and entry offsets.
The adapter now preserves every untouched local record at its exact original
offset and appends only replacements. The central directory lists each path
once. The obsolete replaced local record is unreferenced. Fresh level builds
start from the official export, so obsolete records do not accumulate there.

Tests cover compressed bytes/header preservation, offsets, metadata, CRCs and
unique active replacements. This fixes the unnecessary archive transformation;
whether it fixes the retail crashes still requires a live result. No NPC,
appearance, brain, world service or combat setting was changed for this test.

### Follow-up: own-body crash and exact export comparison

The packing-preserving build also crashed when the user looked at Henry's
own body. The report again identifies WHGame `004285ae` (PE RVA `0x4295ae`),
matching the earlier compiled-render-object fault. Packing preservation did
not resolve the crash. Evidence: `crash-own-body` in the build output.

The current editor export versus the generated retail level has only one
decoded entry difference: `whdata_0` gains the control ConceptModules entry.
The other 32 level entries retain their native packed records; terrain.pak
and recast.pak are whole-file identical. Generated and installed copies of
all three archives are whole-file identical.

The earlier working editor control is a different baseline:

| Aspect | Earlier editor control | Current systems control |
| --- | --- | --- |
| Runtime entities | 14 | 1,392 |
| Player | Local Dude with explicit StaticData, body, head, hair and beard | Native retail SharedSoulGuid, without local StaticData |
| Concept project | None listed | Native Barbora plus custom Level |
| Loaded mod | Isolated Fritz package, 601 entries | Full GlueMapper, world resources, bridge and control assets |
| Global player script | Native | Native script plus horse arrival hooks |
| Engine | Community tools build | Retail executable |

The installed player.lua base matches retail exactly; the difference is an
appended horse recovery observer wrapping OnInit and OnLoadAI. It does not
replace body-rendering functions. Its placement action is limited to
kcd1_travel, but observations/timers also run in the control. This is a real
environment difference, not evidence that this hook caused the crash.

The earlier and current leveldata.xml render/environment settings match;
the semantic differences are level name and one added collision class.
The broader level differences include entities, scheduler, links, physics,
navigation and terrain data. Therefore the earlier successful editor combat
test was not a matched retail test of the currently crashing player setup.
Compare player initialization and the mod environment before treating any
further failure as proof of a missing AI system.
