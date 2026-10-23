# Designer collision and retail door repair

Recipe 53 repairs existing recipe 52 builds through the same finalization path
used by a clean build. In setup, choose **Restore / upgrade build…** and select
the original job directory containing `job.json`. Setup verifies its retained
package, upgrades a private staging copy and installs transactionally.

The designer-volume import copied editor-facing Illum materials into retail.
The repair recognizes the authored collision-proxy texture and uses KCD2's
Nodraw material rendering contract, retaining SurfaceType and geometry. This
preserves fireplace, building and boundary collision without coloured surfaces.

Source horse blockers also occupy the exact origins of registered AnimDoor
entities. The repair resolves source parent transforms and matches registered
door identities and positions, then removes only HLOD brushes matching the
source blocker origin and full bounds. Ordinary structure collision, other
designer volumes and unregistered doors are preserved. No house coordinates,
NPC identities or door animation timers are part of the rule.

The existing LOD marker is verified before changing HLOD membership, then its
fingerprint is updated without reencoding surviving records. A repeat run is
unchanged. Asset archive replacements do not write through hard links.

The same release repairs inactive tutorial progress callbacks, preserves built-in
Progress types, and stops controller-only quests publishing a blank journal
entry. Training provenance checks resolve unchanged assets moved into retail
PAK shards by the packaging stage.

Private-package evidence: 939 duplicate door blockers removed and 11 proxy
materials hidden. These are source/package checks; retail walking, rendering
and tutorial behavior still require a game test after installation.
