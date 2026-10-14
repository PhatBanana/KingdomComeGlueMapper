# Dialogue speaker, gaze and camera conversion

## Source and target contracts

Responses use their source `role_id` as the speaker. Camera subjects and gaze
targets are independent roles, and must not replace that response speaker.
Source commands preceding a response retain their original delay and apply to
that following response. A reaction shot may therefore show Henry while Father
speaks, or vice versa.

The source command type numbers are not the KCD2 command enum. In the installed
KCD1 `WHGame.dll` (SHA-256
`cf9f6dc384edcf35c20647a912745ddb8adb5ba65953e329c24e89dd9c4381aa`),
the command dispatcher at RVA `0x6880a4` selects the look-at constructor for
type 4. The constructor at RVA `0xd6c086` installs the RTTI-identified
`C_CommandLookAt` vtable and copies the actor and target identities separately.
The importer emits native `LookAtCommand Role=... LookAtRole=...` for this
source operation. KCD2's shipped `Scripts.pak` contains this native form,
including commands whose actor differs from the current response speaker.

Camera commands support Auto, Master, Medium, CloseShot, CloseUp and authored
custom camera references. KCD2's camera registry and Skald `CameraCommandTypes`
define these names. Source response mode 0 emits an explicit Auto camera command
for the response role unless that response already has an authored camera
command. Modes 1 through 4 emit their specified camera type for the response role.
An explicit authored command can subsequently cut to a different participant.
Custom response modes without a resolvable camera fail conversion.

Role dependency collection includes response speakers, declared participants,
command actors and command targets, including silent listeners. The actor
dialogue builder requires those NPC roles to be bound to imported souls.
Missing actors are reported rather than silently mapped to the current speaker.

## Installed development audit, 14 October 2026

`build_dialogue_presentation_test.py` reconciles the topic-based imported
dialogues against original source responses using localization identities.
It checks consistent speaker remapping, preserves voice bindings and existing
commands, and adds missing camera/gaze commands without rebuilding quest state.

The audit covered 147 responses across eight opening/parent/greeting graphs.
The recorded speaker mappings preserve Henry, Mother and Father. Four source
CloseUp instructions were missing from Father's topic-9193 conversation tree;
these were restored, including a shot explicitly assigned to Henry. Existing
opening and Mother camera instructions were already present. These eight source
graphs contain no type-4 gaze commands, so that generic adapter is covered by
regression tests rather than a new live gaze case here.

Artifacts: `outputs/OpeningStart/DialogueTargeting03/report.json`, staged travel
package, installation receipt and backup. Validation: 246 campaign tests pass,
including silent target dependencies, distinct actor/target mapping, listener
camera subjects, preservation of recording duration and idempotent upgrades.
The new shots still require visual acceptance in game. This audit does not
establish collision-free camera placement or complete gesture/lip-sync support;
other command categories are retained in the report outside the targeting scope.

## Automatic speaker cuts correction

The user's comparison with KCD1 exposed an incomplete mode-0 conversion:
omitting a camera command did not restore the original speaker-change cuts.
KCD2's Skald `CameraCommand.CreateDefaultCameraCommand` binds the command to
`response.Role` at delay zero; shipped dialogue XML explicitly places camera
commands on successive Henry/NPC responses. The importer now materializes
those automatic cuts. Authored reaction shots and custom cameras take priority;
in-world monologues never receive generated camera cuts.

`outputs/OpeningStart/DialogueAutomaticCuts01` adds 78 automatic cuts across
four installed parent dialogue definitions, including all 24 responses in
Father's initial conversation. The opening and Mother's authored camera sequence
and the proximity greetings receive no changes. Validation: 248 campaign tests
pass. These cuts are installed for the next visual test; the prior live log's
invalid generated-camera candidates still need runtime rechecking after this
correction. Restored commands alone do not establish camera collision validity.
