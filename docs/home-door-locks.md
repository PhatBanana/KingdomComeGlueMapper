# Home door links for night locking

`tools/home_door_links.py` ports the authored KCD1 home-to-door links of every
home that `register_person_world` has registered into the native KCD2 contract
that the crime AI uses to find and lock a home's doors. It runs in shared setup
finalization after the forge loft, for clean builds and package upgrades alike,
and repeats byte-identically. Setup recipe 67 adds it.

## Why converted doors never locked

Retail KCD1 decides night locking inside `AnimDoor.lua`: a door with
`esInteriorType="home"` locks outside its keep-open clock whenever an NPC
passes through it, and `bDoLockOnMissingHomeArea` covers doors outside any home
area. KCD2's `AnimDoor.lua` keeps only the per-instance `bLockInside` /
`bLockOutside` rule; the home policy moved to the crime AI, which finds a home's
doors from the owner's scheduler hub through `home_area` and
`crime_door[type($enum:crime_doorKind.*)]` links (`AI/crime/gethomedoors.xml`)
and reads the trespass level from the area label.

`door_locks.convert_properties` drops the interior enum on purpose, writes
`bDoLockOnMissingHomeArea=0` and `bNeverLockByPassingNPC=1`, and the home areas
created by `register_person_world` carry neither labels nor door links. So no
converted door had any rule left that could lock it. Native Trosky confirms the
contract: 250 of its 252 doors are linked from a home area or shop by
`crime_door` / `shopDoor` links, the only two unlinked doors start locked, and
226 doors set `bNeverLockByPassingNPC=0`.

## Conversion

For each registered home whose `TriggerArea` GUID matches a source
`SmartAreaShape` (all quest-state layer variants must agree, otherwise the home
is reported as ambiguous and left alone):

| Source link name | Native link |
| --- | --- |
| `entrance` (also inside composite names) | `crime_door[type($enum:crime_doorKind.entrance)]` |
| `stash_door` | `crime_door[type($enum:crime_doorKind.storage)]` |
| unlabelled link to a converted door | `crime_door[type($enum:crime_doorKind.basic)]` |
| anything else (`sleepoverDoor`, `unlockAfterCrime`, quest places) | reported as skipped |

Links are written on the area entity and in `waitinglinks.xml`. Each linked
door gets `bNeverLockByPassingNPC=0`; its authored keep-unlocked clock
(`fKeepOpenFrom/Until`, usually 07:30-19:30), key, difficulty and initial lock
state are untouched, as is `bDoLockOnMissingHomeArea`.

The area label follows KCD1's own home behaviour tree
(`Libs/AI/final/sa_home.xml`): a home without the `nonprivateHome` script key
defaults to trespass level `personal`, so it becomes `private;personal`;
`nonprivateHome:true` (Henry's forge home, `rat_home31`) and `trespass:none`
get no privacy label. Explicit `trespass:*` levels and court `trespassMode`
values map onto the shared `trespassLevel` enumeration; unknown values fail
instead of guessing. `interior` is not added because the source polygons cover
the yard as well as the house. Ownership links, shops, pubs and doors without a
home remain unchanged.

## Validation and limits

Seven focused tests cover link kinds and labels, the non-private home, repeat
application, disagreeing layer variants, missing source areas, label conflicts,
unsupported trespass values and the archive stage/upgrade path. The setup
finalization tests assert the step runs with the package and source paths.

A dry stage of the 29 October 2026 package (`main` 47f031a) against retail
KCD1 took seven seconds and linked 39 doors in 16 homes: 19 entrance, 15
storage, 5 basic; 15 homes labelled `private;personal`, 2 without a label;
nothing pending or skipped. The 176 other registered homes are generated
wildlife areas with no source counterpart. Fourteen of the homes are in
Skalitz, including the three doors observed unlocked at 01:00 on 29 October
(`gm_door_103243`, `gm_door_103240`, `gm_door_62546`), all entrance doors.

Nothing here has been verified in game. Whether KCD2 locks a linked door at
night by itself, only when its owner passes through, or only once the area is
private, is engine behaviour that only a play session can show. Making a home
`private;personal` also enables native trespass reactions inside it, as KCD1
did. Doors of shops and pubs, the player's own home and NPC `owner` links are
outside this step.

## Retail acceptance

1. Build or upgrade with recipe 67 and start in Skalitz.
2. By day, confirm the three doors above open freely and `IsLocked()` is false.
3. After 21:00, confirm they are locked, that their owners can still pass, and
   that lockpicking and the converted keys still work.
4. Enter a labelled home at night and confirm the trespass bark and reaction
   match KCD1 rather than a crime escalation on entry by day.
5. Check Henry's forge home stays unlabelled and open, then save, reload and
   repeat step 3.
