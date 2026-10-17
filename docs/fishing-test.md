# Fishing prototype

Fishing03 replaces the dry-bank restriction with a ray from the view camera.
Aim at water within 40 metres; terrain blocks the ray. Feet position, bank
slope, actor facing and standing in shallow water do not reject a cast.
Collision-only objects (walls, boats and bridges) are not yet included in the
ray test; water surface height is approximated from compiled water contours.

## Controls

- Equip and draw the rod using the main-hand weapon slot.
- Aim at water, hold left click for at least 0.25 seconds, then release to cast.
- Left click at the bite prompt and at each pull prompt. Three pulls land trout.
- Right click cancels. F7/F8/F9 remain development fallback controls.
- Moving away, losing the rod, combat, dialogue, mounting or death cancels.

The rod is registered as a MeleeWeapon using native class -1 (undefined): its
native table configuration has PrimaryMainHand equipment, no attack types and
zero damage. This avoids repurposing an offensive weapon class. The equip/draw
behavior still requires live validation; this is a prototype, not a verified
finished weapon integration. Primary mouse action events were observed live
before implementing the hold/release handler.

Both test chest presets contain the same stable rod ID:
11168d06-72e7-51e9-bb72-678de69b09f6. Existing saves created with the earlier
MiscItem definition require checking that the item type migrates correctly.

## Icon

The built-in image generator created assets/fishing/fishing_rod.png using the
installed player_shovel inventory icon as the style reference. The prompt is
in assets/fishing/generation.txt. The generated alpha is preserved in the
64x64 DDS inventory texture, packaged as
Libs/UI/Textures/Icons/Items/gm_fishing_rod_icon.dds.

## Build and verification

Use tools/build_fishing.py with --game, --mod, --output and optional --baseline
pointing to the original pre-fishing backup (outputs/Fishing02/backup) when
upgrading. The baseline supplies travel/localization source files; current
installed terrain supplies the water polygons. Installation receipts include
pre-install and post-install hashes; original packages are backed up.

Run `.venv/Scripts/python.exe -m unittest discover -s tests -p test_fishing.py -v`.
Seven tests cover camera targeting, terrain blocking, charge/release handling,
wrong-weapon input, catches, single rewards, mistimed pulls and cancellation.

Fishing02 live checks verified rod draw/holster with the earlier MiscItem,
script initialization and both test chests containing one rod. Camera targeting
was hot-applied and accepted water at the reported location. Fishing03 is
installed and the development game launched normally. Full equip, icon display,
mouse casting, animation and catch verification remain pending in-game.
No shader cache is cleared by building, installing or launching this feature.


## Fishing04 visual cast

Fishing04 is installed with backed-up originals. All displayed prompts now use
English localization keys; raw sentences are no longer passed to SendInfoText.
The cast fragment switches after 0.6 seconds to the native standing rod idle,
and seated idle/stand-up animations are removed from this feature.

The float follows an analytic gravity trajectory (9.81 m/s²) to the aimed water
point, then a damped spring approximates buoyancy. Sixteen rendered line
segments use a constrained Verlet simulation for slack. The first-person rod
tip anchor is currently estimated from the camera, rather than a measured rod
bone attachment. The float has a pale body and red tip; a custom native particle
emitter produces landing, idle, bite and fighting ripples. During the bite window
the float dips, and a click hooks the fish. Three prompted pulls finish landing.

This is script-simulated physics, not a native rigid-body/rope simulation.
Terrain-only aiming still does not account for collision-only walls or boats.
Water bodies are inferred from polygon compactness: elongated channels get a
river pool (75% trout, 25% perch); others a pond pool (20% trout, 80% perch).
These are gameplay weights, not surveyed habitats; native water materials are
shared and do not supply reliable river/pond ecological metadata. Both rewards
are the game's existing raw fish items.

The Fishing04 probe only checked Lua exceptions and missed engine binding
warnings. It did NOT validate rendered output. The user subsequently found a
wrong SetLocalScale argument, missing materials, missing hands and a line that
followed the camera. Fishing05 corrected scalar scaling/materials but still
had the wrong animation/attachment setup. These builds are not visually accepted.

## Fishing06 animation correction (staged, not installed)

The user requested preparation without launching the game. The staged package
is outputs/Fishing06/package; animation-audit.json records the checked source
events and remaining live checks. The installed Fishing05 package is unchanged.

Native source findings:

- FishingCast uses fisherman_cast_sitdown_01, lasting 14.133334 seconds according
  to Animations.img. Its c_w_halberd_flick event is at normalized 0.3367099
  (4.758834 seconds). Rod placement/detach occurs around 0.6393 and the sitting
  sound at 0.8124. The previous 0.6-second cut preceded the throw.
- Custom fragments had no entries in kcd_male_controllerdefs.xml. Fishing06
  registers FullBody+UpperBody scopes, in addition to the fragment names/data.
- The preview attaches the old animated rod CDF to hand_right, but the native
  kcd_fishingrod_database.adb is empty. The equipped inventory rod is a different,
  static CGF; using the legacy CDF's bone names would be incorrect.

The cast runs the original clip and transitions to that same clip with
StartTime=6 seconds and speed=0. Idle starts at this same held frame; no seated
clip or separate carry idle is used. Six seconds is a candidate between the
throw and subsequent movement/placement events, NOT a visually verified pose.
The runtime no longer interrupts this sequence when the float lands.

The float launches after the native throwing-event delay, from a named helper
added at the equipped rod mesh's measured tip (local z=1.839547 metres). The
held-item WUID is resolved with XGenAIModule.GetEntityByWUID; GetHelperPos in
world space follows the entity's hand/slot transform. A missing rod/helper
rejects the cast instead of substituting a camera anchor. Only the mod's cloned
rod receives the new helper; its original pickup helpers/materials remain.
Save-load initialization removes exact-name orphaned fishing visuals.

Mannequin's StartTime-in-seconds and playback-speed handling were checked
against the related engine's primary source:
[ActionScope.cpp](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Mannequin/ActionScope.cpp).
This supports the implementation but is not proof of KCD2 runtime behavior.

Eleven offline tests pass. The staged archive was checked for scope registration,
frozen clip parameters, helper position/references, Lua parsing and hashes.
Live checks still required: the exact frozen pose, first-person hands, WUID to
rendered-rod resolution, helper world-space alignment, release synchronization,
right-click retrieval and an end-to-end catch. No live success is claimed.

## Fishing07 cancellation and anchored float

The user confirmed Fishing06's casting animation plays. They reported that
cancellation leaves the animation stuck and requested a small red float that
stays at the landing point while Henry moves with the rod.

Fishing07 is installed, with Fishing06 backed up under outputs/Fishing07/backup.
The game was left closed. Twelve offline tests pass; live verification is pending.

- Cancellation now releases the owned animation action and explicitly resets
  speed/stops its character layer (cast layer 0; held pose layer 6). Completion
  no longer immediately restarts the same frozen pose. Cancellation also works
  with no active session and before the usual safety/held-item input gates.
- The original cast remains; at its hold time the pose moves to UpperBody scope.
  The 80 cm movement-cancellation rule is removed. Live movement/pose behavior
  of this upper-body fragment still needs confirmation.
- One 7 cm wide, 9 cm tall red float replaces the pale body/separate cap. Its
  horizontal landing coordinates remain fixed even during a bite or fish fight.
- Line length pays out with the cast, keeps slack when walking closer, pays out
  farther when walking away, and retracts on cancellation. The rod-tip helper
  is sampled on every update. Tests verify both fixed water and moving rod ends.
- A quick press/release can cast too; holding still continuously checks aim.
  The log showed repeated aim_short rejections, so the arbitrary 250 ms minimum
  was removed. Input without a preceding press still cannot launch a cast.

Offline checks cover logic and package data, not rendered appearance or native
input/animation acceptance. The next live check must confirm full cancellation,
walking while the line is out, red float visibility, and rod-tip alignment.

## Fishing08 immediate cancellation and timer recovery

The user changed movement behavior: walking must cancel immediately. Right click
and pull-in must also be instantaneous. Fishing08 supersedes Fishing07's walking
with the line out and timed retrieval behavior.

- Cancel clears session/geometry and stops the owned animation synchronously.
  No retrieval phase or cancel cooldown remains. Successful landing and failed
  pulls also finish immediately in the runtime adapter.
- Native moveforward/moveback/moveleft/moveright actions cancel before forwarding
  movement. A 5 cm displacement check is a fallback for external movement.
- Live diagnosis found phase=windup, deadline=527.116, time=557.804, visuals=0.
  A separate repeating Script.SetTimer probe fired four times successfully.
  The fishing loop had stopped, so nothing had spawned. Interactions now restart
  a stale update heartbeat and invalidate obsolete callbacks. Release logs the
  actual visual entity count to distinguish spawning from rendered visibility.
- The attempted live script transfer did not complete before the game closed;
  no live patch success is claimed. Fishing08 is installed with hash verification
  and a Fishing07 backup. Thirteen offline tests pass. The game was left closed.

Live confirmation still required: heartbeat survives level loading/interaction,
the red float and line actually render, and both walking and right click release
Henry immediately. This update fixes the observed failure path, but offline
checks do not substitute for that visual verification.

## Fishing09 single bite, sixty-second cast

Installed and hash-verified; game left closed. Thirteen tests pass. This replaces
the original three-pull fight with the user's requested one-click catch:

- The sixty-second window begins at the scheduled water landing time.
- One bite is scheduled uniformly from 3 to 58 seconds after landing, with a
  two-second response window. A click during that window immediately lands one
  fish. An expired bite cannot be recovered by a late callback or stale click.
- Missing the bite leaves the float until the sixty-second deadline; right
  click/walking can end it instantly at any time. An early pull yields no fish.
- Float buoyancy dips during the bite and produces ripples. A successful catch
  emits a final ripple before removing geometry. Effect failures cannot block
  inventory delivery. The line remains tied to the authored rod tip.
- Native cast root motion is excluded from displacement cancellation until
  landing; actual walking input still cancels immediately in all phases.

The installed package is not visually verified. Do not describe line/bobber
rendering or the stopped-loop root cause as confirmed fixed. Physics is a
scripted gravity trajectory plus a buoyancy spring, not a native rigid body.

## Fishing10 joined segments, quicker throw, quieter prompts

User screenshot confirms Fishing09 renders the red bobber and line, but line
segments overlap instead of connecting. Source inspection found SetWorldAngles
rebuilds a unit-scale matrix; applying it after SetLocalScale erased each
segment's length. Rotation now precedes scale. The regression test simulates
that native side effect and verifies all sixteen transformed mesh endpoints
against the next simulated point, rather than only testing the point array.

The cast starts at 3.9 seconds in the existing clip and releases at 0.858834
seconds of elapsed play; the frozen hold remains source frame 6, reached after
2.1 seconds. This skips the lead-in without accelerating or replacing the throw.
The new entry blend still needs live visual confirmation.

Casting/waiting/bite/missed/cancel/equip prompts are log-only. Aim feedback is
short and appears on press or validity change, not every second. Catch results,
timeout and actionable errors remain visible. The float dip/ripples indicate
the bite. Fishing10 is installed and hash-verified, with Fishing09 backed up;
13 tests pass. Game left closed. Live acceptance of the corrected joins remains
pending; this does not claim a screenshot check of Fishing10.

## Fishing11 wooden float, bite cues and native interaction

User confirmed Fishing10 works, then requested a period-style float, clearer
ripples/tug, the native item-received UI and contextual interaction rather than
function keys. Fishing11 replaces the red ball with a 5.2 cm wide, 14 cm tall
pale carved-wood float and deterministic grain texture. This is a visual design,
not a claim of a documented medieval specimen.

The ripple uses the native Materials/particles/water_ripple material, animated
4x2 atlas and Free/x=90 orientation from IPL_GameData.pak WH_Particels.xml.
Visibility distance is 60 m, with larger bite pulses. Bites tighten the existing
connected line over 0.12 seconds and dip/pulse the float. The actual rod animation
and helper remain unchanged; no detached endpoint is used to imitate rod bending.

Catches call Game.ShowItemsTransfer(fish,1) after verifying inventory growth,
matching Scripts/Utils/ItemUtils.lua. No duplicate large catch message is shown.
An owned native InteractionTrigger supplies trigger_use actions (normally E,
with engine-managed bindings/controller glyphs): Fish over valid water with the
rod drawn; Pull in while active; Catch fish during the bite window. Callback
revalidates state. No new F-key bindings are installed; mouse controls remain.
The hidden, nonphysical trigger follows the view only while an action is valid,
and is removed when invalid/unequipped and on save initialization.

Fishing11 installed with both package hashes verified; Fishing10 backed up in
outputs/Fishing11/backup. Fourteen offline tests pass, including native action
dispatch/gating, one item notification per successful reward, and line tightening
without breaking endpoints. Game left closed. Native trigger focus/glyph display,
ripple visibility and the wooden float appearance still require live validation.

## Fishing12 ripple plane correction

User screenshot shows Fishing11 ripples edge-on as a vertical sheet. Replace
Free facing plus x=90 initial rotation with Horizontal facing and zero rotation.
Explicitly disable emitter-relative motion and velocity orientation. Every
pulse uses the fixed target XY and water Z + 0.015, ignoring the dipping float's
position. Native animated atlas/material and larger bite pulses are retained.

Fishing12 staged; 14 tests pass, including a regression that a displaced float
cannot move the ripple emission point. Built particle XML and package hashes
verified. Installation awaits normal game exit; horizontal rendering still
requires live visual confirmation.

## Fishing13 cork float specification

User specified a 2-4 cm irregular oval cork float, tan/light brown porous texture,
and a thin wooden or quill stem securing the line. Implemented a 3 cm cork body
(streamed mesh vertex bounds measured), mildly tapered/uneven XY silhouette,
matte granular tan texture with dark pores, 1.3 mm diameter wooden stem through
the centre and a small line tie. Line endpoint now follows the tie 18 mm above
the cork centre. The stem is 38 mm overall; cork body 30 mm. Resting buoyancy
centre lowered to water +3 mm, with 2 mm idle bobbing, to suit the small float.

Includes Fishing12 horizontal, fixed-water ripple correction. Fishing13 installed
and hashes verified after confirming the game was closed; Fishing11 backed up
in outputs/Fishing13/backup. All 14 tests pass. Game left closed; new cork/stem
appearance and horizontal ripples still need in-game visual confirmation.

## Fishing15 inventory interaction and quieter bite cue

User confirmed the horizontal ripple is visible but too strong. Ripple now uses
one particle at alpha 0.18 and size 0.3, emitted exactly once when the cork first
submerges during a bite. Removed landing, idle, repeated bite and reward pulses.
Added an 8 cm tapered pale quill above the 3 cm cork, with a small red tip following
the supplied reference. All 21 owned visual entities are removed on cleanup.

User clarified the rod only needs to be in inventory. Native Fish prompt now
checks ownership, not the drawn/equipped state. Fish holsters a normal held weapon,
draws the inventory rod and starts the cast as soon as the real tip helper is ready.
A two-second readiness deadline aborts failure; it does not delay successful
casts. Other held props are preserved and report the existing empty-hand message.
Movement/right click cancels even during preparation. Completion/cancel holsters
only the rod. Initialization and idle updates put away a restored/native-drawn rod;
they never start an idle pose. Thus native attempts to draw it outside fishing are
corrected on the next 33 ms update, rather than disabling all weapon draw controls.
Old F7 command can only put the rod away; native Fish is the entry point.

Fishing14 was staged before the inventory-control clarification and not installed.
Fishing15 includes all changes and is installed with verified package hashes;
Fishing13 backup is in outputs/Fishing15/backup. Fifteen offline tests pass,
including automatic draw/readiness/cancel, load cleanup, unrelated-item preservation,
single bite ripple and inventory-based interaction. Game left closed. New native
draw flow, quill appearance and softer ripple require live validation.
