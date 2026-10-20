# Retail NPC startup and movement audit

## Confirmed startup failure

The user reported that all NPCs remained idle, did not flee when hit, but
could still participate in conversations. On 20 October 2026 the user
confirmed that launching through setup restored working behavior.

The failed diagnostic sessions had started the ordinary retail executable
directly, bypassing setup's private runtime. Their logs mounted the converted
level at `mods/kingdomcomegluemapper/data/levels/kcd1_travel`, while the level's
serialized `AI/LevelPath` was `data/levels/kcd1_travel`. The ordinary retail
`Data/Levels` directory did not contain that custom level.

Setup's launcher already projected custom levels into the canonical private
`Data/Levels` directory, following commit
`623d7e0d763df619fcad9f1a10dc8cd0f5858b1b`. The successful setup-launched session
reported the matching `data/levels/kcd1_travel` mount. The regression in these
tests was bypassing that launcher. Removing the new character LOD archive
did not fix the direct-launch session.

Successful Lua initializer entry/exit messages alone did not establish that
the engine could resolve the level-local AI data. Similarly, Mother holding
a broom did not prove that movement to her activity had succeeded: the job
can set up its hand content separately.

## Changes

`tools/setup_launch.py` now exposes a diagnostic CLI that uses the same
PowerShell helper and private runtime as setup:

```powershell
.venv\Scripts\python.exe tools\setup_launch.py --target "D:\SteamLibrary\steamapps\common\KingdomComeDeliverance2" --development
```

`runtime/launch_with_shaders.ps1` accepts the optional development flag.
Normal setup launch behavior is unchanged. Diagnostics must use this entry
point instead of starting the ordinary retail executable directly.

`tools/npc_runtime_paths.py` compares the packaged AI path with an existing
engine log. It is read-only and explicitly does not treat matching paths as
proof of working schedules.

Two additional conversion defects were corrected during the code audit:

* Detached job destinations could retain parent-local coordinates. The new
  `character_person.world_entity` resolves parent chains, including parents
  in other layers, composes position/rotation/scale, and removes parent
  references only after obtaining the world transform. Arrival, market,
  station, city-work and blacksmith adapters use it. Missing or cyclic
  parents fail explicitly. Unparented transforms are preserved.
* Schedule writers could bind jobs while relying on an earlier package to
  supply their program resources. `character_schedule_jobs.job_resources`
  emits the resources required by the actual schedules, including sweeping
  on existing actors and station definitions. Population and individual
  schedule builders now use it.

These two defects have automated regression coverage. They are not asserted
to explain the all-NPC startup freeze, and their changed routes still need
in-game validation.

## Audit scope

Whole-file inspection covered the character schedule, job binding, person
registration, activity, route, work-path, work-item, blacksmith, market,
station, city-work, capability and world-AI modules; population builders;
campaign behavior/scheduling/AI registration, actor placement, navigation,
path parameters, entity links, doors and start policy; static navigation
profiles; animal population/templates and wildlife; player animation updates;
setup launch, the PowerShell runtime launcher, package migration and travel
package composition. Larger files were read in consecutive sections.

The audit did not justify disabling AI, suppressing errors, forcing character
detail, or introducing a substitute scheduler. Existing animal navigation,
animation-queue overflow and performance reports are separate outstanding
runtime investigations. The native-training modules committed alongside this
work remain staged integration work, not a claim of a finished fencing lesson.

## Validation

* Eight tests in `test_npc_path_audit.py` cover parent transforms, cross-layer
  ancestry, invalid ancestry, required job resources and log/path comparison.
* The setup-launch regression checks that development diagnostics and
  prepare-only mode use the same runtime helper.
* Full discovery ran 1,506 tests, with 17 skipped. Six launcher tests initially
  failed because the real game was running and the launcher's safety guard
  refused preparation. All six passed when rerun after the game had closed.
* The user confirmed that setup launch restored working NPC behavior. This
  is the runtime evidence for the startup diagnosis; automated package tests
  alone would not establish it.

No game was relaunched and no installed game archives were replaced during
this code audit. The source changes do not imply that a new setup executable
has been built or a release published.
