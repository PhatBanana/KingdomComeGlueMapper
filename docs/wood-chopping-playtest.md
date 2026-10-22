# Native housework wood chopping

Setup recipe 47 adds KCD2's native collect/chop/store activity to eligible
importer-owned housework pools. Selection uses the source housework gender
branch, the home's actual `choppingWood` behavior binding and its linked
`ChopBlock`, `woodForSplitting` and `choppedWood` objects. No NPC name or fixed
coordinate selects the adapter. Missing or unsupported source bindings are left
alone; ambiguous workplaces fail validation rather than selecting a nearby prop.

The adapter preserves existing fence-repair and home-rest activities. It retains
the source work hours and shares each chopping resource across workers. Existing
quest controllers and actor initialization are not replaced. This is an additional
housework choice, not the complete ordered KCD1 housework controller.

The complete native workstation graph is relocated to source animation contact
positions. It includes a reserved basket, collection and unloading points,
set-aside slots, the axe and phase logs. Authored items are promoted/reused by
identity; redundant imported decorative item meshes are removed. Native item
definitions, helper collections and animation hashes are checked. World-space
navigation/physics results from Trosky are not copied; the imported positions
request runtime animation validation. The stock KCD2 activity handles the work
sequence and its tool lifecycle.

## Validation

Twelve focused tests cover:

- Complete native graph, source work hours and compiled waiting links.
- Preservation of an existing fence-repair pool.
- Repeat application, shared workplace geometry and corrupted tool rejection.
- Rejection of foreign owners, changed clocks and unrelated pool activities.
- Missing native links, item definitions and incorrect basket spawn settings.
- Rigid placement of native offsets around source contacts.
- Source query depth/pruning and unsupported lab behavior bindings.
- Applying the upgrade to multiple eligible workers with arbitrary names while
  sharing one workstation and leaving repeat upgrades unchanged.

The full repository suite passed 1,713 tests, with 17 skipped.

A real-data stage was generated through the setup population upgrade path at
`D:\BuildKCDMod\wood-chopping-20261022-v2`. It selected four workers:
`ska_beranMr`, `ska_enemyOfHenry`, `ska_farmer27` and `ska_skinner`. These are
test subjects discovered from source data, not conversion selectors.

Validation found four complete workstations, four extended housework pools and
four new scheduler terminal rows. All 62 NPC entities were unchanged, previous
activity links were preserved, and all 20 new helper registrations have valid
native hashes and imported transforms. Archive CRCs, scheduler targets and
mounted resource aliases passed. Repeating the upgrade added no activities.

This directory contains changed level/travel archives and reports, not a full
standalone mod package. The chopping update was installed into retail on
22 October 2026 over the verified home-rest baseline. Installed archive hashes
and the ownership receipt passed verification. The installation journal and
rollback copies are under `retail-install/` in the stage directory. The base
recipe version is retained with a separate `wood_chopping_playtest` receipt
record; this targeted installation does not claim a full recipe-47 rebuild.
The setup source and frozen-app module list include the adapter; an older
executable does not gain the change automatically.
An updated local executable was built at
`outputs/wood-chopping-setup/KingdomComeGlueMapper-Setup-0.3.16-win64.exe`.
Its frozen self-test passed with all 49 converter modules, worker pools and
extended staging paths available. This is a local setup build, not a new release.

On 22 October 2026 the user confirmed that the installed chopping activity was
working. This is user-reported retail playtest evidence for the installed
example, not a claim that every eligible NPC, interruption path or save/reload
case has been exercised. Generated reports continue to mark unobserved builds
as runtime-unverified.

Both clean setup builds and existing-package upgrades run this same population
conversion for every person in the selected source profiles. Eligibility comes
from source schedules and complete linked workplaces, with no four-person cap.
The current source housework branch assigns chopping to male houseworkers;
female houseworkers retain their source-defined activities. Quest-owned jobs
remain under their quest controllers.

## Retail acceptance

1. Install through the normal verified package path with rollback retained.
2. Observe an eligible worker collect the basket and walk to the log pile.
3. Check arrival, basket placement, axe pickup and chopping alignment.
4. Observe the chopped wood collected and unloaded, with no duplicate tools.
5. Interrupt with dialogue and check the tools and workstation become available
   again. Test leaving/returning, schedule changes and save/reload.
6. Confirm fence repair, bench rest, other workers and quest NPCs still operate.
7. Check for new pathing, animation-queue or reservation errors in the log.

The native choice does not guarantee that an NPC chops immediately on loading:
their existing activities remain available. Full source phase ordering and the
remaining runtime cases stay pending in the conversion report.
