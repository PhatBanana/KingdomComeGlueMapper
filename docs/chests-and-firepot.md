# Skalitz chests and the hearth fire (recipe 71)

**Not tested in game.** Everything below is offline evidence: KCD1 and KCD2 level data,
both games' entity scripts, asset-free unit tests and dry runs against the installed
package in a fresh folder. The acceptance steps at the end are still open.

## Symptoms (Skalitz, 2026-10-29 play session on main 47f031a)

1. At game hour 1.07 "chests still show locked".
2. At 820,3487 the burning log fire sat on the stone ledge beside and above the cooking
   pit, while the pit under the iron grate only had embers.
3. A world survey (`tools-local/world_survey.py --town skalitz`, 30 Oct) flagged 68 fire
   pieces more than 0.25 m from their nearest KCD1 piece.

## Chests: locked exactly where KCD1 locked them

KCD2's `Stash:Reset` (`Scripts/Entities/WH/Stash/AnimStash.lua`) locks a chest at spawn
only when `Properties.Lock.bLocked` is set; difficulty and fanciness are generated from the
model when their override flags are false but never lock anything. `ordinary_containers`
copies `bLocked`, `bCanLockPick` and the key item from the authored KCD1 Stash and derives
the difficulty from the same model table KCD1's `GenerateLockDifficulty` used.

Comparing every converted `gm_container_<id>` with its KCD1 source over the whole map:
2769 containers, 937 locked, 0 lock-flag or key mismatches. In the Skalitz box
(x 600-950, y 3330-3600): 149 converted containers, 36 locked, every one of them
`bLocked="1"` in KCD1's own `sv_state0` layers. The keys those chests take
(`vk_key_ska_skasahome*_chests`) are carried by the house owners in KCD1
(`ska_fatherOfHenry`/`ska_motherOfHenry` for the forge chest, `ska_jan`, `ska_zbysek`,
`ska_maruna`, `ska_merchant4` for home 14), not by the player, and KCD1 Henry has no
lockpicking in the prologue. The chests the player sees locked were locked in KCD1 too.

No converter change. `tools/container_lock_audit.py` (read-only) reports lock and key
mismatches and lists a region's containers with both states; it is not part of
finalization because it changes nothing. Report:
`D:\KCD\Builds\glue\diag\chests-firepot-20261030\audit-installed\container-lock-audit.json`.

## Hearth: the generated cluster was placed from the Trosky donor, not from KCD1

`cooking_pots.convert` rebuilds each KCD1 fireplace from a native Trosky donor cluster
(fireplace smart object, kettle trigger, cook trigger, ladle, fire, steam and cauldron
prefabs). It moved kettle, cauldron, steam and ladle onto the authored KCD1 pot trigger
and pinned the fire prefab (`fireplace_off1_prc`, phase pair 26e2bbda/25bff32e, a
`fireplace_wood_c` log pile with the flame emitter 0.287 m above its pivot) to the KCD1
flame origin. Everything else kept its donor-relative offset.

Two things were wrong with that:

- KCD1 fire prefabs (`prefabs/fires.xml`) are flame and light only. The inset black-kitchen
  hearths (`Fires.Fireplaces.Inset_house_fireplace`, 19 map-wide, 2 in Skalitz) put the
  flame origin 0.15 m above the pot trigger and 0.11 m above the pot item that rests on the
  hob. At 821,3488 the hob plates and grates are at z 52.09, the ash in the pits at 51.98,
  the KCD1 pot item at 52.088 and the flame origin at 52.199, so the native log pile floated
  0.11 m above the plate between the two grates against the back wall. Corner hearths
  (166) put the origin 4 mm below the pot item and camp fires 0.2 m below the pot trigger,
  which is why only the inset hearths looked wrong.
- The native cook-on-fire trigger (`kettleTrigger['pan']`, a `FoodProcessingTrigger` with
  the `@ui_cook_item` / `@ui_use_fire` prompts) stayed donor-relative: 0.57 m from the
  authored KCD1 `st_fire` trigger at corner hearths, 1.43 m (and 1.11 m higher) at the
  inset hearths, 0.75 m at camp fires. KCD1 players cooked at the `st_fire` trigger.

The fire's x/y never moved: the converted pivot equals the KCD1 origin bit for bit, so the
"1.5 to 2 m" in the session notes is the player's distance to the hearth, not an offset.

### Change

`cooking_pots.cluster_placements(owner, pot, entities)` is the one rule for both paths:

- kettle, cauldron, steam, ladle: the authored KCD1 pot trigger (unchanged);
- cook trigger: the KCD1 `st_fire` trigger's position (all 303 fireplaces link one);
  rotation keeps the donor yaw, since both games' triggers are omnidirectional;
- fire: KCD1 flame origin x/y, z lowered to the resting height of the fireplace's pot item
  (category `Kotlik`, 205 home hearths; camps have none and fall back to the pot trigger)
  when the origin is more than 1 cm above it, never raised.

`cooking_pots.convert` applies it on clean builds. `tools/hearth_fire_placement.py`
applies the same rule to a built package in `setup_package_upgrade.finalize`, on the
completed-package fast path and the full path, receipt key `hearth_fire_placement`
(version, rule, moved entities with before/after positions, counts), with a `stage()` dry
run. Recipe 66 -> 71; `desktop_setup` inventory lists both new modules.

### What moves

Staged from the installed recipe-70 package (fresh folder, mod untouched): 317 entities
map-wide, 14 log piles (all inset hearths, lowered 0.04-0.15 m) and 303 cook triggers.
In Skalitz, 17:

| Entity | Role | Before | After | m |
|---|---|---|---|---|
| gm_cooking_101489_24043 | fire | 821.210,3487.766,52.199 | 821.210,3487.766,52.088 | 0.11 |
| gm_cooking_101489_24046 | cook trigger | 820.430,3487.201,53.160 | 821.304,3486.989,52.047 | 1.43 |
| gm_cooking_101618_24043 | fire | 797.256,3517.596,53.032 | 797.256,3517.596,52.921 | 0.11 |
| gm_cooking_101618_24046 | cook trigger | 798.083,3518.091,53.993 | 797.231,3518.379,52.880 | 1.43 |
| gm_cooking_37699_16226, 103182_16226 | camp cook trigger | 0.74-0.75 m off, 0.09-0.12 m high | on the KCD1 fire trigger under the pot | 0.75 |
| 11 corner-hearth cook triggers (101472, 101642, 101763, 101854, 101949, 101988, 102048, 102351, 102397, 102611, 102593) | cook trigger | 0.57 m off, 0.25 m high (102593: 2.3 m) | on the KCD1 fire trigger | 0.57-2.3 |

Full list: `D:\KCD\Builds\glue\diag\chests-firepot-20261030\stage-r70\report.json`.

### Survey before and after

`world_survey.py --town skalitz` on the installed recipe-70 package: 68 fire pieces flagged.
On the staged copy: 54. The 14 cleared are the 14 cook triggers that the survey could pair
with their KCD1 counterpart. The 54 left are not misplacements:

- 13 kettle triggers, 13 cauldrons (`kettle_a_standing`, template f39cd738) and 13 steam
  tag points (ce0ee77c) stand on or within 0.04 m of the KCD1 pot trigger; the survey pairs
  them with the KCD1 fire trigger 0.5 m away because the pot trigger is not in its fire
  category. 2 camp steam points sit 0.28 m above the pot trigger by the donor's offset.
- 2 inset cook triggers now stand on their KCD1 trigger, which KCD1 named
  `sequenceTrigger_ohen`; "ohen" is not in the survey's fire regex, so it pairs them with
  the nearest fire-named object (a spark particle).
- 8 lamp and candle pieces (`gm_fire_light_103067_*`, `_103209_*`) sit at the offsets the
  KCD1 prefabs give them (the `Lamp_tavern` candles hang 0.48-0.76 m below the prefab
  origin, the `Candles_three` light 0.26 m above); KCD1 instantiated the same prefab at the
  same origin, so the positions equal KCD1's. The survey measures against the origin.
- 3 `gm_fire_light_loft_table_*` are new candles from `feat/loft-navmesh`.

Table with every pair: `D:\KCD\Builds\glue\diag\chests-firepot-20261030\survey-before-after.md`.

## Validation

- `tests/test_cooking_pots.py`: camp fire keeps its origin and donor cook trigger when the
  source has no `st_fire`; inset hearth fire rests on the pot item and the cook trigger
  stands on `st_fire` with the donor yaw; `fire_pivot` never raises and ignores sub-centimetre
  floats. `tests/test_hearth_fire_placement.py`: both roles, second pass changes nothing,
  displaced fires are normalised to the rule, missing `st_fire` keeps the donor trigger,
  unconverted pots reported, missing links fail, stage/upgrade archive round trip.
  `tests/test_container_lock_audit.py`: real mismatches only, region listing.
  `tests/test_setup_package_upgrade.py` asserts the step runs with package and source on
  both paths.
- Full suite: 2315 tests, 0 failures, 19 skipped, the same 9 environment errors (missing
  `webview`/`numba`, parallel bake worker) as the untouched 47f031a worktree (2304 tests).
- Dry runs: recipe-66 installed package, 14 fires lowered, second pass 0; recipe-70 installed
  package staged to a fresh folder, 317 moved, second pass 0 (`stage-r70`, `stage-r70-pass2`).
  The installed mod was only read.

## Limits

- Nothing seen in game. Whether the log pile resting on the hob between the grates reads
  right, and whether the cook prompt at the KCD1 spot (0.4 m beside the pot on the inset
  hearth, directly under the hanging pot at camps, as in KCD1) competes with the eat prompt,
  only a play session shows.
- The log pile is still a KCD2 addition at the KCD1 flame spot. On the inset hearth the
  hob between the back wall and the pot is about 0.4 m deep and the pile is about 0.5 m
  across, so no horizontal shift fits it; a flame-only fire would need a mod-local prefab
  pair registered in `prefab_phase` as its own category, which needs an in-game check.
- Kettle, cauldron, steam and ladle yaw stay donor-relative. The KCD1 pot item and the
  native cauldron both exist at the pot anchor, and the KCD1 ladle slot category
  `Naberacka` is not matched by the ladle replacement; both are visible duplicates at this
  hearth and separate work.
- The lamp and candle lights are placed as KCD1 placed them; the survey's reference point
  is the prefab origin.

## Retail acceptance

1. Build or upgrade with recipe 71 and start in Skalitz.
2. Chests, by day and after 21:00: the forge chest at 737.7,3411.2 and the house chests at
   790.6,3506.1 and 815.4,3473.4 show the lock prompt (locked in KCD1 too); the forge
   chests at 732.6,3419.3 and in the loft open freely.
3. Stand at 819.9,3487.4 facing about 72 degrees east of north, look down at the hearth:
   the burning logs rest on the hob plate between the two grates, no gap under the pile,
   flames above them; the cook prompt appears over the hob at 821.3,3487.0 beside the pot,
   the eat prompt at the pot.
4. Repeat at the second inset hearth (797.3,3517.6) and at a corner hearth (825.0,3492.2,
   unchanged fire, cook prompt moved 0.57 m onto the hearth).
5. Camp fire at 727.1,3410.4: cook and eat prompts both at the pot, logs on the ground.
6. Save, reload, repeat 3.
