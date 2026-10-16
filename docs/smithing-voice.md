# Native smithing warnings in the standalone map

The running development log on 16 October 2026 showed the native minigame
requesting BLACKSMITHING_COLD_WORKPIECE and BLACKSMITHING_BROKEN_WORKPIECE,
followed by `Unable to force monolog via metarole`. The standalone
GlueTravel_kcd1 project does not instantiate the native open-world smithing
dialogue module. The station alone supplies mechanics but not that registration.

`tools/build_smithing_voice.py` adds a minimal open_world/minihry hierarchy to
the standalone project, containing only the shipped kovareni Gameplay module
and its nine dialogue definitions. It preserves native decisions, aliases,
roles, text keys and the tutorial suppression context. It does not start native
story quests or use a timed substitute for actual gameplay warnings.

Both wrapper nodes explicitly retain the native VoiceNamespace setting. The
resulting audio scope is `dialog/open_world/minihry`, matching 73 verified Tom
McKay recordings in the installed English audio packages. No audio files,
shaders, player voice identities or global native scripts are replaced.

The combined staged package is `outputs/SmithingVoice01/package`, based on the
previously staged SmithingSupplies01 package. Its report includes the installed
baseline hash and staged hash. Unrelated archive entries were checked unchanged.
It is NOT installed while the game is running. Install its gluemappertravel.pak
after the game closes, preserving the previous file and checking the baseline
hash first. A subsequent normal game launch/map load is needed to load the new
graph. Runtime warning playback remains unverified.

The live log also reports missing `f_bl_forge` and `blacksmithing_piece` audio
controls. Those are separate sound-effects issues; this dialogue registration
does not claim to repair them. A further slave-context conflict appeared after
minigame transitions and likewise remains outside this voice patch.

Build:

```powershell
.venv/Scripts/python.exe tools/build_smithing_voice.py --game D:/SteamLibrary/steamapps/common/KCD2Mod --mod D:/SteamLibrary/steamapps/common/KCD2Mod/Mods/kingdomcomegluemapper --base outputs/SmithingSupplies01/package --output outputs/SmithingVoice01
```

Verify in game by allowing the workpiece to cool, overheating it and making
ineffective strikes. Confirm an actual native warning plays, its subtitle is
correct, and the log no longer rejects the relevant metarole. Do not infer
successful playback from the presence of the recordings alone.
