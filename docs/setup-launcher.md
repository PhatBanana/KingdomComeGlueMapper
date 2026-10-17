# Setup 0.3.3

Run `KingdomComeGlueMapper-Setup-0.3.3-win64.exe`. The HTML/CSS/JavaScript interface runs locally in WebView2; a Python worker performs conversion and verified installation. Python is bundled in the EXE. Microsoft Edge WebView2 must be installed.

## Mod library

| Mod | Package version | Requirements | Description |
| --- | --- | --- | --- |
| KCD1 Map | 0.2.0-alpha.4 | Installed KCD1 and KCD2 1.5.6 | Converts the original landscape, buildings, vegetation and objects and adds coach travel to the Rattay region. The original campaign and saves are not converted into a complete playable campaign. |
| KCD2 Fishing | 0.3.0 | KCD2 1.5.6 | Standalone fishing for Trosky and Kuttenberg. Carry a rod, look at water and choose Fish. General merchants stock rods after a stock refresh. A KCD1 Map present during package construction also contributes its water data. Native-region runtime validation is still pending. |

## Wizard

Fresh KCD1 Map builds also include **New Game Sasau region (In Progress)** in
the retail main menu. It uses the native New Game route with destination level
1001 and needs no development runtime. The ordinary KCD2 New Game option remains
available. This exposes the experimental map start; it does not mean the clean
build contains the development installation's manually staged campaign scenes
or a completed KCD1 campaign. Coach travel remains available for existing saves.

1. **Locations:** find Steam installations or browse manually. Select a build directory outside either game. Choose Build & install, Build packages, or Install packages.
2. **Baking:** select optional KCD1 Map lighting preparation. This step is skipped for fishing alone or prebuilt packages.
3. **Opening movie:** optionally convert and install the complete original KCD1 opening with English audio and subtitles. RAD Video Tools is detected or located with a file dialog and remembered. FFmpeg/FFprobe must be on PATH. Setup runs extraction, AVI preparation, RAD encoding, output validation and subtitle/package merging before installation. Source resolution, frame count and frame rate are preserved. This replaces the shared New Game intro, including ordinary KCD2 New Game; later campaign scenes are not added. Allow another 10 GiB of working space. RAD is never bundled or downloaded automatically. Cancellation stops the current encoder process tree and preserves the partial build.
4. **Review:** inspect selected versions, paths and bake choice. Preflight checks game version, input files, space and installation ownership before a final start confirmation.
5. **Activity:** see conversion stages, current-task progress, elapsed time, throughput-based current-task ETA, completion checklist and logs. Estimates do not pretend to predict unmeasured later stages. Cancellation finishes the current safe unit of work; generated output is retained.

## Baking choices

| Choice | What setup does | Additional working-space allowance |
| --- | --- | --- |
| No Baking | Skip the extra static-surface lighting bake. Retain the normal conversion lighting configuration. | None |
| Buildings | Include structures, static props, ground and roads. Explicitly exclude forest instances from this surface pass. | 30 GiB |
| All (Forest) | Buildings coverage plus eligible trees and foliage with their original transforms. | 60 GiB |

Every choice installs visible buildings and vegetation. Baking prepares opacity, surface colour and normals for indirect illumination; it does not bake shader caches or prevent runtime shader compilation. Lighting remains dynamic. The optional surface bake uses automatic CPU/OptiX selection: two compiled CPU workers for smaller tiles, persistent OptiX for dense tiles, 64-brick batches and overlapping CPU preparation/encoding. GPU errors are logged and fall back to CPU. All tiles are validated before packaging. The current bundled GPU binary targets sm_120; other hardware uses CPU when unsupported. These are experimental presets: terrain blends and foliage translucency do not have proven native parity. Full-world setup duration has not been benchmarked. The allowances are conservative planning thresholds, not measured final package sizes.

Existing unrecognized/modified installations are refused. Fishing is not installed alongside the old embedded fishing experiment in a map package; migrate to a clean map package first. Each mod has a separate verified installation transaction and recoverable backup. If the second mod fails, the first successful installation remains.

## Development and validation

Clean development builds and the launcher use `desktop_setup.worker` and the
same `conversion_plan`. After world conversion and `region_travel`, both run
`build_recipe.run`: test gates, world containers and loot, Neuhof horse shop, starter supplies, Rattay
smithing and its coal repair, smithing dialogue, altar prayer, workshop recipes
and resources, and the retail New Game menu. Existing builders implement these
steps; the launcher does not maintain a second gameplay implementation.
Gate and smithing replacements verify original geometry at the reviewed
placements, so changes in generated `meshNNN` filenames do not break rebuilds.

The two reviewed building blend models (including their LODs) share the same
selection with the focused development repair. Other buildings retain the
established base conversion; unsupported secondary-detail atlas conversion is
not applied across the whole map.

You can rebuild repeatedly. Every launcher run gets a timestamped, unique job
folder and builds from the installed original game assets. It does not patch the
previous build repeatedly. A recipe receipt records completion and prevents
reapplying a partially completed recipe. Installation stages and verifies the
new package, then backs up and replaces the previous owned mod. Failed builds
leave the installed mod alone. Build folders and installation backups consume
disk space and are retained for inspection. Game shader caches are not deleted.
The complete recipe reserves 200 GiB of free build space and 64 GiB for a new
installation; optional baking and movie conversion add their stated allowances.
These include intermediate conversions, not just the final mod size. Existing
builds and backups already occupy disk space and are not automatically removed.

Optional lighting baking and opening-movie conversion follow this shared recipe.
Fishing remains a separately selected package. This recipe does not include
unreleased campaign-scene or clothing assembly experiments.

Install `requirements-setup.txt`, then run `python tools/setup_app.py` or build the GPU backend using `./tools/build_voxel_cuda.ps1 -Optix`, then build setup using `python tools/build_setup_exe.py`. The old interface remains available with `--legacy-ui`. Use `--mods-worker job.json` for the same background build pipeline. Receipts include hashes and bake settings. Do not distribute game-derived packages.

The library uses fresh user-supplied in-game screenshots in `setup-ui/assets`, with simple HTML title labels. Earlier generated crest artwork is retained as an unused design draft; its prompts are recorded in `setup-ui/assets/artwork-prompts.txt`.

## Resume a failed or cancelled setup

In **Activity**, choose **Resume failed setup…** and select the original timestamped job folder containing `job.json`. You can close and reopen setup first. Resume uses the saved mod selection, game paths, baking preset and movie choice; it does not use changed wizard settings.

Setup verifies the completed map package against its receipt before reusing it. A failure during optional baking therefore does not repeat the map conversion. Completed movie conversion and the selected bake are skipped when their receipts are present. Compatible completed bake tiles are checked before reuse; missing or damaged tiles are rebuilt. Interrupted scene planning restarts that planning phase. An interrupted map conversion without a verified complete package restarts the map phase, not individual world-converter steps.

Each retry writes separate logs under `resume-<timestamp>-<id>` inside the original job. Original logs and partial outputs remain. An old cancellation request does not cancel the new attempt. A job lock prevents two current setup workers from resuming the same job simultaneously. Stop an older setup application before selecting its job.

Optional movie and bake work is prepared separately before replacing the private package. A failed optional stage leaves the last verified package available. Installation still stages and verifies a package before replacing an owned mod. Changed or incomplete receipts stop recovery with an error; setup does not silently bless changed files. If installation itself failed, resuming retries its verified transaction. Already completed installations may be verified and staged again when both mods were selected.

Keep the original job folder until you finish. Do not select `map-job`, `baking`, or the game Mods folder. Resume checks space for remaining optional work and installation staging instead of reserving the whole world-conversion budget again.
