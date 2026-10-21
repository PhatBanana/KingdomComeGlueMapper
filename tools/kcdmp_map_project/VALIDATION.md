# Validation of this patch project

Date: 20 October 2026.

## Completed

**34 automated tests passed** on Python 3.12. The project requires Python 3.11+
and uses only its standard library. Both optional original-distribution checks
were enabled in this run.

| Area | What was checked |
| --- | --- |
| Complete export | Built a synthetic combined GlueMapper package through the real exporter, templates, registration generator and receipt verifier. Source game/conversion/distribution bytes were unchanged. |
| Mixed asset archives | Retained asset payloads byte-for-byte while removing campaign/player/menu resources. Checked pure archives remain entirely identical. Rejected nested uncleaned level overrides. |
| Scene metadata | Native player record preserved; NPC/quest/controller metadata removed; furnishings converted to inert models; transforms, GUIDs and surviving links checked; initial-layer handling and reserved player IDs checked. |
| Table mounting | Sole custom LevelId 1001 registration and new-mod aliases contain the final cleaned table schemas, including helper-animation cleanup. |
| Spawn | Explicit coordinates and actual authored-marker fallback reach scene, server TOML and Lua; quaternion heading is converted to degrees. |
| Steam / Store selection | Validated the exact launcher-selected executable/DLL directory. A supported backup/dev-folder DLL cannot certify an unsupported active engine. |
| Launcher | Correct online/offline/server argv and working directory; comma-delimited spawn; inherited KCDMP environment overrides removed; no updater or build-check bypass requested. |
| Recovery | Exact original mod order including BOM/CRLF, absent-order restoration, failed staging, failed final write, interruption after mod-order replacement, preservation of later user edits, and refusal to overwrite an existing target. |
| Uploaded distributions | ZIP sizes, SHA-256s, entry counts and inspected executable/DLL fingerprints match `evidence/inspected-packages.json`. Reads only; no attached executable was run. |

The authored Lua template was also parsed and exercised against mocked
documented API functions with the system Lua 5.4 library: init/story flag,
spawn callback, own-player teleport, dead-player respawn, position diagnostics
and command fall-through were checked. The TOML template parses after numeric
substitution.

The repository-addition patch is checked with `git apply --check` against the
inspected GlueMapper commit, and the delivered ZIP is checked for archive
integrity. The ZIP includes the source and tests needed to reproduce checks.

## Reproduce

From the extracted project directory:

```bat
py -3 -m unittest discover -s tests -v
```

To include the optional distribution tests:

```bat
set "KCDMP_TEST_CLIENT_ZIP=D:\Downloads\KcdMp-0.44.0-win-x64.zip"
set "KCDMP_TEST_SERVER_ZIP=D:\Downloads\KcdMp-server-0.44.0.zip"
py -3 -m unittest discover -s tests -v
```

Without those variables, the one distribution test is explicitly skipped.
Synthetic fixtures contain no game assets or executable third-party binaries.

## Not verified

The attached files contained KCDMP distributions, not the user's complete
converted map or a runnable KCD2 installation. Consequently these checks do
**not** prove that the custom scene creates the local actor, finishes loading,
renders correctly or synchronizes two players.

The first real acceptance gate is `KcdMp_ready kcd1_travel`, followed by the
server mode's `<player> spawned on kcd1_travel ...` message. Then test movement,
ground collision, materials, baked GI/HLOD and a second client. The bridge
reports `runtime_verified: false` until that work is actually performed.

Campaigns, quests, native NPC simulation, synced interactive furnishings,
server world-data exports and persistence are outside the map-loading scope.
