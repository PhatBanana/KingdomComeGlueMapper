# Windows setup — 0.3.4

Download `KingdomComeGlueMapper-Setup-0.3.4-win64.exe` from [GitHub Releases](https://github.com/SamG-Coder/KingdomComeGlueMapper/releases/tag/v0.3.4). This is an experimental prerelease for Windows x64. Python is bundled; Microsoft Edge WebView2 is required for the local interface.

**KCD1 Map requires the official KCD2 Modding Tools from Steam before building, installing an existing package, or resuming installation.** Setup detects the tools and offers Browse, Recheck, and Install through Steam. It uses your installed tools to compile shaders; Warhorse's tools are not bundled. Fishing alone does not require them.

Recipe 3 connects the bounded Skalitz opening, selected actors and routines, initial equipment, conversations, quest combat, and final streaming checks to the normal setup build. The redesigned interface groups locations and prerequisites, with one persistent navigation bar. The parallel conversion changes from PR #28 include bounded worker pools, concurrent package reads and hashing, and a workspace lighting cache.

Compiled shader archives stay under the mod's `ShaderCache` folder. **Launch mod** in the setup Library prepares one reusable linked runtime inside Mods and starts the unchanged retail executable. Retail Engine archives are not replaced. See [mod-contained shader loading](mod-shader-loading.md) for the mechanism and validation limits.

## Choose a mod

| Mod | Package version | Required games | What it installs |
| --- | --- | --- | --- |
| KCD1 Map | 0.2.0-alpha.4 | KCD1, KCD2 1.5.6, and official KCD2 Modding Tools | Converted Rattay region, coach travel, supported interactions and services, plus the bounded Skalitz opening/gameplay recipe. |
| KCD2 Fishing | 0.3.0 | KCD2 1.5.6 | Standalone fishing in Trosky and Kuttenberg; also includes converted-map water when built with KCD1 Map. |

The setup version and mod package versions are separate. KCD1 Map does not convert a complete playable campaign or KCD1 saves. Standalone fishing's native-region runtime validation remains pending.

## Install step by step

1. Install the required games and, for KCD1 Map, the official KCD2 Modding Tools through Steam. Run the setup executable as your normal Windows user in writable folders.
2. In **Library**, select one or both mods, then **Configure installation**.
3. **Locations:** confirm detected Steam paths or browse to each game's main folder. Check that KCD2 Modding Tools are detected. Choose a build folder outside the games, such as `D:\BuildKCDMod`. Select **Build & install**, or **Build packages** to prepare files without installing them.
4. **Lighting:** choose a mode from the table below. Surface baking follows the map conversion and gameplay packaging. It does not run during the early tree/vegetation conversion step.
5. **Opening movie:** leave the optional movie off, or locate your installed RAD Video Tools encoder and enable it. FFmpeg and FFprobe must be on PATH. Setup does not download RAD or open a file picker until you choose to locate it. The optional movie currently replaces the shared New Game intro, including ordinary KCD2 New Game. Later campaign scenes are not included.
6. **Review:** check paths, selected mods and options. Close the games before installation, then start.
7. **Activity:** all planned steps appear up front. The current task reports progress when measurable. Overall stage counts are not time percentages. An ETA only appears where throughput can be measured.
8. Wait for **Selected mods installed**. With Steam running, select **KCD1 Map → Launch mod** in Library to use the compiled mod shaders. Fishing alone can use the ordinary Steam launch.

### Lighting choices and space

| Mode | Scope | Extra build-space allowance |
| --- | --- | --- |
| No Baking | Keeps the normal conversion lighting configuration; skips the additional surface bake. | None |
| Buildings | Structures, static props, ground and roads; forest instances excluded from this pass. | 30 GiB |
| All (Forest) | Buildings coverage plus eligible trees and foliage. | 60 GiB |

All modes include visible buildings and vegetation. Optional surface baking prepares data for indirect illumination; the separate shader compilation stage runs for every fresh KCD1 Map build, including No Baking. Setup does not clear retail shader caches. The surface bake uses two compiled CPU workers for tiles below one million triangles, persistent OptiX for dense tiles, and 64-brick GPU batches with CPU preparation/encoding overlap. GPU failures fall back to CPU with the reason recorded. Baking remains experimental, including approximations for layered materials and foliage.

The bundled GPU binary currently targets `sm_120` (the tested development GPU). Other architectures or unsupported drivers use the CPU fallback; broader GPU compatibility has not been validated. The executable includes the GPU DLL, PTX, integrity metadata and OptiX license. Users do not need the CUDA toolkit to run setup.

A fresh map build reserves **200 GiB** in the build location and **64 GiB** for installation staging. Add the chosen bake allowance and another **10 GiB** for the optional movie. Requirements combine when build and game folders share a drive. Fishing alone needs approximately 1 GiB for build and staging. These are planning allowances, not final installed sizes. Existing build folders and older backups are not automatically removed. Successful map replacement retains no additional full-mod backup.

End-to-end timing for recipe 3, including its additional gameplay and shader stages, is not established. Earlier 43-minute conversion measurements predate this recipe. PR #28 includes contributor measurements for its parallel conversion changes, with warm-cache caveats; they are not a timing guarantee for this release. CPU, storage, memory, shader compilation, and selected coverage affect duration.

## Continue a failed setup

1. Keep the original job folder and its output.
2. Stop any older setup run for that job. Open this updated setup.
3. Go to **Activity → Resume failed setup…**.
4. Select the timestamped folder containing `job.json`, `package`, and `map-job`. Do not select `map-job`, `baking`, or the installed Mods folder.
5. Setup reads the saved options, verifies completed packages and resumes remaining operations. Watch the new attempt's log.

For a failure in optional baking, a completed map package from the current recipe is reused. A completed movie or selected bake is skipped when its package receipt confirms completion. Compatible completed bake tiles are verified and reused. Missing or damaged tiles are rebuilt. Interrupted scene planning restarts that planning phase.

**Packages from older setup recipes must be rebuilt with 0.3.4.** Resume and installation reject receipts missing the current gameplay, streaming, or shader validations. The setup does not silently treat an older hash-valid package as a complete current build.

If map conversion failed before a complete package existed, the map phase restarts. Resume does not checkpoint every individual world-converter stage. Partial outputs remain for diagnosis. Modified or incomplete packages are rejected rather than treated as successful.

Each attempt gets separate `resume-<timestamp>-<id>` logs under the original job. Old cancellation requests do not apply to a new attempt. Remaining disk-space checks exclude already completed world conversion. If the final installation failed, resume retries the verified installation transaction; a previously installed first mod may be staged again when recovering a two-mod run.

Use **Cancel safely** rather than terminating the process. Cancellation waits for the current safe work boundary; some operations take time to finish. The next attempt can reuse completed packages and compatible bake tiles. Optional movie and bake work is prepared separately so failure leaves the verified map package available.

## Enter the map or fish

- **KCD1 Map:** use **Launch mod** in the setup Library, then continue a Trosky save, speak to the coachman and choose **Travel to the Rattay region**. The retail menu also offers **New Game Sasau region (In Progress)** as an experimental start. Launching through the ordinary Steam entry uses the original retail Engine shaders. The custom launcher changes the shared shaders for the entire game session; other regions and mods still need compatibility testing.
- **KCD2 Fishing:** buy a rod from a general merchant after its stock refreshes. Having the rod in your inventory is enough. Face nearby water and use the contextual **Fish** action. Follow the casting and bite prompts; cancelling or moving ends fishing.

If the old map contains an embedded fishing test, standalone fishing installation is blocked. Build the clean map package before adding the separate fishing mod.

## Install existing packages

Choose **Install existing packages** and select the job's parent `package` folder, which contains `map` and/or `fishing`. The selected packages must match their receipts and the map must have completed recipe 3. The official Modding Tools are required for map installation even when compilation was already completed. This operation does not rerun conversion or change bake settings.

## Logs and reporting problems

Use **Open log** and **Open folder** in Activity. The main `setup.log` and `events.jsonl` record selected-mod operations. `map-job/setup.log` records world conversion and gameplay packaging. `stage-times.json` records measured stage durations. Resume attempts have separate logs; include both the original error and the new attempt when reporting a problem.

Bake errors identify the affected mesh and scene plan. Setup 0.3.3 fixes the reported unbound burned-fabric mesh by recording its default-material binding while retaining its geometry. Failed stages are reported as failed, rather than misleadingly logged as finished.

When filing an issue, include setup version, selected mods and bake mode, game version, error text and relevant logs. Do not upload game archives or your complete converted package.

## Installation, backups and removal

The destinations are `<KCD2>/Mods/kingdomcomegluemapper` and `<KCD2>/Mods/kcd2fishing`. Setup stages and verifies files before replacing recognized installations. Map replacement keeps rollback data only during the transaction, then removes it on success. Standalone Fishing still retains its previous installation and mod-order backup under `<KCD2>/GlueMapper Backups`. Modified or unknown installations block replacement. Retail game archives and saves are not overwritten.

To disable a mod, close the game, move its folder outside Mods, and remove its line from `mod_order.txt` if that file exists. Keep unrelated entries. Launch KCD2 through Steam to use its original Engine shaders. The linked `.kingdomcomegluemapper-runtime` folder is generated by Launch mod and can be refreshed by the launcher; it contains junctions to game assets, so do not use a cleanup tool that traverses junction targets.

Existing build folders, unsuccessful attempts, and backups from earlier versions are not automatically deleted. A successful map install no longer creates a permanent rollback copy; regenerate the desired version from source or keep a verified package when recovery is needed. Setup does not clear retail shader caches.

## Build from source

Setup 0.3.6 can resume completed recipe 3 through 5 packages and upgrade them without
repeating world conversion. It finishes or reuses the existing `kcd1_travel`
bake checkpoints first, then updates the campaign start guard, removes the old
horse-recovery hook, reconciles smart-area registrations, and removes compiled
smart-area geometry duplicates while preserving their inline shapes. These
area changes passed the user's Mod Tools return-travel test; retail and broader
save/companion coverage remain separate acceptance checks.

Only `kcd1_travel` is baked and retained in the final package. `kcd1_rataje` is
an intermediate conversion input; its packaged directory and level registration
are removed while the playable level ID remains unchanged. Successful bake and
upgrade swaps remove their temporary rollback directories. Existing historical
builds and checkpoints are not deleted automatically.

Use **Resume failed setup** in the new executable and select the original job
folder containing `job.json`. A safely cancelled or completed job can also be
selected. Stop the previous setup worker first. The upgrade runs before install;
choosing **Install packages** directly does not migrate an older recipe.

On Windows x64, Python 3.13 avoids compiling the pinned xatlas dependency. Building the GPU payload also requires Visual Studio C++ build tools and the CUDA toolkit; users of the finished setup do not need these build tools:

```powershell
py -3.13 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-setup.txt
.venv/Scripts/python.exe -m pip install -r requirements-test.txt
.venv/Scripts/python.exe -m unittest discover -s tests
./tools/build_voxel_cuda.ps1 -Optix
.venv/Scripts/python.exe tools/build_setup_exe.py
```

Python 3.14 also works when the Visual Studio C++ build tools are available to build `xatlas==0.0.11` from source. That version of xatlas has a Windows cp313 wheel but no cp314 wheel; a missing wheel is not a Python 3.14 incompatibility. The parallel CPU baker supports both Python versions.

Outputs include the EXE, SHA-256 checksum and frozen-runtime self-test report. GitHub Actions is manual-only; a push or release tag does not automatically run tests. Frozen checks validate included resources, native extensions, GPU payload hashes and a small CPU raster job. They also run a small OptiX bake against the CPU reference and report GPU availability explicitly; they do not substitute for a complete bake or in-game playtest.

See [launcher implementation details](setup-launcher.md) and [region travel](region-travel.md) for further scope and limitations. The release distributes setup code and interface assets, not converted game archives.
