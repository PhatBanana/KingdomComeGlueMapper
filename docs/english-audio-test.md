# Original English voices and music mapping

`tools/build_english_audio_test.py` stages a patch over the currently installed
Python mod. It does not regenerate the world, replace native master banks, or
change player voices globally. Generated recordings and extracted game metadata
stay under ignored `outputs/`, never in the source release.

```powershell
python tools/build_english_audio_test.py `
  --source D:\SteamLibrary\steamapps\common\KingdomComeDeliverance `
  --target D:\SteamLibrary\steamapps\common\KingdomComeDeliverance2 `
  --mod D:\SteamLibrary\steamapps\common\KCD2Mod\Mods\kingdomcomegluemapper `
  --output D:\KingdomComeGlueMapper\outputs\EnglishAudio\CurrentTest
```

Choose a fresh output directory. The build records baseline/output hashes.
Install only the three staged PAKs while the game is closed, after checking the
baseline hashes still match. Other world, quest, horse and herb packages remain
the existing installed versions.

## Voice binding

The source roles are Henry (3), Zora (941), and the female horse merchant (2535).
Recordings are resolved through `v_response_wave_file_recorded`, the source
response IDs, English subtitles and KCD2's native voice table. Henry resolves to
`tomMcKay` (`tmck`), and Zora to `abigailRice` (`aric`). Regular English banks and
owned DLC banks are indexed; HD variants are deliberately not mixed with them.
Ambiguous audio contents, missing selected lines and non-Ogg payloads fail build.

The horse introduction uses original sequence lines 156455, 156457 and 156521.
The spoken subtitles are the original English strings, not the previous custom
prose. `VoiceNamespace=true` and the namespaced `dialog/gm_neuhof_horse_sales/`
paths follow KCD2's native dialogue packaging. The existing quest trigger still
returns to the horse selection menu. A repeatable introduction is available
when the introductory quest step is inactive; it does not fire quest triggers.
The custom advice topic remains unvoiced and is listed in the report.

The first live test exposed two missing runtime contracts: `SelectedSoul.Voice`
did not assign a voice to Zora's imported soul, and copying Ogg files without the
English dubbing index produced missing-wave and synthetic-timing errors. The
builder now gives her a dedicated `skald_character` record with voice 68 and
links that record from her soul. It merges all native rows of
`dialog/response_depot_wave_file.xml` with the imported recordings and their
durations. The native index includes duplicate hashes; their order and values
are preserved. The filename-stem CRC32 rule is checked against 32 native files
on every build. Audio duration comes from Vorbis sample rate and the final Ogg
sample granule. The original three recordings still require a fresh live test
after this correction; the earlier session demonstrated failure, not playback.

Generated files:

- `dialogue-map.json`: source response/role, original subtitle, recording path,
  archive/CRC/size, native voice identity and explicit missing status.
- `report.json`: provenance, installed voice hashes, remaining custom lines,
  baseline/output hashes and `runtime_verified=false`.
- `package/Localization/English.pak`: only the selected original recordings,
  merged with existing mod English audio if present, plus the merged dubbing index.
- Updated existing travel and English subtitle PAKs.

Runtime acceptance still requires hearing both Henry and Zora, checking subtitle
timing, reaching the horse menu, and buying a horse. Static validation does not
prove audio playback or lip synchronization. No KCD1 facial animation is imported.

## Music mapping status

`music-map.json` validates every source SQCB directory, segment offset/size and
Ogg signature, and records source scene dependencies and native-name collisions.
The installed source has 139 containers. KCD1 and KCD2 both use SQCB1.00, but their
adaptive controllers are WIDSH 1.18 and 1.22 respectively. Identical audio
containers do **not** make the old controller's state variables compatible.

Music is audited, **not installed or activated by this English-audio builder**.
Its inventory labels describe that builder's scope. The separate
[`world_music` conversion](music-conversion.md) now imports original score
scenes and recordings with native area/state bindings, integrated into the
normal world builder. It merges with the native controller and gates scene
selection and continuation by world; it does not copy KCD1's global controller
over KCD2's unchanged. No FMOD master-bank replacement is generated.
