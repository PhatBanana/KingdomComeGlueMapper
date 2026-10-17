# Windows setup — 0.3.2

Download `KingdomComeGlueMapper-Setup-0.3.2-win64.exe` from [GitHub Releases](https://github.com/SamG-Coder/KingdomComeGlueMapper/releases). This is an experimental prerelease. Python and the game modding tools are not required to run the executable. Microsoft Edge WebView2 is required for its local interface.

## Choose a mod

| Mod | Package version | Required games | What it installs |
| --- | --- | --- | --- |
| KCD1 Map | 0.2.0-alpha.4 | KCD1 and KCD2 1.5.6 | Converted Rattay region, coach travel, supported interactions and services, Rattay smithing, church prayer, containers and test supplies. |
| KCD2 Fishing | 0.3.0 | KCD2 1.5.6 | Standalone fishing in Trosky and Kuttenberg; also includes converted-map water when built with KCD1 Map. |

The setup version and mod package versions are separate. KCD1 Map does not convert a complete playable campaign or KCD1 saves. Standalone fishing's native-region runtime validation remains pending.

## Install step by step

1. Install the required games. Run the setup executable as your normal Windows user in writable folders.
2. In **Library**, select one or both mods, then **Configure installation**.
3. **Locations:** confirm detected Steam paths or browse to each game's main folder. Choose a build folder outside the games, such as `D:\KCDModBuilds`. Select **Build & install**. Use **Build packages only** to create packages without installing them.
4. **Baking:** choose a mode from the table below. Baking follows the complete map conversion and gameplay packaging. It does not run during the early tree/vegetation conversion step.
5. **Cutscenes:** leave the optional opening movie off, or locate your installed RAD Video Tools encoder and enable it. FFmpeg and FFprobe must be on PATH. Setup does not download RAD. The optional movie currently replaces the shared New Game intro, including ordinary KCD2 New Game. Later campaign scenes are not included.
6. **Review:** check paths, selected mods and options. Close the games before installation, then start.
7. **Activity:** all planned steps appear up front. The current task reports progress when measurable. Overall stage counts are not time percentages. An ETA only appears where throughput can be measured.
8. Wait for **Selected mods installed**. Launch KCD2 normally.

### Lighting choices and space

| Mode | Scope | Extra build-space allowance |
| --- | --- | --- |
| No Baking | Keeps the normal conversion lighting configuration; skips the additional surface bake. | None |
| Buildings | Structures, static props, ground and roads; forest instances excluded from this pass. | 30 GiB |
| All (Forest) | Buildings coverage plus eligible trees and foliage. | 60 GiB |

All modes include visible buildings and vegetation. Baking prepares surface data for indirect illumination. It does not build or clear the game's shader cache. The bake uses the CPU and remains experimental, including approximations for layered materials and foliage.

A fresh map build reserves **200 GiB** in the build location and **64 GiB** for installation staging. Add the chosen bake allowance and another **10 GiB** for the optional movie. Requirements combine when build and game folders share a drive. Fishing alone needs approximately 1 GiB for build and staging. Existing builds and backups already consume space and are retained.

The measured local map conversion took **43 minutes 10 seconds**, excluding optional baking. The previously reported 190.5-second bake ended with an error and was not a completed bake. Full-world bake time is not yet established; CPU, storage, available memory and selected coverage affect duration.

## Continue a failed setup

1. Keep the original job folder and its output.
2. Stop any older setup run for that job. Open this updated setup.
3. Go to **Activity → Resume failed setup…**.
4. Select the timestamped folder containing `job.json`, `package`, and `map-job`. Do not select `map-job`, `baking`, or the installed Mods folder.
5. Setup reads the saved options, verifies completed packages and resumes remaining operations. Watch the new attempt's log.

For a failure in optional baking, the completed map package is reused: the 43-minute conversion need not repeat. A completed movie or selected bake is skipped when its package receipt confirms completion. Compatible completed bake tiles are verified and reused. Missing or damaged tiles are rebuilt. Interrupted scene planning restarts that planning phase.

If map conversion failed before a complete package existed, the map phase restarts. Resume does not checkpoint every individual world-converter stage. Partial outputs remain for diagnosis. Modified or incomplete packages are rejected rather than treated as successful.

Each attempt gets separate `resume-<timestamp>-<id>` logs under the original job. Old cancellation requests do not apply to a new attempt. Remaining disk-space checks exclude already completed world conversion. If the final installation failed, resume retries the verified installation transaction; a previously installed first mod may be staged again when recovering a two-mod run.

Use **Cancel safely** rather than terminating the process. Cancellation waits for the current safe work boundary; some operations take time to finish. The next attempt can reuse completed packages and compatible bake tiles. Optional movie and bake work is prepared separately so failure leaves the verified map package available.

## Enter the map or fish

- **KCD1 Map:** continue a Trosky save, speak to the coachman and choose **Travel to the Rattay region**. The retail menu also offers **New Game Sasau region (In Progress)** as an experimental start.
- **KCD2 Fishing:** buy a rod from a general merchant after its stock refreshes. Having the rod in your inventory is enough. Face nearby water and use the contextual **Fish** action. Follow the casting and bite prompts; cancelling or moving ends fishing.

If the old map contains an embedded fishing test, standalone fishing installation is blocked. Build the clean map package before adding the separate fishing mod.

## Install existing packages

Choose **Install existing packages** and select the job's parent `package` folder, which contains `map` and/or `fishing`. The selected packages must match their receipts. This does not run conversion or change their bake settings.

## Logs and reporting problems

Use **Open log** and **Open folder** in Activity. The main `setup.log` and `events.jsonl` record selected-mod operations. `map-job/setup.log` records world conversion and gameplay packaging. `stage-times.json` records measured stage durations. Resume attempts have separate logs; include both the original error and the new attempt when reporting a problem.

Bake errors identify the affected mesh and scene plan. Setup 0.3.2 fixes the reported unbound burned-fabric mesh by recording its default-material binding while retaining its geometry. Failed stages are reported as failed, rather than misleadingly logged as finished.

When filing an issue, include setup version, selected mods and bake mode, game version, error text and relevant logs. Do not upload game archives or your complete converted package.

## Installation, backups and removal

The destinations are `<KCD2>/Mods/kingdomcomegluemapper` and `<KCD2>/Mods/kcd2fishing`. Setup stages and verifies files before replacing recognized installations. Previous installations and mod-order backups are retained under `<KCD2>/GlueMapper Backups`. Modified or unknown installations block replacement. The game archives and saves are not overwritten.

To roll back, close the game, move the current mod to a safe location, restore its chosen backup to the original Mods path, and restore the corresponding `mod_order.txt` backup if necessary. To disable a mod, move its folder outside Mods and remove its line from `mod_order.txt` if that file exists. Keep unrelated entries. Retain backups until the new build works for you.

Build folders, unsuccessful attempts and backups are not automatically deleted. Remove them only after you no longer need recovery or comparison. Shader caches are not cleared by setup.

## Build from source

On Windows x64, Python 3.13 avoids compiling the pinned xatlas dependency:

```powershell
py -3.13 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-setup.txt
.venv/Scripts/python.exe -m pip install -r requirements-test.txt
.venv/Scripts/python.exe -m unittest discover -s tests
.venv/Scripts/python.exe tools/build_setup_exe.py
```

Python 3.14 also works when the Visual Studio C++ build tools are available to build `xatlas==0.0.11` from source. That version of xatlas has a Windows cp313 wheel but no cp314 wheel; a missing wheel is not a Python 3.14 incompatibility. The parallel CPU baker supports both Python versions.

Outputs include the EXE, SHA-256 checksum and frozen-runtime self-test report. GitHub Actions is manual-only; a push or release tag does not automatically run tests. Frozen checks validate included resources, native extensions and a small CPU raster job; they do not substitute for a complete bake or in-game playtest.

See [launcher implementation details](setup-launcher.md) and [region travel](region-travel.md) for further scope and limitations. The release distributes setup code and interface assets, not converted game archives.
