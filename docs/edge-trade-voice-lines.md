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
`voice_name`, `abbreviation` column block) and exposes the cvar
`wh_dlg_EnableFallbackVoice` ("Controls usage of generated dialogue voiceovers
when the actual ones are not dubbed yet"); `fallback_voice_level` and
`voice_groups` do not appear in the binary, so they are table-side metadata.
The imported rows carried no fallback, which is the whole defect.

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

## 3. Converted traders talk through the native shop dialogue

Added on 31 Oct 2026 after the -4 play session (recipe 71 on a plain launch):
every Skalitz market trader and Henry were silent on the talk and trade
screen, while the traders' world lines played with audio and subtitles. No
record shows any converted trader's trade speech was ever heard, so this
predates the feature branches.

### Cause

Each converted source trader's talk screen is a generated FaderDialog
(`region_travel_merchant.dialogue`, registered as `<namespace>_trade` in the
entry Level by `campaign_merchant_work.add_trade_dialogue`). It sets
`AllowGreeting="false"` and `AllowFarewell="false"`, and none of its
Responses carries Text, so neither side says anything. Trading works through
its Shop and OpenShop sequences. Retail traders talk through Storm roles
instead: `addShopRoles_greeting_*` gives the native greeting
(`open_world/shop/greeting_obchodnika_*.xml`), and `OBCHODNIK_Z_DIALOGU_MUZ`
or `OBCHODNICE_Z_DIALOGU_ZENA` select the spoken trade dialog
(`open_world/shop/nakupovani_z_dialogu_*.xml`, Henry 8 lines, trader 5, with
Shop, OpenShop and ShopDenied). Both dialogs are in the native `shop` module
the package already registers, and their recordings are already relocated.
`shop_roles.py` left the spoken-trade role out on purpose so a keeper would not
get a second Trade option beside the generated one.

### Change

`tools/native_shop_dialogue.py` replaces the generated dialog for the
`gm_source_shop_*_trade` keepers. It adds the spoken-trade role and the
greeting operation to the keeper's own Storm rule, and removes the generated
dialog's Definition, node and file. The native Shop sequence needs
`Port('seller_in_shop')`, which is the keeper's `shop_sellerReadyToSell`
context. The step therefore acts only when one of the keeper's schedule jobs
has a behavior tree that sets that context. All five Skalitz source traders
qualify: `ska_merchant1` and `ska_merchant4` on the native market seller,
`ska_merchant2`, `ska_merchant3` and `ska_woman20` on converted work trees
that set it. A keeper without such a job, without its own roles rule, with a
wired dialog or with an edited dialog keeps the generated one and is reported.
The tavern (`ska_blanka`) and charcoal (`ska_collierVarlet`) trade dialogs
have the same silent shape but are out of scope and only reported.

Because `ska_merchant4` now gets native trade lines, `source_voice_fallbacks.SCOPE`
also covers her: her imported voice `akem` gets fallback 68 (Mia Allis). The
charcoal burner, on `rpro`'s fallback, was heard speaking on 31 Oct, which is
the first in-game sign that the fallback works.

**This changes behavior that comes from the maintainer's merchant code**
(`region_travel_merchant.dialogue` and `campaign_merchant_work.add_trade_dialogue`
still generate the dialog; this step replaces it afterwards). Upstream may
prefer to stop generating it instead.

### Validation

- `tests/test_native_shop_dialogue.py` (6): the generated shape is
  recognised and a spoken dialog is not; ready keepers get the roles and lose
  the dialog; a keeper whose job does not set the context, one without a roles
  rule and a wired dialog are left alone; out-of-scope dialogs stay; a changed
  native dialog or greeting operation fails before writing; a second run
  changes nothing.
- Dry run on hard-linked copies of the -4 package
  (`D:\KCD\Builds\glue\diag\voice-lines-20261030\dry-run-4-report.json`):
  first run removes the five generated dialogs and modifies the five keepers'
  role files, the entry Level and the imported voice table; the second run of
  all three steps changes nothing; the source archive is unchanged.

### Retail acceptance

1. Talk to each Skalitz market trader: a greeting should play, then Henry asks
   to trade and the trader answers before the shop opens. Expect James
   Beaumont for `ska_merchant1` and `ska_merchant3`, Mia Allis for
   `ska_merchant4`, Brian Caspe for `ska_merchant2`, and `ska_woman20`'s own
   native voice.
2. Exactly one Trade option per trader.
3. Off duty (at night or away from the stall) the trader should not offer
   Trade; that is the native `seller_in_shop` rule.
4. Blanka and the collier keep their current trade screens.

## Wiring

`setup_package_upgrade.finalize` runs the three steps (fallbacks, native shop
dialogue, barrier bark) right after `setup_work_speech` on the completed-package fast path and on the full path,
with receipt keys `source_voice_fallbacks`, `native_shop_dialogue` and
`level_barrier_speech`. Both
are idempotent and return the travel archive digest only when they changed
it. `build_recipe.VERSION` 66 -> 70 (67, 68 and 69 belong to
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
4. If a KCD2Mcp session is open, read the cvar `wh_dlg_EnableFallbackVoice`
   (read-only); the step assumes it is on.
5. Ride the east road to about 3930,1827. When the barrier stops Henry, one of
   the five lines should play: "No, I shouldn't leave now.", "I should go
   back.", "Hmm, I have to go back.", "No, I can't leave now." or "Oof... I
   should go back." (retail `text_ui_dialog.xml`). Henry's head is native and
   the recording path is native, so the line should also lip-sync. A Mod Tools
   build should no longer log `Unable to force monolog via metarole` for
   `HRAC_NEMUZE_Z_MAPY`.
6. After the first confirmation: add `ska_blanka` to `SCOPE` (one line) and
   rebuild; then consider the deep-water barks.
