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

The updated complete profile schedule scan resolves 46 daily intervals, with
21 unresolved intervals and no planner exceptions. The planner uses the shared
source link parser for bare, quoted and parenthesized job names and resolves
quest-controller work targets, including the coal seller's `varlet_sellPlace`.
Controller callbacks, behavior conditions and priorities remain in the plan;
resolving them is not runtime dispatch. Missing
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

`outputs/OpeningStart/SkalitzProfileActors04` contains 48 newly converted actor
appearances and world registrations, preserves eight previously registered
quest/profile actors, and has no pending appearance failures. The ten previous
failures rebuilt under `outputs/OpeningStart/SkalitzAppearanceRepair01`:

- Eight female outfits now generate missing coverage from converted diffuse
  alpha. Opaque textures can prove full coverage; cutouts use the converted
  mesh UVs and material subsets at ray intersections. Every bilinear footprint
  must pass the alpha threshold in every mip. This conservatively retains skin
  near transparent edges, rather than hiding it through a fabric opening.
- Authored nonvisual accessories retain a native equipment component, source
  item stats/text and clothing-preset membership. A ring is no longer sent to
  the skin loader as an empty mesh path.
- An actor without a modular body definition uses the explicit body attachment
  in that actor's source CDF. The CDF asset provenance is retained. No unrelated
  body or outfit is substituted.

The package is staged, not installed. New actors currently have the explicit
idle baseline until their full work programs are converted.

Static package validation confirmed all 33,030 existing mission entities remain
semantically unchanged, localization keys are unique, and the installed baseline
hashes have not changed. Regression validation:
253 campaign tests, 75 character tests, nine clothing coverage tests and four
dubbing/localization tests pass.
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

## Work program conversion follow-up

The shared importer now discovers SmartObject sibling behaviors and brain
request/update/release callbacks as well as SmartArea callbacks. Tool programs
can therefore enter the dependency graph through their registry, rather than
only through explicit `IncludeTree` nodes. A registry match remains a candidate;
it is not proof that a particular placed object can execute that behavior.

Added native operation adapters preserve route reservations (`AddLink` and
`RemoveLink`), path-existence queries and filters, held-item checks and path
traversal measurements. Item/slot class filters require a registered item GUID.
Structured link data retains named, typed fields, including contextual work
requests. Unknown fields, invalid scalar types and out-of-range integers fail
conversion. The engine-owned `predefinedPathParams` record uses the native type
and explicit source defaults instead of an incompatible namespaced copy.

`character_work_paths.py` validates the complete version-38 predefined-route
table in `ubernav.tmm`. Campaign entity conversion retains route GUIDs and
depends on navigation registration. It does not approximate a route from an
entity's single position or replace its authored vertices.

Live-file evidence in `outputs/OpeningStart/WorkPrograms01/routes/report.json`:
484 source routes and 289 native reference routes passed format validation.
The normal Skalitz profile's 45 routes contain 222 points. The installed
navigation graph matches the source bytes. Converted route entities are staged;
this is not proof of NPC traversal.

Simple untagged work animation calls can reuse shipped `AnimationAction`
fragments after checking both human controller databases for an actual body
animation. Tagged, aligned, context-locked or event-handle calls remain explicit
conversion failures. The rebuild lowered 11 compatible calls, including the
sweeping fragment; this does not make their containing routines executable.

`outputs/OpeningStart/WorkPrograms01/conversion04/summary.json` records the
current source rebuild: 354 of 1,436 non-function behavior trees emitted as
conversion fragments. This helper closure includes shared programs outside the
opening's active execution path, so the ratio is not a quest completion metric.
The top-level housework selector emits, but its sweeping animation and other
subjobs are not fully converted. `BlackSmith_new` still requires animation-event
handling, movement/action coordination, item phase changes and additional state
adapters. The fragments have not been installed. Complete routines, animation
events, interruptions, resumption and save/load remain unverified in-game.

Validation for this follow-up: 261 campaign tests, 80 character tests and seven
quest-import tests pass. The accepted installed Father forging/greeting build
has not been replaced by these incomplete work-program fragments.
