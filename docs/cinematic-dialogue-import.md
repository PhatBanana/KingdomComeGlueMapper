# Cinematic and dialogue import

The importer reads source records and translates them into KCD2 formats. Scene
names, camera transforms, stat choices, actors and timing must come from source
data or explicit build inputs, not an opening-specific runtime script.

## Media conversion

`tools/cinematic_media.py` takes an archive, USM entry and source language ID.
It resolves retail patches, demuxes the selected audio and video, records the
original subtitle cues, and invokes a separately supplied RAD encoder. Output
dimensions, frame rate and duration are checked against the decoded source.
The encoder is not bundled; see [installer requirements](../newInstallRequirements.md).

The current supported media path is the MPEG/ADX USM format inspected in KCD1.
Bink 1 output uses KCD2's existing decoder. A `.bk2` package suffix is required
by the native player; it does not make the encoded payload Bink 2.

The target Bink audio track base is an explicit build input. The inspected native
KCD2 reference movie uses groups 10–15, 20–25 and so on for its six-channel
language tracks; the encoder's default 0–5 is not an equivalent registration.
Do not confuse source USM channel selection with target Bink track routing.

The optional `--rad-avi-end-guard` adds one repeated terminal frame to the
intermediate AVI to accommodate endpoint handling in the inspected RAD build.
The encoder also receives an explicit end frame. The final Bink must still match
the original source frame count; the guard must not become an extra output
frame. Other encoder builds must pass the same validation; do not suppress a
mismatch.

`tools/cinematic_subtitles.py` converts source cue timing to SRT references and
imports the original localized strings under deterministic namespaced keys.
Its localization rows must be merged with the mod's existing localization, not
installed by replacing an existing language archive wholesale.

The media builder can produce an explicit native cutscene-table override for
isolated development testing. It preserves other native movie entries and
removes the replaced movie's unrelated subtitle and event references. This is
a test package, not campaign selection or a production New Game hook.

## Dialogue conversion

`tools/campaign_dialogue.py --convert-presentation` converts the source dialogue
graph, including original choice text and objective callbacks, and emits:

- `FacialMoodCommand` from source mood IDs and the source mood table.
- `CameraCommand` retaining the authored custom camera reference.
- `AnimationCommand` retaining role, fragment, requested variant and delay.

Source commands precede their associated response. They are queued and attached
to the following response, preserving authored timing. Unknown commands,
unresolved roles and commands without a following response fail conversion.

With `--camera-level`, the importer resolves camera names from the dialogue
against the supplied level's mission and layer data. It converts persistent
identities and preserves the original camera transform and optics. Missing or
ambiguous camera references fail conversion. Camera entities are staged for the
world/profile importer; they are not enabled globally by this tool.

Emitting native command records is separate from importing the referenced
animation fragments, binding actor rigs and facial/lip-sync assets, connecting
quest callback ports, and installing the native dialogue invocation. These are
dependencies of the generated scene, not candidates for handcrafted substitutes.

## First acceptance case: original KCD1 New Game

The original source establishes this sequence:

1. Native New Game preparation sends `questModule:onNewGame` to `q_master_main`.
2. The master activates the original opening profile and starts `q_skalitz`.
3. The original `stribrna_skalice` cinematic plays. Complete and skip paths must
   lead to the same intended campaign state, without a gameplay flash first.
4. The source opening behavior sets 10:00, pauses time for `q_skalitz`, installs
   actor schedules and enables `q_skalitz_mother_dialog_cameras`.
5. The mother's source behavior invokes `q_skalitz_characterCreation`, including
   its two rounds of Speech, Agility, Vitality and Strength choices and original
   objective effects. The source `p_startOfGameDone` gate prevents replay.
6. The original quest state and subsequent interactions continue and persist
   through native save/load.

These names identify the first test case only. They are not special cases in the
generic media, presentation-command or custom-camera conversion code.

On 13 October 2026, the source-driven dialogue conversion produced four topics,
ten sequences, 27 original voice files, 106 native presentation commands, four
converted custom cameras and nine distinct objective callback ports. The eight
choice branches are preserved in the generated graph. Body-animation variant
compatibility, facial/lip-sync playback, actor binding, callback execution and
the complete New Game handoff still require installation and in-game acceptance.

Test each step in order: complete movie, skipped movie, mother scene entry,
each stat-choice branch, camera/animation/voice synchronization, quest handoff,
then save/load. Keep conversion reports separate from runtime acceptance.

The first development movie test now uses the full 7,706-frame 1920×1080,
30 fps source. A live test showed the original Skalitz establishing shot and
the original localized place/date subtitle through the native loading-movie
entry while the engine was in level-load preparation. Completion/skip and the
mother-scene handoff are separate acceptance checks. The test override is
installed only in the development mod, with its prior test pak and localization
archive backed up locally.

On 13 October 2026, the user accepted the opening-video test. This acceptance
is limited to the movie stage; the mother conversation and character-creation
handoff are not installed or accepted yet. Completion and skip-path state
equivalence remain separate campaign integration checks.

## Dialogue runtime dependency stage

`tools/campaign_dialogue_runtime.py` consumes a staged dialogue package and a
converted quest project. It resolves the original recording abbreviations
against the native voice table, emits `SelectedSouls` and `VoiceNamespace`,
places recordings under the actual native dialogue name, and derives response
durations from Vorbis sample counts. It also creates native dubbing metadata
and localization additions. Merge these additions with installed localization;
the staging folders are not replacement language archives.

The stage connects each source objective callback to a validated trigger input
on the corresponding converted quest instance. Its activation must be an
existing declared boolean output. It neither invents a startup event nor starts
the conversation: source behavior invocation, role registration and presentation
dependencies must be installed by the campaign builder.

The next New Game dependency pass produced 27 bound original recordings and
nine validated objective connections. The mother's source appearance also
converted after two reusable importer fixes:

- Resolve NPC links into other world layers, preserving their provenance and
  rejecting missing or ambiguous target identities.
- When a garment has source opacity data but no cached triangle visibility,
  derive visibility from the complete converted mesh only after verifying its
  hiding memberships were cleared. Texture cutouts still use the source opacity
  mask. This is coverage for the converted outfit, not reconstruction of KCD1's
  missing visibility cache, and still requires visual acceptance.

Animation inspection found matching named clips for all 36 role/fragment pairs,
but that does not establish matching variants. An untagged, one-based variant
probe found four Henry commands selecting a clip absent from the native dialogue
database and one selecting two native fragments with different blend timings.
Source context and variant numbering must be verified, and unresolved motion
must be imported rather than replaced with an arbitrary native gesture. The
mother conversation was still staged at that checkpoint.

### Installed scene test and camera binding

The next development test reached the original first choice menu and played
the mother's original voice; the user confirmed both on 13 October 2026.
`ForcedDialog` requires its native `EnqueueDialogue` and `DialogParams` inputs.
The lowercase `enqueuedialogue` found in shipped content belongs to a wrapper
port, not the underlying forced-dialogue node. Parameters are supplied through
`wh::dialogmodule::CreateDialogParams` with the imported participant soul.

Custom camera entities also require `CameraAsset` declarations and
`asset['alias']` links from the native project holder, in both the mission and
`waitinglinks.xml`. Without those bindings the engine falls back to automatic
conversation cameras. The reusable `bind_scene_cameras` adapter now creates
these bindings while preserving the authored camera transforms.

This remains a diagnostic scene, not a completed New Game implementation.
The full quest/reward graph caused a loading stall and is disconnected in the
installed diagnostic build. Five unresolved gesture commands are omitted only
under an explicit test flag; original lip-sync clips are still missing. The
exploration side-quest notifications also need to be gated out of this opening.
The first scene builds copied source spawn transforms but omitted native
dialogue-entry placement. Both actors reached terrain below the house before
the conversation. Raising the initial markers by 0.08 m did not fix this;
the player's later return to floor height was a manual jump, not engine recovery.

`bind_scene_positions` now translates the selected source participant spots
into a `DialogueHolderAsset`, a world `DialogueHolder`, and TagPoints with
`teleportBefore` / `useAsset['soul_alias']` links, including compiled waiting
links. This follows shipped native scene placement and preserves the original
actor and camera coordinates. Parented source spots are rejected until their
world transforms can be resolved explicitly. It does not add a guessed delay
or derive indoor floor height from terrain.

The development placement test measured both original actors and both dialogue
twins at the authored floor height (63.9089 m) during the first choice menu,
without manual jumping or console repositioning. A captured frame showed the
conversation inside the room. The two Speech choices then completed and the
dialogue cleaned up; both actors remained at 63.9089 m in normal gameplay,
without a manual jump or repositioning. Collision streaming as the initial
cause, stat rewards, and fresh movie completion/skip integration still require
separate verification.
