# Source campaign format upgrades

Recipe 20 applies these adapters both to clean builds and to existing packages
through setup's normal resume/migration path. They do not select quests by name.

## Separate map assets

`quest_tracked_asset.map_asset_id` takes precedence over the counted
`quest_asset_id`. NPC map assets use registered soul identities. Point map
assets resolve `quest_place.entity` against the original level's TagPoint,
retain its world position and create a native TagPointAsset plus both entity
and waiting-link bindings. Only the Started journal log receives the marker.
Graph-editor `pos` values are never treated as world coordinates.

The source opening consequently supplies the crossguard, charcoal and chest
point markers. Cross-map and area markers remain explicitly reported as pending;
this adapter does not replace an area with an arbitrary point.

## Multi-NPC conversations

The original topictorole/soul2role records determine every NPC participant,
including participants with no recorded response. The clean dialogue builder
and existing-package upgrader lower multi-NPC FaderDialog output using KCD2's
shipped `utils/speech/SpeakTrigger` pattern: a technical Talk interaction queues
a ForcedDialog with explicit CreateDialogParams participants. The original
dialogue name, voice namespace, recordings, choices, scripts and quest effects
remain in that dialogue. The technical interaction preserves the source entry
predicate and its local once-only entry history.

The importer rejects ambiguous soul membership, ambiguous containers and entry
history referring to other sequences. Source-controlled movement and cinematic
choreography are separate adapters; this change does not claim to implement
those. Native ambient greetings can still request recordings absent from the
imported character's voice. That is separate from the packaged source dialogue.

Validation covers arbitrary quest/actor identities, separate item/map targets,
source-position use, silent participants, preserved effects, missing/ambiguous
targets and repeated upgrades. Runtime Talk, handover and audio still require
an in-game test of the upgraded package.
