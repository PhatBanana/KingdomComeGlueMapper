# Native job conversion

The converter selects adapters by source behavior identity, not by NPC name.
The existing schedule adapter resolves work areas, time windows, tools and
workstations. Each supported job adapter must retain the source dependencies
and use the native job's movement, hand-item, animation and cleanup contracts.
An unsupported phase remains explicitly reported; converting one phase is not
equivalent to converting a person's complete daily routine.

## Sweeping point-navigation candidate

`character_sweeping_routes.py` previously replaced native sweeping approach
logic with a predefined-route Move copied from a horse behavior. It removed
the native hand checks and distance guards. This is a confirmed implementation
difference, not a proven explanation of the reported door blockage.

The new `character_job_routes.py` translates every source route vertex into a
stable TagPoint, with ordered first/next links in both entity links and the
compiled waiting-link network. Different routes have different point identities
even when their coordinates match. Missing references and conflicting existing
points fail conversion. No geometry or target navigation mesh is rebuilt.

Sweeping now retains the native sweeping approach sequence, including its hand
and distance checks, with only the movement target changed to the current work
point. Native point movement selects the path between destinations. Source start
and end dwell durations remain intact. Movement failure propagates to the native
job lifetime; an absent final successor is normal completion. Tool reservation,
hand-item scopes and existing interruption ownership remain native.

The existing fresh-build schedule and tavern builders call this shared adapter.
`build_job_routes_upgrade.py` stages an existing-package conversion for every
registered instance of that adapter. It does not reset schedules or install the
result. Historical completed build outputs need this explicit refresh or a new
build; they are not automatically invalidated by this code change.

## Validation on 20 October 2026

- 97 character tests and 547 campaign tests passed, including six new route tests.
- The retail staging candidate converted six routes / 30 vertices across three
  registered jobs (Mother, another houseworker and Bianca), selected by template
  and links rather than names.
- Repeating migration produces identical files. Unrelated archive entries were
  compared byte-for-byte; archive CRC checks passed.
- All 43 generated runtime nodes passed attribute checks against the extracted
  native KCD2 behavior catalog.
- Candidate: `outputs/native-job-point-navigation-test-v2`; installed in retail.
  The user reports Mother still stops at the closed door, but continues through
  it and resumes work when the player opens it. This is not a verified door fix.

Still test closed-door approach while carrying a broom, resumption after the
door, dialogue interruption, failed movement, schedule changes and save/load.
Also verify the new TagPoints resolve through KCD2's loaded AI link network.
The shipped native door script includes occupied-hand handling and obsolete
movement branches; static inspection alone cannot identify the actual branch
taken in the reported failure.

This provides reusable route movement conversion, not support for every KCD1
job. Cooking, water carrying, embroidery, patron orders and other reported
unconverted phases still need their own source-to-native behavior adapters.

## Door animation registration repair

Inspection of the installed archives found 948 converted doors with an animation
registration `Hash="0"` and one rental door with no registration. All 252 native
Trosky door rows instead reference their corresponding local helper collection:
for example DoorLeft uses 6722057138874366142 and DoorRight uses
16144086406879383884. These are observed hashes, not constants in the converter.
The installed DoorLeft/Right helper definitions match native definitions.

`seating_animations.install` previously discarded this collection reference for
doors while correctly preserving it for work objects. This confuses local
animation identity with world-specific animation validation. The repair retains
the collection reference and the converted door's own world transform. It does
not copy Trosky's world-space projections or precomputed navigation checks.
Rental AnimDoors are now included in the same registration path.

`door_animation_upgrade.refresh` repairs missing/zero door registrations from
the package's existing helper collections. It preserves valid caches and rejects
ambiguous collections, invalid hashes, conflicting transforms and duplicate
rows. `plan` updates both the level-local table and its mod-prefixed mounted
copy. Setup package finalization calls this repair for migration/resume;
`build_door_animation_upgrade.py` can stage just these two archive entries.
The executable already downloaded by a user is not rebuilt by editing this code.

Candidate: `outputs/door-animation-registration-test`. Structural validation
repairs 949 doors, is idempotent, verifies both tables agree and checks every
unrelated archive member byte-for-byte. This corrects a demonstrated registration
defect; the subsequent retail test did not resolve Mother's blocked traversal.
The user also reproduced the blockage with empty hands after interrupting her
job. That makes a broom-specific failure insufficient to explain the problem.
No changes
to door locks, collision, navmesh, job ownership, or automatic door-opening
scripts are included in this repair.

The next investigation found that two of the house's door navigation connections
were absent from the active base mesh. The user confirmed the subsequent retail
test fixes the reported issue on 20 October 2026. See
`static-navigation-profiles.md` for that repair, its tested baseline and the
remaining runtime coverage limits.
