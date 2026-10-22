# Release, source and runtime status

Reviewed on **22 October 2026 (UTC)** against committed source
[`a9a40cd`](https://github.com/SamG-Coder/KingdomComeGlueMapper/commit/a9a40cd3030b7dc8ca023d7c1718cc14d4e0672f).
Some linked development records use 23 October local dates. This is a bounded
documentation review of source and recorded evidence, not a new game playtest.

## Choose the right version

| Reference | What it establishes | What it does not establish |
| --- | --- | --- |
| [Published Setup v0.3.16](https://github.com/SamG-Coder/KingdomComeGlueMapper/releases/tag/v0.3.16), published 21 October 2026 | A Windows x64 prerelease executable, checksum file and packaged self-test report are available. Its tagged source is `9881163`, recipe 40. | Later commits are not included merely because their setup version string is also 0.3.16. |
| Reviewed source `a9a40cd`, recipe 51 | Later conversion and upgrade implementations are present in the source tree. | A source implementation or a successful package build is not proof of released availability or in-game behavior. |
| Dated runtime records | Acceptance of the specific build, location and behavior described in each record. | Whole-map, every-NPC, all-quest or save/load acceptance outside the recorded test. |

The [Windows guide](windows-setup.md) is the installation starting point.
Use the executable under the release's **Assets** for the published build, or
follow [Run the current source](../README.md#run-the-current-source) for source
development. Keep the original job folder and its `job.json` for Resume.
Setup version, mod package version and gameplay recipe version are separate;
include the release/commit and package recipe when reporting a problem.

Recipe eligibility is defined by
[`build_recipe.py`](../tools/build_recipe.py) and
[`setup_package_upgrade.py`](../tools/setup_package_upgrade.py).
At the v0.3.16 tag, completed recipes 3-39 can migrate to 40. At the reviewed
source, completed recipes 3-50 can migrate to 51. Valid receipts and all required
validators must still pass. Direct installation requires the recipe expected by
the running setup; it does not migrate an older package or downgrade a newer one.

## Selected feature and acceptance boundaries

| Area | Implemented or packaged | Recorded runtime evidence / remaining work |
| --- | --- | --- |
| KCD1:MP export | v0.3.16 fixes reserved scenery entity IDs; scene preparation retained 19,043 visual entities. | Export preparation and packaged self-test passed. Player initialization, traversal and two-client synchronization remain unverified. See [release notes](releases/v0.3.16.md) and [multiplayer acceptance](kcd1-mp-setup.md#acceptance-boundary). |
| Imported level startup | Setup's private runtime supplies canonical level paths as well as mod shaders. | User-confirmed NPC behavior recovery on 20 October after launching through setup. Use **Launch mod**, including for diagnostics; see [startup audit](retail-npc-startup-audit-2026-10-20.md). |
| Town benches and NPC sleep | Later source adds generic schedule/seating and sleep conversion; these changes postdate v0.3.16. | Sampled retail behavior was user-confirmed on 22 October. Contention, interruptions, all actors and save/load remain separate checks. See [bench playtest](city-bench-work-playtest.md) and [sleep playtest](npc-sleep-playtest.md). |
| Fence repair and home rest | Later source converts bounded source-linked activities; targeted packages were installed in retail. | Installation and structural validation do not establish behavior. Their records still require runtime observation: [fence repair](fence-work-playtest.md), [home rest](home-rest-playtest.md). |
| Designer collision and barriers | Conversion of supported initial-world volumes was merged after v0.3.16. | Fresh-build player/horse traversal, water and map-edge barriers, monologues and normal routes still require the checks recorded in the [conversion review](https://github.com/SamG-Coder/KingdomComeGlueMapper/pull/43#pullrequestreview-5604765913). Source conversion does not close every reported collision problem. |
| Starting torch and trainer invitation | Recipe 51 adds the new-game torch and source invitation/departure adapters. | Automated and offline package checks are recorded; the new behavior has not been live-tested. The complete combat lesson remains outside this slice. See [quest inventory](source-quest-inventory.md#new-game-torch--23-october-2026) and [introduction audit](quest-introduction-activities.md). |
| Stale LOD repair and install reuse | Later source can repair supported stale sections from matching saved evidence and reuse verified installed files during staging. | Tests cover bounded repairs and transactions. This is not arbitrary corrupt-package recovery or a gameplay acceptance claim. Keep the original workspace; see [repair requirements](stale-section-repair.md). |

The [README feature checklist](../README.md#feature-checklist) covers broader
world conversion. Its checkmarks mean the stated implementation exists, not that
every object has passed runtime acceptance. The full KCD1 campaign and KCD1 save
migration remain unfinished; multiplayer scenery export does not convert quests
into cooperative gameplay.

The [quest checklist](quest-checklist.md) is a historical checkpoint. Use the
newer linked audits for later work, retaining their explicit pending checks.
No new runtime acceptance is inferred from this documentation update.

## Performance evidence

[PR #45](https://github.com/SamG-Coder/KingdomComeGlueMapper/pull/45), merged
22 October after v0.3.16, reports a complete 1,220-tile **Buildings** bake on a
24-thread machine with 64 GB RAM and an RTX 5090 32 GB. Its standalone default
two-heavy-slot run took 23.5 minutes, with all tile hashes matching the serial
baseline. A separate cold build reported 94 minutes for map conversion, baking
and finalization, including a 24.1-minute bake with an empty lighting cache.

These are contributor measurements for the stated source/build configuration.
They are not fresh-install timings for every later recipe, measurements of
**All (Forest)**, or a promise that the published v0.3.16 executable includes
the parallel tile change. Compare like-for-like hardware, cache state, selected
coverage and measured stages before drawing conclusions about setup duration.
