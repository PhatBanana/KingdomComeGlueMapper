# Opening dependency coverage

Scope confirmed by the user: New Game through the Skalitz attack. Escape to
Talmberk and later campaign quests are outside this pass. Source quest states,
profile activation, dialogue conditions and NPC work requests determine when
dependencies run; discovery does not grant permission to activate everything.

## Source-backed discovery, 14 October 2026

The source `q_skalitz_normal` profile contains 55 placed NPC candidates across
73 layers. The installed development build has seven of those instances; 48
are missing. These counts concern exact SoulList instance/entity identities,
not characters that merely share a dialogue role. Some profile records still
need source eligibility/appearance resolution before they can be installed.

Including the source `q_skalitz_attack` profile produces 120 distinct placed
instances, of which 113 are absent from the installed build. The source
`cutscene_navsteva_racka` enables the attack profile and disables the normal
profile. Combining their actor assets must preserve that transition; their
population must not all be spawned at New Game. The current appearance stage
covers only the normal profile.

Dialogue ownership reduces the initial 94 candidate roots to 85. Explicit
controller calls to another subchapter remain dependencies, as do unowned
branches. This is not proof that all 85 execute before attack onset. Their
conditions and call sites must remain intact.

The generic importer now discovers actors referenced by response speakers and
command actors/targets, in addition to declared topic participants. Optional
source-profile filtering prevents an opening actor dependency from selecting
every later-game or DLC soul sharing that role. Profile membership is resolved
through GameProfile layers and persistent entity/SoulList identities, never
through prefixes in character names.

The complete profile schedule scan contains 32 unresolved daily intervals and
one quest-controller work target that the area-only planner cannot yet resolve.
The latter is the coal seller's authored `varlet_sellPlace` request. Missing
ordinary activity links also include NPCs whose work is assigned through quest
events. These require the original controller/event dependencies, not invented
daily destinations.

Resolved work identities include housework, farming, guard duty, shop work,
embroidery, blacksmithing, compound work camping and bartending. Only a subset
has native work adapters. Unsupported jobs now remain in the conversion receipt
with their original area, links and behavior identity instead of disappearing
from the report.

## Reproduce

```powershell
.venv/Scripts/python.exe tools/audit_quest_profile_dependencies.py `
  --source D:/SteamLibrary/steamapps/common/KingdomComeDeliverance `
  --mod D:/SteamLibrary/steamapps/common/KCD2Mod/Mods/kingdomcomegluemapper `
  --model outputs/OpeningStart/ControllerAudit10/quest-ir.json `
  --profile q_skalitz_normal `
  --output outputs/OpeningStart/SkalitzCoverage02/profile-dependencies.json
```

Use a fresh output path. The model hash and patched source-table provenance
are recorded in the report. `build_quest_people_test.py --source-profile NAME`
can stage the profile's actors while preserving existing registered people.
`build_actor_dialogues_test.py --discover-quests --quest-owned-scope` uses the
source subchapter boundary. These commands stage files. The actor test builder
writes mission placements, so its package must not be installed as a replacement
for conditional profile activation. The profile lifecycle remains a separate
conversion requirement; staging does not establish complete quest behavior.

## Remaining acceptance boundary

`outputs/OpeningStart/SkalitzProfileActors03` contains 38 newly converted actor
appearances and world registrations, preserves eight previously registered
quest/profile actors, and records ten appearance failures. Eight need clothing
opacity-mask generation; one has a nonvisual ring routed through mesh conversion;
one has no resolved source body. No substitution is counted as conversion.
The package is staged, not installed. New actors currently have the explicit
idle baseline until their full work programs are converted.

Static package validation confirmed all 33,030 existing mission entities remain
semantically unchanged, localization keys are unique, and the installed baseline
hashes have not changed. There are 41 staged PAK files. Regression validation:
253 campaign tests, 71 character tests and four dubbing/localization tests pass.
These checks do not establish in-game acceptance.

- [ ] Resolve every required opening actor, original outfit, inventory and tool.
- [ ] Preserve controller-driven work changes as well as daily activity clocks.
- [ ] Connect work programs, movement routes, reservations, animations and release.
- [ ] Convert errands, training, optional branches, hand-ins and failure paths.
- [ ] Bind voice recordings, speaker/reaction cameras and proximity dialogue.
- [ ] Preserve Henry's source state and quest-driven state changes.
- [ ] Convert forging scenes and the transition into the attack.
- [ ] Play from a fresh menu start through the attack, including save/load.

Actor packaging and dependency tests are not completion of this checklist.
The accepted Father greeting, skill check and forging behavior remain separate
live results documented in `quest-checklist.md`.
