# Generic seated-work upgrade

The schedule upgrader recognizes `final/sa_embroider.xml:embroider_sit` and
converts it to KCD2's native `so_benchActivity.embroidery` activity. Selection
does not depend on an NPC name, quest, town or fixed coordinates.

The source area's direct seat links select the converted benches. Parent and
inventory links are excluded, as are benches with tables. Existing bench slots
are shared reservation resources, not copied per NPC. The compiled graph is:

```
NPC (source work interval)
  -> bench activity (embroidery override, native female restriction)
     -> one of the area's converted seats (use, exclusive resource)
```

Native stance and unstance actions own movement, animation and interruption.
There is no animation timer, teleport, forced initialization or per-NPC Lua
patch. Source schedule hours remain on the incoming activity. The ordinary
population work upgrade enables this adapter for eligible imported idle
schedules; existing quest, merchant and converted work schedules are retained.
Other embroidery variants and other work activities are not enabled by this
adapter. Missing converted seats or changed native contracts fail conversion.
Recipe 42 requires the normal upgrade for older completed packages, including
recipe 41; the adapter is included in the frozen setup converter inventory.

## Repeatable staging

Use `tools/build_person_schedule_test.py --jobs` with source/target game roots,
the installed level and travel PAK paths, a fresh output directory, and one or
more `--person` selections. The person arguments select the test subjects only;
the upgrader discovers their work routines, intervals and seats from source data.
The output is a pair of staged replacement archives and a report, not a complete
standalone mod installation.

The first local fixture uses `ska_johanka` and `ska_sarka`, whose source schedules
already request this activity. Johanka's home links two benches; Sarka's links
one. Their source work intervals are both 0–1440. No new hours were invented.

## Runtime acceptance

After installing the staged package through the normal package workflow and
restarting the game, use a fresh session with those source profiles active:

1. Observe an NPC walking to one of her authored benches and sitting down.
2. Verify that seated embroidery starts and continues, with no animation queue
   overflow, missing unstance or repeated action-state/path failures in the log.
3. Start and finish a conversation. Verify that work stops cleanly and can resume.
4. Occupy a seat and check that another NPC does not reserve the same slot at
   the same time. Where an alternative exists, observe how the scheduler uses it.
5. Leave the area and return. Check that the NPC resumes a valid activity without
   duplicated props, frozen stance or a forced initialization command.
6. Check an unrelated worker and a quest actor for unchanged behavior.

Automated tests cover interval preservation, repeated intervals, shared seat
registration, native reservation/stance requirements, unsupported seats and
protection of already converted schedules. Archive validation is not evidence
that the runtime acceptance steps have passed.
