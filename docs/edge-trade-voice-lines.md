# Trader voices and the map-edge bark

Recipe 70 adds two repeatable finalization steps for native speech that the
standalone project left unanswered. Both were seen on the 29 Oct 2026 build of
`main` 47f031a: `ska_merchant1` at 813,3487 traded without a word, and the
level barrier on the east road near 3930,1827 stopped Henry without his
"turn back" line. **Neither step has been tested in game.** Everything below
is package data, retail data, unit tests and a dry run.

## 1. Imported KCD1 voices fall back to a native voice

### Cause

`dialogue_dubbing.import_source_voices` gives each KCD1 voice that a converted
speaker needs a synthetic KCD2 identity (`voice_id` 100000 + the KCD1 id,
`gm_source_<abbreviation>` in `Libs/Tables/skald/voice__gm_source.xml`) so
the speaker's own converted lines keep their original actor. Native open-world
speech is recorded per native voice and looked up as
`<abbreviation>_<text id>.ogg`. The imported voice `rpro` (KCD1 105, bound to
`ska_merchant1`, `ska_merchant3` and `ska_collierVarlet`) has no native
recording at all: 0 of the 10,348 relocated shop lines, 0 greetings, 0
farewells. `ska_merchant2` is bound to the native voice `bcas` (78, Brian
Caspe, 199 shop lines) and speaks.

Retail handles missing recordings with `fallback_voice_id`. All 91 recorded
retail voices name one; only the two placeholder roots (`fejk` 1 and `fejka` 2,
`fallback_voice_level` 3) do not. Level-0 and level-1 actors point at level-2
actors (`bcas` 0 -> `jbea` 2 -> `fejk` 3; `ggud` 0 -> `gand` 2), and level-2
actors point at a root. `WHGame.dll` reads the `fallback_voice_id` column
(the `voice_actor_id`, `voice_technical_name`, `fallback_voice_id`,
`voice_name`, `abbreviation` column block) and nowhere else; `fallback_voice_level`
and `voice_groups` do not appear in the binary, so they are table-side metadata.
The cvar `wh_dlg_EnableFallbackVoice` is unrelated: its help text, "Controls
usage of generated dialogue voiceovers when the actual ones are not dubbed
yet", describes generated stand-in audio. An earlier revision of this note
tied it to the fallback table; that was wrong. The imported rows carried no
fallback.

### Change

`tools/source_voice_fallbacks.py` chooses the fallback from retail's own
pattern rather than by taste. A candidate is a native voice that

- has `fallback_voice_level` 2 (the tier retail's partial actors fall back to),
- is cast for Czech merchants (`voice_groups` contains `Czechs` and `Merchants`),
- has the same sex as the imported voice (Skald `gender` 0 = male, 1 = female,
  as `char_GENERIC_MAN_COMMONER_*` / `char_GENERIC_WOMAN_COMMONER_*` show;
  a voice bound to both sexes is excluded),
- and has recordings in the native shop, greeting and farewell folders
  (greetings live one level down in nested voice-namespace modules).

Candidates rank by how many retail voices already fall back to them, then by
shop recordings. On retail 1.5.x this gives men `jbea` (144, James Beaumont,
named by 10 voices, 432 shop / 35 greeting / 15 farewell recordings) ahead of
`gand` (83, 9 voices, 375 / 33 / 15), and women `aric` (68, Mia Allis, 317 /
71 / 18). The rule and the top candidates are written into the receipt.

Only the voices of the souls in `SCOPE` are changed (first `ska_merchant1`;
`ska_merchant4` was added with section 3):
`rpro` gets `fallback_voice_id="144"` and keeps `fallback_voice_level="0"`,
which is how retail writes a level-0 actor. Because the voice is shared, the
change also covers `ska_merchant3` and `ska_collierVarlet`. An existing,
different fallback is kept and reported. The report lists every converted
shopkeeper (`shop_roles.keepers`) with voice, native coverage and the fallback
it has or would get; on the installed package:

| Keeper | Voice | Native shop / greet / bye | Fallback | Status |
| --- | --- | --- | --- | --- |
| ska_merchant1, ska_merchant3, ska_collierVarlet | rpro (imported) | 0 / 0 / 0 | jbea | applied |
| ska_merchant4 | akem (imported, woman) | 0 / 0 / 0 | aric | applied (section 3) |
| ska_blanka | bvac (imported, woman) | 0 / 0 / 0 | aric | candidate, not applied |
| ska_merchant2 | bcas (native) | 199 / 33 / 15 | jbea (retail) | native voice |
| ska_woman20, neu_zdena | aric (native) | 317 / 71 / 18 | fejka (retail root) | native voice |
| rato_innkeeper1 | rlaz (native) | 6 / 31 / 15 | jbea (retail) | native voice |
| rat_pesek | dosg (native) | 207 / 33 / 15 | dcol (retail) | native voice |

The relocated copies the fallback relies on are already in the package:
`world_speech_audio.upgrade` keeps every voice, and the installed
`Localization/English.pak` holds exactly `jbea`'s 432 / 35 / 15 files under
`dialog/kcd1_travel/open_world/`.

### What this does not do

- It does not give the imported voices their own native lines. KCD1's bank
  has 30 shop-like `rpro_*` recordings, but they carry KCD1 text ids
  (`t16624_s30026_...`) that no KCD2 shop response uses, so they cannot be
  relocated onto the native shop dialogue.
- A speaker on an imported voice will use two actors: the KCD1 actor for his
  converted lines (`ska_merchant3`'s nine market cries) and James Beaumont for
  native lines. Retail accepts the same split for its level-0 actors.
- The engine's lookup order (own recording, then the fallback voice's) is
  inferred from the retail table and the cvar text, not read from code.

## 2. Henry's level-barrier bark

### Cause

The boundary is a ring of designer brushes with surface type
`mat_level_barrier`. Retail `Libs/MaterialEffects/SurfaceTypes.xml` declares
`<Barrier distance="10" slowdown="1" monologMetaroleId="HRAC_NEMUZE_Z_MAPY"/>`
on it; `C_LevelBarrierInteractor` slows and stops the player and asks for a
monolog on that metarole. Henry gets the matching role
`JINDRICH_NEMUZE_Z_MAPY` from the retail Storm rule `player_henry`
(`Libs/Storm/roles/dude.xml`, "kcd2 barrier barks"), which the package's
`Libs/Storm/storm.xml` includes. The dialog that answers the request is
`open_world/stavy_hrace_unavahlad/narazeni_na_barieru_voda_level/jindrich_narazil_na_level_barieru.xml`
in retail `Scripts.pak`: five "I should turn back" variants, all five recorded
by Tom McKay in `Localization/IPL_english.pak` under
`dialog/open_world/stavy_hrace_unavahlad/`. The standalone project never
instantiated that dialog, so the request found nothing, the same class of
failure `docs/smithing-voice.md` describes for the smithing warnings.

The native parents cannot be registered through `world_gameplay_basis.SYSTEMS`:
`stavy_hrace_unavahlad` has the campaign input `m03_socky` wired into
`narazeni_na_barieru_voda_level`, which in turn feeds two deep-water barks
from that port and from a horse stance check on `player_any`. The Level-nested
`open_world` wrapper is also the wrong host: `package_dependencies` re-resolves
its definitions against native graph paths on every upgrade, and moving the
dialog under the Level would require relocating five recordings by rewriting
the 1.4 GB `English.pak`.

### Change

`tools/level_barrier_speech.py` follows the smithing warnings and the church
prayer. The project-level `open_world` voice namespace
(`Quests/GlueTravel/smithing_voice/open_world.xml`) gets a Definition
`../level_barrier_speech/stavy_hrace_unavahlad.xml` and a
`stavy_hrace_unavahlad` node; the new folder holds a reduced
`stavy_hrace_unavahlad` Gameplay wrapper (`VoiceNamespace="true"`, like the
native one), a reduced `narazeni_na_barieru_voda_level` Module with no port,
and the native dialog copied byte for byte. `campaign_dialogue_runtime.voice_namespace`
resolves the copy to `('open_world', 'stavy_hrace_unavahlad')`, so the audio
scope is retail's own `dialog/open_world/stavy_hrace_unavahlad/` and the
installed recordings play from where they are. Nothing is copied or relocated
and no native graph is modified.

Before writing, the step checks the retail contract it depends on and fails
loudly if a game update changes it: the native parent, module and dialog
layout; the dialog has no ports, assets or other roles and is an
`ingame monolog`; `mat_level_barrier` still requests `HRAC_NEMUZE_Z_MAPY`; the
metarole exists; `player_henry` still adds the role; the package Storm still
includes `roles\dude.xml`; every line has a recording under the native scope.

### Not included

- The deep-water barks (`HRAC_NEMUZE_DO_HLUBOKE_VODY`) in the same module need
  the horse stance asset and a quest-progress constant; they are the natural
  next step once the barrier line is heard.
- The hunger, fatigue, drunkenness and unconsciousness barks of the same
  native parent, for the same reason.
- The smithing, prayer and dice dialogs share this project-level registration,
  and none of them has been heard in game yet. The barrier line is the first
  chance to confirm the mechanism; if it stays silent, the three earlier
  registrations are suspect too.

## 3. Converted KCD1 traders keep KCD1's own shop conversation

Sean's decision (1 Nov 2026): "all KDC1 NPCs should use their original lines
and voices. KCD2 keeps KDC2. Keep the feel the same. If it did not exit in 1
dont port it over for the time being." This replaces the earlier attempts:
- the native spoken trade dialog (`native_shop_dialogue` v1, -5: no trade off
  the stall);
- the native shop greeting (v2, -6: silent talk screen);
- an ungated native dialog with direct native voices (parked, never committed).

`native_shop_dialogue` is retired.

### What KCD1 had

KCD1 traders got `addShopRoles_man/woman`: `SMLOUVANI_(MUZ|ZENA)` for the haggle
reactions in the shop screen, `VYJEDNAVANI_*` for negotiation, and `MERCHANT`
for one unvoiced choice, "Let's talk trade." (topic 22069, a type-9 sequence
that opens the shop). Every NPC greeted through `POZDRAV_(MUZ|ZENA)`.

The live closures:
- greeting 25570 (man) / 25697 (woman): 71 / 64 lines;
- haggle 23469 (man) / 23605 (woman): 31 trader + 12 Henry lines each.

Older generations of these closures have no English text or recordings. Every
trader voice recorded its pools:
- rpro (ska_merchant1, ska_merchant3, the collier's varlet);
- bcas (ska_merchant2);
- akem (ska_merchant4);
- aric (ska_woman20);
- bvac (ska_blanka);
- tmck for Henry.

KCD1 had no trade farewell.

### Change

`tools/kcd1_shop_conversation.py` converts; `tools/kcd1_shop_install.py` installs.
The install covers the seven converted keepers only. Native KCD2 shopkeepers
in the package keep the native dialogs.

- **Haggle.** KCD2's `open_world/shop/bribe_haggle_.../smlouvani_v_obchode_*`
  descends from KCD1 23469: its Decisions keep the KCD1 topic ids, it reads the
  same gvars, its ExitScripts run the sale, and the shop screen finds it by
  the SMLOUVANI metarole.
  - The port keeps that skeleton and swaps in the KCD1 text ids. A KCD1 line
    maps only inside the Decision named after its topic, and only to a sequence
    with the same entry condition. KCD1's female copy (23605...) aliases onto the
    male ids that KCD2's female dialog uses.
  - Every KCD2 Response without a KCD1 counterpart is removed. Sequences,
    ports, scripts, jumps and OpenShop stay.
  - The role becomes `GM_KCD1_SMLOUVANI_*` (role row metarole SMLOUVANI), and
    the keeper loses `SMLOUVANI_*`, so exactly one haggle dialog binds. The
    step checks that, and `shop_roles` skips ported keepers on a fresh build.
  - `skeleton_differences` allows only text ids, removed responses, the dialog
    name and the role token, and the step refuses to write otherwise.
  - Reviewed exception: in Decision 23528, KCD1's "No deal then." and "Forget
    it then." carried a KCD1-only condition (`negotiation_result_canceled == 0`,
    `negotiation_merchantReaction_kind == 4`). KCD2 kept the same five lines
    unconditioned, in the same order (seq57-seq61), so they map onto them and
    the KCD1 condition is dropped.
  - Reviewed exception: in Decision 23479, KCD1 gave "Naturally." and "Sure,
    why not?" the condition "< 0.35". That band overlaps the mid band
    (-0.35 to 0.35), and it comes first (priorities 0-1, mid band 2-3), so the
    lines fired for every dominance below 0.35. That range contains KCD2's
    tightened "< -0.35" band, whichever way KCD1 picked among valid sequences,
    so the lines map onto KCD2's low band.
  - Result: man 43 of 43 lines, woman 42 of 43.
  - KCD2's female seq60 has no line, so the female "I'm finished. This is
    going nowhere." has no slot.
- **Greeting.** KCD1 25570/25697 become a KCD2 `Dialog` of Type "greeting",
  shaped like KCD2's own common greeting.
  - A gate on `!Port('uz_jsem_pozdravil')` fires `nastav_cooldown`. This is
    KCD2's once-a-day greeting cooldown, standing in for KCD1's
    `RemoveMetaRoleByName('POZDRAV')`. That substitution is a port, not an
    addition.
  - The KCD1 topics follow as Autoselect Decisions. Overlapping conditions stay
    as KCD1 wrote them: the bleeding and appearance variants sit after the broad
    reputation branch, so KCD1 cannot have taken the first valid sequence.
  - The ports are wired to KCD2's greeting state node
    (`utils.greetings_utils` timeandplayerstate) and cooldown, as KCD2's module
    wires its common greeting.
- **Trade.** KCD1's "Let's talk trade." becomes the generated trade dialog's
  proven shape (Trade topic, OpenShop behind it, End dialog) bound to
  `GM_KCD1_OBCHODNIK`, with KCD1's prompt string and greetings allowed.
  - There is no seller_in_shop gate, so it trades on and off the stall.
  - The seven generated per-keeper dialogs leave the archive and the entry
    Level. The tavern and charcoal ones held only Trade/OpenShop/End.
- **Storm.** Each keeper's own rule:
  - adds the three roles;
  - drops `SMLOUVANI_*`, the v1 spoken-trade role, the v2 shop greeting and the
    native post-purchase farewell (`addShopRoles_ending_*`), because KCD1 had
    no trade farewell;
  - removes KCD2's common greeting and farewell (`POZDRAV_*`,
    `ROZLOUCENI_S_HRACEM_COMMON_*`; the package Storm includes retail
    greetingsAndEndings.xml, which comes earlier in source order);
  - keeps `VYJEDNAVANI_*`, which is not a shop step.
- **Hosting.** The five dialogs sit in a `gm_kcd1_shop` Gameplay module under
  `Quests/GlueTravel/kcd1_shop/`, registered in the project-level `open_world`
  voice namespace (`smithing_voice/open_world.xml`) beside the prayer and
  barrier registrations.
  - `entry/world/open_world.xml` is the crime step's wrapper: it must hold
    exactly the native systems and `utils`, and is rebuilt from native data.
    The -7 build failed when the port registered there. The port never writes
    it now, and refuses a package that still has that pre-release layout.
  - The module brings its own `native/utils.xml` closure, packaged by
    `world_gameplay_basis.package_dependencies`. Besides `general` and
    `greetings_utils`, timeandplayerstate pulls in `item`, `reputation`, `rpg`
    and `time`.
  - Before writing, the step resolves every node type through the packaged
    scopes and every asset alias through the module's ancestors. It also
    copies the native Project Types the graphs use (`RPGStatInterval` on -6).
- **Assets.**
  - The trader and Henry KCD1 recordings go to the module's audio scope
    (`dialog/open_world/gm_kcd1_shop/`; the Project adds no folder), with a
    dubbing row for each speaker's own stem.
  - The text goes to text_ui_dialog. The mod ships English only.
  - The traders' KCD1 facial records go to the facial pak. Henry's KCD1
    records target the KCD1 rig and are not imported.

Greeting adapter, KCD1 condition → KCD2 port (to tune after the first play
test):

| KCD1 | KCD1 meaning | KCD2 port |
| --- | --- | --- |
| greeting_reputation_5 / _4 | relationship ≥ 0.8 / 0.65-0.85 | reputace_dobra |
| greeting_reputation_3 | 0.3-0.7 | reputace_stredni |
| greeting_reputation_2 / _1 | 0.2-0.35 / < 0.25 | reputace_nizka |
| GetActorAngriness < 0.25 | calm | nastvanost__klid |
| angriness 0.2-0.4, 0.4-0.7, > 0.5, > 0.65 | not calm | nastvanost__neklid |
| gvar playerIsBleeding == 1 | bleeding | hrac_je_zakrvaceny |
| greeting_looksPoor | dirtiness > 0.25 | hrac_je_spinavy |
| greeting_looksFancy | relative charisma > 0.5 | hrac_ma_alespon_vysoke_charisma |
| HourOfDay 6-10 / 12-17 / 18-22 | time of day | je_rano / je_odpoledne / je_vecer |
| greeting_looksKnightly | armour > 0.65 | FALSE (KCD2 has no such state) |
| greeting_do_not_judge_clothes_*, expectsDude | named souls / soul tag | FALSE (none of the seven) |

Known gaps, for later enhancements:
- The "good knight" greetings can never play (6 male, 7 female lines).
- In the haggle, these KCD2-only mechanics now run silently:
  - the stolen-goods refusal funnel;
  - the own-goods theft reaction;
  - the no-deal funnel (dec2/seq64);
  - the second line of KCD2's two-line reactions where KCD1 had one.
- No silenced sequence is a player choice.

### Why the talk screen needs a dubbing row (consistent, not proven)

On -6, ska_merchant4 (imported voice akem, fallback aric) spoke her world bark
but not her shop greeting in the talk screen. The installed English.pak had
dubbing rows for `aric_gree_obchodnik_pro_cos_pr_9RFJ`, `aric_pozd_...`, bcas's
leave line and the rpro market cries, and none for the akem stems. The dubbing
table belongs to `wh::dialogmodule` (DialogueDubbingDatabase).

So "the talk screen needs a row for the speaker's own stem, world speech does
not" explains every observation so far. The port therefore adds a row for each
speaker's own stem, and treats those rows as essential.

### Validation

- `tests/test_kcd1_shop_conversation.py`: haggle mapping, condition override,
  empty slots, skeleton diff, role tokens, female aliasing, inventory, greeting
  adapter and emitter, trade dialog.
- `tests/test_kcd1_shop_install.py`:
  - keeper rule changes and idempotence;
  - the haggle-role guard, including custom operations;
  - role rows;
  - cloned haggle wiring;
  - greeting wiring;
  - registration;
  - `shop_roles` skipping ported keepers.
- Dry runs on hard links of the -5 backup and the installed -6:
  `diag/voice-lines-20261030/kcd1-shop-port/dry-run-{5,6}-report.json`.

### Retail acceptance

1. First talk of the day with each of the seven keepers: a KCD1 greeting in the
   keeper's KCD1 voice, then "Let's talk trade." opens the shop, on and away
   from the stall. Exactly one Trade option.
2. Haggle: KCD1 reactions in the keeper's voice and Henry's KCD1 lines. Buying
   and selling must complete (money and items move), since the sale runs in
   the haggle dialog's scripts.
3. No KCD2 greeting, shop greeting or post-purchase farewell on these keepers.
   A native KCD2 shopkeeper (neu_zdena, rat_pesek, rato_innkeeper1) is unchanged.

## Wiring

`setup_package_upgrade.finalize` runs the three steps (fallbacks, the KCD1 shop
conversation, barrier bark) right after `setup_work_speech` on the
completed-package fast path and on the full path, with receipt keys
`source_voice_fallbacks`, `kcd1_shop_conversation` and `level_barrier_speech`. Both
are idempotent and return the travel archive digest only when they changed
it. `build_recipe.VERSION` 66 -> 71 (67, 68 and 69 belong to
`feat/home-door-locks`, `feat/loft-navmesh` and `feat/moved-line-lipsync`;
whichever merges later rebases its bump). `desktop_setup.CONVERTERS` lists all three
modules.

## Validation

- `tests/test_source_voice_fallbacks.py` (8): the rule picks the most
  referenced complete Czech merchant voice of the right sex and skips German,
  mixed-sex, partially recorded and non-merchant voices; only the scoped voice
  is written; shared users are covered; a second run changes nothing; an
  existing fallback is kept; a scoped voice without a candidate fails before
  writing; coverage counts nested greetings; duplicate identities are rejected.
- `tests/test_level_barrier_speech.py` (8): the reduced hierarchy, the
  byte-identical dialog copy, the resolved voice scope, idempotence, and the
  failures for a missing recording, a changed surface hook, role or metarole,
  a dialog with inputs or other roles, a changed native layout, a missing
  project registration and an existing wired registration.
- `tests/test_setup_package_upgrade.py`: both steps run on both finalization
  paths with the game folder and a progress callback; `tests/test_desktop_setup.py`
  lists them in the converter inventory.
- Full suite on the branch: 2,326 tests, 0 failures, 19 skipped and the same 9
  environment errors (missing `webview` and `numba` in the system Python, parallel
  bake workers) that the untouched 47f031a worktree shows with 2,304 tests; logs in
  `D:\KCD\Builds\glue\diag\voice-lines-20261030\`.
- Dry run on hard-linked copies of the installed recipe-66 package
  (`D:\KCD\Builds\glue\diag\voice-lines-20261030\dry-run-report.json`):
  fallback step 3.5 s then 3.2 s, barrier step 3.5 s then 2.6 s; the second
  runs change nothing. Of the travel archive's entries, three were added
  (the `level_barrier_speech/` graphs) and two modified
  (`voice__gm_source.xml`, `smithing_voice/open_world.xml`); the installed
  archive's hash is unchanged.

## Retail acceptance steps

1. Trade with and greet `ska_merchant1` (813,3487), `ska_merchant3` and the
   collier's varlet: expect shop, greeting and farewell lines in James
   Beaumont's voice (with subtitles as before). `ska_merchant3`'s market cries
   stay in his KCD1 voice.
2. Trade with and greet `ska_merchant2`: still Brian Caspe, unchanged.
3. `ska_blanka` stays silent on native lines until her voice is added to
   `SCOPE`; that is the control.
5. Ride the east road to about 3930,1827. When the barrier stops Henry, one of
   the five lines should play: "No, I shouldn't leave now.", "I should go
   back.", "Hmm, I have to go back.", "No, I can't leave now." or "Oof... I
   should go back." (retail `text_ui_dialog.xml`). Henry's head is native and
   the recording path is native, so the line should also lip-sync. A Mod Tools
   build should no longer log `Unable to force monolog via metarole` for
   `HRAC_NEMUZE_Z_MAPY`.
6. After the first confirmation: add `ska_blanka` to `SCOPE` (one line) and
   rebuild; then consider the deep-water barks.
