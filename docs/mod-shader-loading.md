# Mod-contained shader loading

The source setup recipe now includes the four compiled shader archives inside
`Mods/kingdomcomegluemapper/ShaderCache/Engine`. The setup Library has a **Launch mod**
button; no CMD or PowerShell shortcut is installed in the mod. No retail Engine
archive is overwritten. The released
setup EXE has not yet been rebuilt with this change.

## Why a separate launcher is needed

KCD2's retail log shows `Engine/Shaders.pak` and `ShadersBin.pak` mounting before
renderer initialization. `ShaderCache.pak` mounts during renderer initialization,
and `ShaderCacheStartup.pak` immediately afterward, before the regular mod Data
archives. Placing compiled shaders in an ordinary mod Data archive is too late
and uses the wrong virtual root. Warhorse's [Installing mods](https://warhorse.youtrack.cloud/articles/KM-A-56/Installing-mods)
also identifies shader PAKs as requiring manual setup beyond ordinary Data mods.

The unchanged retail executable searches upward from its own path for the Engine
directory. This allows a private launch root inside Mods, without an engine patch
or changing the retail install. The launcher creates exactly one reusable view:

```text
Mods/
  kingdomcomegluemapper/
    ShaderCache/Engine/       four compiled archives
  .kingdomcomegluemapper-runtime/
    Bin/                     hard links to unchanged retail EXEs/DLLs
    Engine/                  shader links to the mod; other PAK links to retail
    Data/                    directory junction to retail Data
    Localization/            directory junction to retail Localization
    Mods/                    manifests/config copies and per-mod asset junctions
    system.cfg               private copy of retail configuration
```

The large asset directories and binaries share the existing files. They are not
another full game build or backup, although tools summing logical folder sizes
may count linked files again. Only the shader package, small configuration copies
and runtime logs need additional storage. Link creation has no large-copy fallback.

Each launch refreshes the same view, detaching junctions without traversing their
targets. Retail updates therefore cannot leave stale linked binaries in use.
SHA-256 checks reject a modified shader package or a different retail shader source
version. Refresh refuses an unowned or redirected runtime directory and refuses
to run while KingdomCome is already active. Writable configs and logs are not
hardlinked back into the game.

## Use

After installing a package built with recipe 3, sign in to Steam and choose
**KCD1 Map → Launch mod** in the setup Library. It launches the original retail
binary with the real Steam app context (1771300); Steam authentication remains in
the unchanged game. The [Steamworks initialization contract](https://partner.steamgames.com/doc/sdk/api#initialization_and_shutdown)
requires the correct App ID and an owning account with Steam running.

Launching from the ordinary Steam entry continues to use retail's original
Engine archives. The custom launcher enables the modified shared shaders for
that entire game session; folder isolation does not restrict their effects to
KCD1 materials. Same-scene rendering and other-mod compatibility need playtesting.

For developer-only bounded startup checks, the setup-bundled helper supports
`runtime/launch_with_shaders.ps1 -ModDirectory <installed-mod> -StartupCheck`.
It starts hidden with `+quit`, verifies
Steam initialization and all four archive mount messages, and requires a clean
exit. It never loads a save or starts a level. `-PrepareOnly` checks/builds the
filesystem view without launching the game.

## Observed evidence

Tested against retail `release_1_5_1308617_856`, configuration
`MasterMasterSteamPGO`, version 1.5.6. The initial attempt without Steam context
stopped before mounting; adding the correct Steam app context produced successful
Steam initialization, all four archive mounts, and exit code 0 after `+quit`.

The temporary probe and its linked runtime were under the real retail Mods folder.
The private root's shader files were checked with `samefile` against the compiled
mod package, and against the original Engine files to exclude accidental retail
fallback. Native Engine and Bin hashes were compared before and after. No game
save or level was loaded. The temporary probe was removed after collecting logs.

Evidence is retained in the existing job, not a new build:
`D:\BuildKCDMod\20261017-172936-164078d7\gameplay-validation\shaders\mount-evidence`.
This establishes startup mounting, not roof/GI/clothing visual correctness or full
campaign parity. New builds retain `runtime_verified=false` until separately tested.

## Compiler prerequisite and distribution

KCD1 Map setup requires the official **Kingdom Come: Deliverance II Modding Tools**
for builds, installs of existing packages, and resumed installs. Setup detects Steam
app 2429020 across libraries, accepts a selected folder, and checks ShaderCacheGen,
Resource Compiler, shader lists and engine DLLs before work. The **Install through
Steam** button opens Steam's installation flow; it does not download or redistribute
tool binaries itself. The selected path is preserved in the saved job and supplied
to the build worker. Fishing alone does not need the shader toolchain.

Warhorse's [shader build instructions](https://warhorse.youtrack.cloud/articles/KM-A-82/Building-shader-cache)
state that retail KCD2 ships precompiled shaders and has no shader compilation step.
This converter uses ShaderCacheGen plus Resource Compiler to produce all four native
archives; a general HLSL compiler alone is not an implemented replacement.

The [Modding Tools EULA](https://store.steampowered.com/eula/2429020_eula_0) prohibits
distributing any part of the tools. No permission to bundle Warhorse's compiler has
been established; separate permission would be needed before redistributing it.
Only our orchestration code is bundled with setup. Playing an already compiled
installation through **Launch mod** does not invoke or require the SDK.
