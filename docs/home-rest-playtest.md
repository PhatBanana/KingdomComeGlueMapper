# Native home-bench rest

The next small schedule conversion gives otherwise pending houseworkers a native
bench-rest activity. It uses the source `housework` gender branch, the home's
actual `hangingOut` behavior binding, and its linked seat objects. No actor name
or fixed coordinate selects the conversion.

This is a bounded activity, not the complete housework controller. Setup recipe
46 applies it only to importer-owned pending arrivals, after fence repair has
been considered. Existing repair, sweeping, city-walking, merchant and quest
activities remain in place. Both male and female actors are checked against
their source phase list; a phase absent from that list is never assigned.

The source normally prefers outdoor seats in normal weather and falls back to
seats without the `outside` link tag. This first conversion accepts only areas
with no eligible outdoor-seat branch. It excludes dice tables and parent or
inventory links, validates the source search and reservation contract, and
reuses already converted bench helpers. Areas needing weather selection remain
pending. A seat lacking the source `outside` tag is not a geometric claim that
it is inside a building.

The native KCD2 sitting activity owns approach, reservation, animation, dialogue
interruption and cleanup. The adapter preserves source work hours and shares
existing seat identities. The current native wait is 15 seconds; source rest
duration, wait-to-time-change and rotation among housework phases remain explicit
pending work. The report therefore does not mark the full work program complete.

## Validation and stage

Eight focused tests cover linked-only selection, dice exclusion, outdoor-branch
deferral, source-contract changes, inherited depth, source binding, existing-seat
reuse, work hours, modified-owner rejection, repeat application and pending-phase
reporting. These tests are independent of installed game files.
The full repository suite ran 1,701 tests successfully, with 17 skipped.

The real-data setup-path stage is
`D:\BuildKCDMod\home-rest-20261022-validated`. In the selected Skalitz population,
one remaining eligible actor is `ska_skinner`, using the source seat linked to
`Ska_SA_Home2`. That name is a playtest subject, not an implementation selector.
Archive CRCs, scheduler targets and mounted resource aliases pass validation.
All 62 NPC entities are unchanged from the installed baseline. Only the worker's
incoming scheduler edge and its owned arrival hub change; existing seat resources
are reused.
The stage contains changed level/travel archives and a report; it is not a full
standalone mod package. It was installed into retail on 22 October 2026 over the
verified fence-update baseline. Installed archive hashes and the ownership
receipt passed verification. The installation journal and rollback copies are
under `retail-install/` in the stage directory. In-game behavior remains unverified.

## Retail acceptance

1. Install over the matching fence-update baseline with rollback retained.
2. Observe the worker walk to the home seat and sit with correct contact/facing.
3. Interrupt with dialogue and verify the seat is released and can be used again.
4. Check leaving/returning, schedule changes, and save/reload.
5. Verify existing town benches, fence repair and other work still run, and check
   the log for new pathing or animation errors.

Generated scheduler validation does not establish these runtime outcomes.
