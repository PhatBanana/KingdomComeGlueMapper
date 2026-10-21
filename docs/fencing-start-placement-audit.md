# Fencing quest starting placement — 2026-10-20

Status: the initial layout correction is implemented in clean setup and package
migration. It has passed structural validation against the installed retail
mission. It has not been installed or tested in-game. The fencing lesson is
still incomplete.

## Confirmed defect

`setup_gameplay.actors` explicitly selected `vra_vanek`, but supplied placement
overrides only for the opening-scene guards. `build_quest_people_test` therefore
registered Vanyek at his source base actor position in Vranik. The shared person
world builder correctly anchored its fallback `schedulerWait` at that position;
this meant that changing only the actor's initial position would leave a
second, incorrect destination.

The installed retail mission contained:

| Entity | Position |
| --- | --- |
| `vra_vanek` | `1033.9132,891.27124,123.88925` |
| `gm_person_idle_vra_vanek` | `1033.9132,891.27124,123.88925` |

KCD1's `q_tutorial_swordOne` controller links `QuestActor[('vanek')]` to that
actor. Its registered `vanek_idle` callback resolves `QuestPlace[('vanekTeleport')]`
and copies that place's transform to the executing actor in `OnInit`, under
the persistent first-entry guard `$p_phase < 10`. The same initialization also
changes perception/faction state. The behavior subsequently uses the separately
linked `vanekSitting` ground seat.

These are distinct authored places:

| Source role | Position | Purpose |
| --- | --- | --- |
| `vanekTeleport` | `772.93317,3471.1392,52.499729` | Initial relocation into Skalitz |
| `vanekSitting` | `780.15918,3477.3896,51.2001` | Introductory sitting activity |
| `vanekWaiting` | `754.30408,3405.6086,61.858891` | Later arrival at the training ground |

The controller starts the intro routine when its quest starts. The later
`vanek_walksToTiltyard` callback moves to `vanekWaiting` and completes
`vanekOnSpot` only after successful movement. None of these later operations
should be replaced with an unconditional teleport to the training ground.

## Implemented correction and scope

`campaign_quest_start_placement.py` provides a reusable world-layout adapter.
Given an explicitly selected quest, actor role and starting-place role, it
resolves source links, validates identities and composes parent transforms.
It contains no Vanyek-specific coordinates or role names.

`setup_quest_starts.py` supplies the opening slice's selection, analogous to
the existing opening-scene placement selections. It chooses the authored
intro relocation point, not the seat or arena. This materializes the selected
opening layout at new-game creation. It is **not a runtime implementation of
the guarded callback**, and must not be used to flatten arbitrary later quest
teleports into a world's initial layout.

Clean setup passes this pose to the normal actor importer before it generates
the idle anchor. The same stage also repairs an actor reused from an earlier
package. Transactional package migration applies the identical adapter.
Only the importer's deterministically identified idle anchor is eligible;
authored work targets and scheduler tables are not changed. An unexpected
existing actor/anchor pose is a conflict and stops conversion.

Recipe version 37 and the converter fingerprint include the new adapter.
The package records its resolved layout in `quest-start-placements.json`,
and setup validates it against the emitted mission. Existing saves are not
relocated or edited by this correction.

## Validation

- Regression tests exercise different quest/actor names and coordinates,
  parent-local placements, missing/ambiguous links, ID/GUID disagreement,
  duplicate source copies, new and reused actors, anchor correction,
  conflicting placements, and idempotent migration.
- Clean actor staging and the real shared package finalizer are covered.
- A read-only probe against the installed KCD1 archives and KCD2 mod mission
  resolved the authored starting pose and changed only the actor and its owned
  idle anchor. All 34,939 other mission entities and all other attributes on
  those two entities were unchanged. Reapplying produced no changes.
- Local probe output:
  `outputs/fencing-audit-20261020/placement-validation.json`.
  The corrected mission is staged beside it, not installed.

## Remaining work before calling the lesson complete

This correction does not convert the controller's perception/faction setup,
the introductory seat/bark routine, its quest-start activation, or subsequent
schedule changes. Vanyek's source faction belongs to his later Vranik role;
the source temporary civilian override must be connected with the intro
routine, not implemented by permanently rewriting that faction.

The quest also needs its invitation dialogue, walking/arrival acknowledgement,
practice equipment lifetime, source exercise workers, phase dialogue, cleanup
and final handoff wired into one controller scope. Existing generic training
adapters cover parts of that assembly, but remain unpublished until their
required dependencies are converted. KCD1 movement/stab and second ordinary
block exercises must not be mapped to unrelated KCD2 phase numbers.

See `native-training-upgrader.md` for the existing conversion boundaries.
No playable lesson, save/load continuation, or retail arrival result is claimed
by the initial layout correction.
