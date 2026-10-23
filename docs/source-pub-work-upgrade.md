# Source pub work upgrade

The profile work builder and saved-package upgrade now add two bounded choices
to existing source `final/sa_pub_v3.xml: Bartender` schedules:

* Table cleaning resolves the source area's one-hop `pubTable` links and each
  table's authored `Place1` helper. A shared, exclusive activity uses the shipped
  `bathmaid_cleaningTable` native action (`Bartender_CleaningTable`, aligned to
  the activity object). The native body animation is verified by controller;
  current retail data supplies the untagged female variant only. Unsupported
  controllers remain pending rather than receiving an idle substitute.
* Resting resolves the source `resting -> getBench` selection, excludes reserved
  table edges and reserved benches, and reuses converted native bench resources.
  It does not clone seats or invent nearby sitting destinations.

Both choices retain the existing actor work windows (including sleep clipping),
sweeping, quest activities and services. Deterministic resource and phase GUIDs
make repeated upgrades idempotent. Modified resources fail validation instead
of being overwritten. `setup_pub_cleaning.upgrade` applies the same conversion
to older saved packages and updates the mounted compiled scheduler alias.

This is not the full source bartender dispatcher. Order queues, food/drink
carrying, cleanup after closing, weather interruption and phase ordering still
need their own conversions. Reserved/custom seat preferences are excluded.
The repeated `bartender_wiping` monologue is explicitly reported as pending:
its source timeout and flags need native equivalents before enabling repetition.

Read-only validation against the installed world found five cleaning contacts
and eight source benches for the existing bartender. No game installation or
runtime playtest was performed. Regression tests cover source selection drift,
preserved clocks and sweeping, resource conflicts, gender support and repeat
application. The detailed XML proof is under
`reports/jobs-completion/pub-cleaning-proof.json`.

## Remaining source coverage

The static Skalitz profile inventory has 55 actors. Forty-six have resolved
daycycle work links across 13 behavior identities; nine have no direct source
activity link and need quest/controller ownership resolved, not invented jobs.
The identities are farmer (6 actors), city walking (8), blacksmith (1), merchant
(5), housework (12), garrison guard (5), shop guard (2), compound camping (1),
horse handler (1), bartender (1), charcoal-selling station (1), embroidery (2)
and gambler (1). These counts describe source assignments, not fully verified
runtime coverage.

The compound assignment is not missing local Skalitz labor:

* `sa_compoundworkcamp.xml:CompoundWorkCamping` delegates into
  `sa_compoundwork.xml:CompoundWork2_main`. This selects dynamic behavior names
  through the `compWork` subgraph, reserves the chosen workplace, invokes its
  behavior, and calls a dynamically named `*_timing` behavior. Camping also runs
  `banditsBarking` concurrently and handles time-change/LOD locks. A static seat
  or wait does not implement this contract. The sole profile actor with this
  assignment is Vanyek, but his two source-selected CampingLeader workplaces
  belong exclusively to `q_infiltrationandcapture_vanek` and
  `vra_vranik_state1/2/3`, respectively. Neither belongs to `q_skalitz_normal`.
  This later Vranik assignment must not be activated as a new Skalitz job.
  See [Source work ownership](source-work-ownership.md) for authoritative layer
  ownership and the reusable audit. This classification does not remove his
  source-authored home link or prove a cause of his observed travel.
* `q_skalitz.xml:gambler_playDiceTillYouRunOutOfMoney` selects `diceOpponent` or
  an authored leaning spot according to the actor's money and social-class
  minimum bet. It needs native dice-table ownership and that decision policy.

Other identities have bounded adapters but still lack parts of their source
dispatchers: household ordering/duration and fire refilling; guard assignment,
weather and post rotation; city shop/weather decisions; full pub customer and
closing service. Independent speech conversion remains gated on source cooldown
and flags. No synthetic job, clock, destination or random conversation was added
to hide these gaps.

## Completion and arbitration limits

The converted sweeping route follows finite authored successor links with its
source-derived dwell. Cleaning is one native action. Ordinary native bench use
waits for its action and then 15 game seconds before completion synchronization;
the native `activity_disableSchedulerLooping` context or keep-in-behavior
synchronization can retain a seat. The converter does not alter those contexts.
The additional choices therefore do not constitute a proven fair round-robin
or a reproduction of the authored phase sequence. Runtime selection and
interruption still require a playtest.
