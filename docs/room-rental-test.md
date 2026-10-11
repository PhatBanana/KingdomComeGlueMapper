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
