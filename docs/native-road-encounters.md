# Native road encounter upgrade

Setup 0.3.22 / gameplay recipe 58 adds a general encounter stage to fresh builds
and the saved-build upgrade. It resolves source event records, game profiles,
spawn tag points and road approach polygons, then binds suitable KCD2 native
event families to those locations. It does not enable legacy KCD1 event scripts
or transplant KCD2 town coordinates.

The first supported families are wandering travellers and attack-on-sight
ambushes. The selected native variants are the drunk traveller, Death, the
traveller questioning life's meaning, bandits and Cumans. Native time-of-day
conditions, dialogue, NPC pools, difficulty mixing, cooldowns, one-shot state,
combat and cleanup remain in their native graphs. Optional traveller daycycles
that reference KCD2 towns are excluded; native idle, dialogue and departure
behaviour remain.

The installed source world supplies **104 suitable locations**: 54 traveller
sites and 50 ambush sites. Another 50 source locations are deferred with a reason
in `world-encounters.json`. These need a separate scenery, route or quest adapter,
or lack authored spawn/approach data. This is not complete coverage of every
KCD2 encounter family. Caravans, camps, crime scenes and quest-specific variants
must not be activated without their required resources.

Fast-travel interruptions are disabled. The source provides NPC spawn points and
approach points but no verified, distinct close landing point for Henry. The
adapter removes native fast-travel variant data and marks the event cache
accordingly. Walking and riding are the intended activation paths.

The stage validates lexical graph dependencies, inherited assets, NPC/pool
catalog references, compiled scheduler targets, persistent entity links and
trigger geometry. Its receipt fingerprints only the content it owns, so other
world upgrades can coexist. Repeating the stage validates existing registration
without duplicating sites or rewriting archives. Setup's private staging
transaction protects the last verified package if any migration fails.

Validation on the installed source/target assets produced 63 native dependency
graphs, 104 site graphs, 1,157 generated entities, and a successful recipe-57 to
58 private-package upgrade. A second encounter upgrade preserved all three
output file hashes. Regression tests cover namespace promotion, literal archive
includes, source quest-condition exclusion, source coordinates, disabled
fast-travel data, and receipt/link corruption detection.

**Retail spawning, dialogue, combat, despawning and save/reload behaviour have
not yet been playtested.** Package validation is not evidence of those runtime
results. The existing installation is not changed by creating the candidate.
