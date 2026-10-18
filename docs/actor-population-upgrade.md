# Source actor population conversion

Explicit actor selection now enters the campaign dependency compiler through
`compile_campaign(..., actor_roots={source_quest: [source_soul_name, ...]})`, or
the equivalent `--actor-roots` JSON file. Actor selection does not activate all
profiles associated with those actors.

The shared path:

- resolves source soul, instance, placement and profile ownership;
- imports the selected actors' registered work trees and their include closure;
- preserves source schedules, with unsupported dispatch reported as pending;
- follows selected actors' home, work and ownership links into the world graph,
  without recursively expanding every neighboring NPC;
- discovers production dialogue branches through source role membership,
  retaining event/service kinds and excluding source test branches;
- adds quests referenced by dialogue effects and expanded quest predicates to
  the compiler's dependency roots;
- feeds work dependencies and schedules to the existing native registration
  and population assembly stages.

There are no charcoal NPC names or quest-specific state changes in these
converters. The actor-root manifest is a content selection, not replacement
quest logic.

## Current validation boundary

The three requested charcoal actors were resolved against installed KCD1 data
on 2026-10-19. Their work closure contains 78 registered programs, 166 world
entities and 174 world links, with no unresolved world graph endpoints. This
includes the market coal-pile Stash, workers' homes, kilns and work helpers.
Their production dialogue references 17 source quests, including later quests.
These are discovery counts, not counts of successfully converted runtime jobs.

The market seller's opening-quest purchase service was subsequently verified
in-game by the user and added to setup recipe 29; see `source-merchant-purchase.md`.
The full three-actor population remains incomplete. Remaining
conversion includes source eat/sleep dispatch, legacy kiln/work operations and
all selected dialogue event/service kinds. The compiler must not claim that placing three NPCs with idle
activities completes this work.

Focused tests cover explicit actor identity/placement selection, missing and
ambiguous roots, library tree scoping, profile ownership, actor-owned world
dependencies, connected dialogue quest dependencies, and runtime range/random
route selection. In-game routines, trading and later dialogue still require
validation after complete conversion and package integration.
