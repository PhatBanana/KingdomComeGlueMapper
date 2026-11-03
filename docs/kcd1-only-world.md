# KCD1-only world: KCD2 small talk left out

Status: implemented in `tools/world_gameplay_basis.py`; **not tested in game**.

Converted KCD1 NPCs should speak KCD1 lines only and stay silent where KCD1 had no line (Sean,
2026-11-02). KCD2's native open-world modules are instantiated in the imported world, and their
lines play in whatever voice the speaker has. Many KCD1 voice codes are the same actors as KCD2's,
so converted NPCs spoke hundreds to thousands of KCD2-only lines each.

## The split
`WORLD_GROUPS` lists every native module the world could instantiate, each with a keep or drop
decision and a reason. `SYSTEMS` (kept) and `DROPPED` are derived from it, so the maintainer can
adjust a single row.

| Group | Decision | Reason |
| --- | --- | --- |
| combat, boj_a_zraneni, battle_barks | keep | fight barks, kept as filler (Sean: "Keep fight barks") |
| punishment_barks (+ nextnextgenpunishment, utils punishment via the crime wrapper) | keep | crime system: fines and arrests |
| shop, repair, sharpening | keep | trade and services |
| perky, statistical_perks, requestplayerholsterweapon, generic_action_prompts | keep | perks and prompts |
| reakce_na_stav_hrace | drop | reactions to Henry's state |
| reputace | drop | reputation remarks |
| spanek_npc | drop | sleep mutters |
| pozdravy_a_rozlouceni_mezi_npc | drop | NPC-to-NPC greetings and goodbyes |
| pozdravy_na_zacatku_dialogu | drop | greetings at dialogue start |
| rozlouceni_na_konci_dialogu | drop | goodbyes at dialogue end |
| reakce_pratelskych_nepratel | drop | friendly-enemy reactions |

A dropped group is not instantiated, so its lines are never requested. Its recordings are not relocated
(`world_speech_audio` follows the packaged graphs), and its facial tracks are not indexed
(`world_speech_facials` follows the audio plan).

## Packages built before this change
`finalize` refuses a package whose world controller still registers a dropped group ("rebuild the
package"). The crime and speech receipts hash the old controller, so an in-place removal would leave
them out of step. Rebuild instead. Recipe 66 -> 67.

## Shop flavour
`SHOP_FLAVOUR` lists the KCD2 small talk inside the kept `shop` module, each row with its reason:
- the welcome on entering a shop (`privitani_v_obchode__muz/__zena`);
- the keeper's gossip with a customer and with a guard;
- the KCD2 stall cries (`vyvolavani_obchodniku_na_trhu`).

`cut_shop_flavour` removes them and every node fed only by them, applied repeatedly: 20 condition nodes
(angriness, charisma, time and state, `math::boolean`). It refuses rather than reach a kept sub-dialogue or a
node with side effects.

The cut runs where `package_dependencies` copies retail `shop.xml`, so the crime wrapper's repackaging gets
it too. It keeps the talk-start greeting, the buy dialogues, haggling and negotiation, and the shop ending
(farewells, after-repair lines, a reward).

The ported KCD1 shop conversation (voice-lines branch) carries its own graphs and utils closure, and does not
depend on any of the cut sub-dialogues; reviewed by that branch.

## Measured (dry run on a staged copy of the installed recipe-71 package)
| Measure | Before | After |
| --- | --- | --- |
| Relocated KCD2 world recordings | 64,670 | 46,148 |
| Of those with a native facial track | 61,942 | 44,165 |
| Referenced responses (groups only) | 8,923 | 5,609 |

Removed by group:
- shop flavour 5,304;
- reactions to Henry 3,282;
- dialogue-start greetings 3,122;
- NPC greetings 2,448;
- sleep 1,182;
- dialogue-end goodbyes 1,115;
- reputation 1,058;
- friendly-enemy reactions 1,011.

Repackaging the world controller twice gives identical graphs (360, all dependency scopes validated).

The package gate's known facial gap shrinks to 1,983 untracked open-world lines (from 2,728).

## In game (not yet checked)
- **Goes quiet:**
  - converted NPCs greeting each other or Henry in passing;
  - "Greetings"/"Farewell" lines around a conversation;
  - remarks about Henry's clothes, blood, weapon or crouching;
  - sleep mutters and reputation remarks;
  - shop welcomes on entering, merchant gossip, and KCD2 stall cries.
- **Must still play:**
  - trade, buying and haggling for every keeper; KCD2's shop greeting and farewell for the three
    keepers outside the KCD1 shop port (rato_innkeeper1, rat_pesek, neu_zdena);
  - repair end lines and reward;
  - ported KCD1 shop talk and haggling;
  - Blanka's KCD1 dialogue;
  - the KCD1 market cries;
  - KCD1 quest dialogue;
  - guards' fines and arrests;
  - surrender and flee;
  - fight barks.

## Not done here
The three keepers outside the KCD1 shop port keep KCD2's shop greeting and farewell. That's their only
shop speech; whether those go too is a KCD1-fidelity decision.
