# Rattay inn room rental

The normal Python region builder and incremental `build_room_rental_test.py`
now attach KCD2's native rental module to the existing Rattay innkeeper.
Source selection follows the innkeeper's Home link, sleepoverParentHome, and
the room's sleepoverBed, sleepoverStash and sleepoverDoor links. It does not
choose furniture by proximity.

The native options are overnight and permanent rental. The original payment,
eligibility, rental state and morning expiry logic are retained. This is not
an arbitrary number-of-days selector. Trade and dialog_started quest
completion remain in the same innkeeper conversation.

Room: sa_sleepoverRoom_rataje. Bed 53331 at 2905.5439,748.87677,112.4267;
chest 52644; door 53413. The bed keeps its source geometry and receives native
StanceSmartObject/BedTrigger interactions and animation helpers. The door
keeps its source skin and pivot with a matched KCD2 rig, animation contract
and physics. Its previous static duplicate is removed.

The chest retains the existing shared player-storage master. Permanent
static ownership is removed for this chest only; rental state controls its
ownership and lock. Native room service controls the door and waits for the
player to leave before checkout locking. There is no meal entitlement:
the unbound native cooking-pot ownership node is removed.

Native utilities are copied with their transitive dependencies, including
implicit sibling references, and declared once in a common module scope.
Referenced project enum definitions are imported too. No native campaign
project is started by this feature.

## Validation

- Four rental tests, six existing chair/bench tests, twelve travel tests pass.
- XML dependency and dialogue destination checks pass.
- Animated door geometry and weights passed the existing skin converter's
  validation without moving vertices.
- Test package Build04 installed into the KCD2Mod developer client.
- Runtime concept graph deserialization completed; native door CHRPARAMS
  loaded; log reached `Game claims it's ready`.
- No end-to-end rental payment, sleep, chest access, door animation, expiry,
  save/reload, or return-travel interaction is yet confirmed.
- Existing innkeeper leaning animation and horse stable scheduler warnings
  remain; successful graph loading does not establish those are fixed.

Generated evidence: `outputs/RoomRental/Build04/`. Pre-change level and travel
PAKs are backed up under `outputs/RoomRental/Baseline/` on D:.

## In-game acceptance

Talk to the Rattay innkeeper and rent overnight. Verify money changes once,
the original upstairs room opens, the door blocks passage while closed,
and opening/closing animates. Verify bed sit/sleep and shared chest access.
Save/reload while rented; then pass the native morning expiry, leave the
room, and verify entitlement is removed. Repeat with permanent rental and
travel away/back. Confirm Trade and the existing innkeeper quest still work.

## Build05: room-and-board selection stalls

The user reported that selecting room and board did nothing. The live log
confirmed the rental topic was offered and selected, but stopped on Henry's
`muz__henry_chtel_bych_tad_xfqc` spoken response with no audio/timing found;
no payment choice was reached. Placement is a separate issue and was not
changed by this correction.

Imported rental responses now use the immediate, silent response contract
already used by Trade and horse-purchase menus. Native UI prompts, decisions,
conditions, payment sequence types, scripts and rental output triggers are
retained. Rental payment/output sequences additionally log
`GLUE_ROOM_RENTAL sequence=...`. This test exchange is intentionally unvoiced;
the original cinematic speech still needs a complete voice/timing mapping.

Five rental tests pass, including preservation of both payment choices and
their rental triggers. Build05 is installed and the developer client was
restarted. Successful payment and room access remain unverified until tested.

Build05 live testing subsequently reached `na_stalo` (permanent-rental
payment), confirming progression beyond the original stalled response.
That exposed a leading-semicolon Lua syntax error in the new diagnostic
script. Build06 removes the leading separator, adds a regression assertion,
and is installed with matching package hashes.

## Build06 user validation — 2026-10-12

The user confirmed that buying the room works and requested commit/push.
Their screenshot shows the bed offering Sit and Sleep and save, but the
console reports failed SitDown and LieDown animation requests for the player.
Room purchase is confirmed; successful bed sitting/sleeping is not. Fixing
the bed animation contract is outstanding. Chest use, door operation, expiry,
save/reload and return travel still require explicit interaction validation.

## Build07: bed interaction alignment

Compared the shipped helper definitions: source Bed sittingLeft/Right use
local Y offsets -/+0.48 and rotations 0/180 degrees, while native
Bed_1Place_High uses local X offsets +/-0.48 and rotations +/-90 degrees.
Copying the source furniture rotation directly therefore puts the native
interaction helpers on the wrong sides of the bed.

The builder now derives a rigid alignment from both named sitting helpers,
checks that both agree, and applies it to the bed smart object and its
relative trigger. The shipped definitions yield a -90-degree local Z
correction with effectively zero translation. Furniture geometry is unchanged.
This avoids introducing copied Trosky world-space animation projections.

Three alignment tests and five rental tests pass. Build07 is installed.
On 2026-10-12 the user confirmed that sleeping, sitting, and the door work,
and requested commit/push. Room purchase was confirmed previously.

The same test exposed repeated player switching errors:
`player:switch:switch.xml:root/(N)EnableRoleOnHubDecorator:107` reports
`Hub must be actual scheduler hub.` This is an unresolved scheduler-hub
contract issue, separate from the now-confirmed bed animation alignment.
Other log warnings include the existing innkeeper leaning failure,
gm_neuhof_stable_work schedulerWait target, and empty OSH preset dictionary.
These are not claimed fixed by this change.

## Build08: bed scheduler registration

Native player switching marks the current sitting/lying smart object with
the usedByPlayer role through EnableRoleOnHubDecorator. Build07 omitted the
bed's C_SmartHub scheduler row, although its interactive entity existed.

The builder now clones the donor bed's compiled hub record under the imported
bed GUID, preserving all four sleeper EffectHeal entries. It rejects duplicate
registration and donor activity links needing additional conversion. The test
packer writes identical scheduler tables in level.pak and the mod-qualified
travel PAK path; the normal builder already packages both paths.

Eleven bed/rental tests pass, package copies match, and Build08 is installed.
The developer client has been relaunched. Repeating sit/sleep is still needed
to verify that the reported runtime error no longer occurs. Other existing
innkeeper/stable/OSH warnings are outside this correction.

Build08 user validation (2026-10-12): the user confirmed the scheduler fix works and requested commit/push. Remaining innkeeper leaning and stable-work warnings are the next task.

## Activity contracts: innkeeper leaning and horse-trader waiting

The horse seller's schedulerWait link had been retargeted from sa_land to a
SchedulerHub when the shop was added. SchedulerHub cannot execute that behavior.
The normal builder now inserts the shop hub above the original wait activity,
preserving its smart-area target and positioning delegate. Shop role and native
OpenShop/AddContext lifecycle effects remain on the work route/hub.

The innkeeper's DetailMovementSmartObject was omitted from animation-helper
registration. It now receives the native leaning collection and runtime
validation at its imported position, without reusing Trosky's baked projections.
Registration alone did not fix the first test: the NPC still spawned inside
the pillar. The source LeaningSpot/align helper is 0.242 m along local Y,
whereas the native leaning_right helper is at its object origin. The converter
now derives the helper-transform correction from both installed games'
SmartObjects.xml and starts the NPC at his original KCD1 actor position.

ActivityContracts/Build02 is installed in the developer client. The current
run contains zero LeaningRight_In errors and zero schedulerWait/non-smart-target
errors; the user confirmed it works and requested commit/push on 2026-10-12.
Three new regression tests cover the preserved idle target/delegate, lean
helper registration and authored transform correction. The existing shop,
bed, rental, chair, bench and region-travel tests also pass (34 tests total).

Remaining developer-client diagnostics are not claimed fixed: its Data/Facials
directory is absent and the log reports failure to open the English facial
archive. Retail contains three Facials_english-part*.pak files, with
Animations/FacialAnimations.img in part0. No archive mounting changes were
made during this fix. Loading-progress 'characters' and SqcbLoad thread-config
warnings also remain separate from the repaired activity contracts.

Update, 13 October 2026: the missing facial archives were subsequently mounted
from the local retail installation and the facial warnings cleared in a sampled
restart. See [runtime warning repairs](runtime-warning-repairs.md) for evidence
and remaining diagnostics.
