# Lip sync for relocated native speech

Status: converter, validation and tests done; **not tested in game**. Whether the engine resolves a
relocated line's facial track at the new path exactly as inferred, and what the result looks like on
converted heads, are retail acceptance steps (below).

## Why

KCD2 finds a line's facial animation by mirroring its recording path: `dialog/X/Y.ogg` plays
`animations/humans/facials/dialog/X/Y.caf` from `Animations/FacialAnimations.img`. In retail,
253,706 of 260,040 English recordings have a header at exactly that path, and the mod's own
`FacialImporter.add` follows the same rule for KCD1 lines (392 of 401 sync; the 9 without a source
track are ska_merchant2's market cries).

`world_speech_audio.upgrade` copies the native recordings of the instantiated world modules under
the imported world's voice namespace: 64,670 recordings (56,955 from `dialog/open_world/`, 7,715
shared-library lines from `dialog/utils/`) move to `dialog/kcd1_travel/open_world/...`. Nothing
indexed a facial track at the new paths, because the gameplay `facials` recipe step matches KCD1
source headers only. So greetings, farewells, shop and haggle lines, fines, arrests, reactions and
combat barks play without lip sync while KCD1 quest lines in the same conversation sync (upstream
issue #57, point 3). 61,942 of the moved lines have a native track at their original path; 2,728
have none in retail either.

## What `tools/world_speech_facials.py` does

It runs in shared finalization directly after `world_speech_audio.upgrade`, on the clean path and on
the completed-package fast path, with receipt key `world_speech_facials` (recipe 66 -> 69).

1. It reads the same relocation plan as the audio pass (`world_speech_audio.plan` and `selection`,
   factored out of `upgrade` unchanged) and requires every planned recording to be in the package's
   `English.pak` with the native payload; otherwise it fails, so the order cannot flip silently.
2. `NativeFacialImporter.relocation` matches each relocated recording to a native header by the
   **full original path** (`animations/humans/facials/` + original path + `.caf`), never by stem,
   and groups the matches by the native DBA that holds their curves. Lines without a native header
   are listed as `missing_tracks`.
3. `index_relocation` adds one header per matched line at the relocated path: a renamed copy of the
   native header whose DBA CRC points at the copy, hash field 0 like upstream's imports. Existing
   relocated headers keep their record identity, headers of lines no longer relocated are removed,
   and a header at a relocated path that belongs to any other import is a hard conflict.
4. `relocated_database` copies each native DBA once through `select_database`: the relocated clips
   renamed inside, their controllers, metadata and the shared curve block byte-for-byte, and each
   clip's controller count must equal its native header's.
5. The copies are written deflated into `Data/gluemapper_world_speech_facials_NNNN.pak` (1 GiB per
   shard, pending files verified before any replace). The extended index stays in
   `Data/gluemapper_dialogue_facials.pak`, whose other entries are untouched. Per-DBA provenance and
   the missing list go to `world-speech-facials.json` in the package root.

Repeatable: an output DBA is named by a hash of its source DBA and exact rename set, so a later pass
recognises its own archives by name, records keep their identities, and nothing is rewritten when
nothing changed (second run on the full package: 11 s, zero changes, identical digests).

## Measured on the installed recipe-66 package (built from 47f031a)

| Measure | Value |
| --- | --- |
| Relocated recordings | 64,670 (utils 7,715, open_world 56,955) |
| Headers added | 61,942 (index 295,948 -> 357,890 records; facials pak 219 -> 245 MB) |
| Without a native track | 2,728 (the lines retail does not sync either) |
| Native DBAs copied | 4,203 of 19,800; 62,012 clips in them, 61,942 selected |
| Copied curve bytes | 1,616,810,980 raw; 1,038,697,143 deflated; shard file 1,039,613,419 bytes |
| First run / second run | 80 s / 11 s on this machine |
| Small scope (ska_merchant2 shop lines) | 199 recordings, 110 tracks, 6 DBAs, 1.9 MB |

By module (raw bytes): punishment 368 MB, combat 343 MB, utils 309 MB, shop 265 MB, player-state
reactions 72 MB, greetings 70 MB, wounds 44 MB, NPC greetings 36 MB, friendly-enemy reactions
26 MB, reputation 25 MB, farewells 20 MB, sleep 20 MB, battle barks 8 MB, perks 6 MB, repair,
punishment barks and sharpening under 2 MB each.

## Size and the 16 GB / RTX 2070 case

The mod grows by about 1.04 GB on disk (1.62 GB if the archives were stored like most of the
project's paks; the retail facial paks are deflated, as are the project's music and appearance
paks, so the engine already inflates these DBAs when it streams them). At runtime the engine loads
the same DBAs it loads when the same lines play in Trosky, one line at a time, so there is no VRAM
cost and no new resident set beyond the 21% larger facial index. The build streams one DBA at a
time, so its peak memory is bounded by the largest native DBA (24 MB) plus the index.

No bound is applied by default: every moved line that has a track gets one. If a smaller profile is
ever wanted, the module table above says what each group costs (skipping combat, wounds and battle
barks would save about 395 MB raw / 250 MB deflated), and `stage(..., only=prefix)` runs a partial
dry run. A bound would trade exactly those lines' lip sync for disk.

## Retarget onto converted KCD1 faces (step version 2, not tested in game)

In game on recipe 71 -6, converted NPCs stayed still on moved lines with a native track and, after a
facials swap, without one: their KCD1 faces carry `*_blendWeightVertex` joints and no `FA_POSE` ones, so a
native track cannot move them. KCD1 and native tracks store a pose weight the same way (the x of a float
position track; native jaw ranges about 0.37, KCD1 about 0.5), so the step now copies native controllers
onto the KCD1 joint names through the existing `select_database(..., aliases)` path:

- `facial_rig_adapter.reverse_speech_mapping()`: 56 rows, 53 used. It inverts `speech_mapping()`; where the
  forward table fans out (lower lip, squint) the left/upper pose drives the joint and the other is recorded as
  unused. `REVERSE_EXTRA` adds 11 rows by name (S2 eye joints, `stickyLips`) or by meaning (U viseme to pucker,
  upper-lip raisers, lip part, outer brow lowerer), each with its basis. KCD1 joints without a driver:
  `mouthBack`, `left/rightMouthAngry`, `left/rightMouthSlide`, `fvFuck`, `pbm2`, and the S2 tongue joints
  `tBack`, `tRoof`, `tTeeth`. On S1 faces 46 of 53 joints are driven, on S2 faces 53 of 63.
- Amplitude: curves are copied unchanged. A native jaw opens about a quarter less than the KCD1 lines did;
  native lines carry brows and cheeks that KCD1 lines barely moved. Blanka's faint KCD1 lip motion suggests
  converted faces may need more than 1:1; that needs new curve data, not aliases, and only a play session
  can tell.
- When a package has converted faces (any `gm_person_*.pak` face skin), every relocated clip gets the
  aliases (copies are renamed by the alias table, so an older package is rebuilt once), headers carry the new
  controller counts, and the shared mood/gesture database `Animations/humans/facials/facials.dba` is written
  aliased into `gluemapper_dialogue_facials.pak` beside the index (its 258 native headers are recounted; the
  importers' baseline check accepts exactly that difference). Native controllers stay byte-for-byte, so native
  heads, Henry included, play exactly as before. Without converted faces, the plain copies, native counts and
  no gesture override come back.
- Measured on the 6279abd full index with the -6 faces: 56 converted faces, 63 KCD1 joints, 53 aliases; 61,942
  headers refreshed, the shard grows from 1,038,697,143 to 1,045,480,201 deflated bytes (1.65 GB raw), the
  facials pak from 245 to 268 MB with the gesture override; first run 63 s, second run 8 s with no change.
  665 sampled clips in 49 DBAs keep every native controller and track byte; every added controller reuses its
  source pose's track; every header count matches its clip.

## Validation (offline)

- `tests/test_dialogue_facials.py`: path matching, a stem-only match rejected, identity retention on
  repeat, a new database on a changed rename set, stale removal, foreign conflict, invalid path.
- `tests/test_world_speech_facials.py`: audio-first ordering, index and shard contents against a
  synthetic native facial pak with a prior KCD1-style import left untouched, report fields, second
  run byte-identical, staging into a new folder with the prefix filter, foreign conflict, removal of
  entries and archives when lines stop being relocated, shard splitting at the byte bound, and the
  skip without a game folder for packages without a relocated world.
- `tests/test_setup_package_upgrade.py`: the step runs after `world_speech_audio` on both paths and
  its report lands in the receipt.
- Full suite: 2,312 tests, 0 failures, 19 skipped, the same 9 environment import errors
  (numba/NumPy, missing webview, parallel bake worker) as untouched `main` 47f031a (2,304 tests).
- Dry runs against the installed package (`D:\KCD\Builds\glue\diag\moved-line-lipsync-20261030\`):
  the small scope staged, then the full upgrade twice on private copies of the three archives. Travel
  and English archives untouched, the installed index a byte-identical prefix, 61,942 headers added
  and all pointing into the shard, 41 sampled DBAs (including the largest) equal to the native clips
  byte-for-byte.

## Limits

- The lookup rule is inferred from the path-mirrored index, upstream's `NativeFacialImporter`
  docstring and the in-game split between KCD1 lines (sync) and moved lines (none). If the engine
  resolved facials some other way, the added headers would be unused, not harmful.
- Native tracks drive `FA_POSE_*` controllers. Converted KCD1 heads have no such joints (issue #57,
  point 1), so the first visible beneficiaries are native-rig speakers: Henry's own replies and any
  native-template NPC. Converted NPCs need the rig mapping as well.
- The 2,728 lines without a native track stay as in retail.
- The facial index grows from 124 MB to 145 MB; no engine cap is known.
- The shard is 34 MB under its 1 GiB bound; more relocated lines spill into a second shard
  automatically (the engine mounts every pak in the mod's Data folder).
- Recipe 69 collides with `feat/home-door-locks` (67) and `feat/loft-navmesh` (68); whichever merges
  later rebases its bump.

## Retail acceptance steps

1. Build or upgrade to recipe 69 and check the receipt: `world_speech_facials.facial_tracks` 61,942,
   one archive, `Data/gluemapper_world_speech_facials_0000.pak` present, `world-speech-facials.json`
   listing 2,728 missing tracks.
2. In Skalitz, trade with `ska_merchant2` and haggle: Henry's replies (`tmck_` shop lines) must now
   lip-sync. The merchant's greeting and shop lines carry tracks too, but his converted head may not
   show them (point 1 of issue #57); note both.
3. Get fined by a guard (`utils/punishment` lines such as `bcas_stra_strazny_z_a_byl_to_t_WLxq`): the
   same split, with Henry's side of the exchange as the control.
4. Blanka in the tavern (`gm_tavern_dialog_7705`) must still sync as before; the KCD1 import is
   untouched.
5. If a native-template NPC appears, their combat and greeting lines should sync.
