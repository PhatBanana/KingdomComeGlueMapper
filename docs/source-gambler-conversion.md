# Source gambler conversion boundary

The source gambler now has a package upgrade adapter. Build-time graph and
dependency validation pass; in-game acquisition, dialogue and cancellation
remain unverified. This is not a claim that a game of dice has been played.

## Implemented package conversion

`tools/character_dice_resources.py` now builds the native resource graph using
authored source seat, cup, hidden-cup and kibitzer contacts. Sitting contacts
come from the source `Category(Sit)` helper, as in the existing bench converter.
Native-only dice and badge helpers retain donor offsets relative to the relevant
source cup. All internal links receive deterministic new identities; external
ownership is rejected. The donor quest's `dice_disabledMinigame` self-link is
excluded. Native opponent/challenger role-filtered scheduler ownership and seat
terminals are copied with remapped identities.

`tools/character_dice_policy.py` derives the uniform source social-class minimum,
rejects unsupported per-class overrides, and emits a private native opponent
variant. It removes the entire arriving money-grant branch, including the forced
success assignment, while preserving native insufficient-money cleanup. The
private table retains its native brain and dialogue inboxes and starts disabled.

`character_gambler_work.py` attaches the native opponent activity with its native
`BehaviorOverride=true` and `ProvidedRole=opponent` parameters, retaining the
disabled default template instead of enabling dice globally. It preserves the
native table brain, opponent/challenger role ownership, dialogue inboxes and
the opponent's readiness contexts and native dialogue calls. It removes the
ordinary converted bench interactions at those two seats to avoid independent
occupancy of the same seats; existing external users cause rejection.

The below-minimum branch calls the authored leaning contact from a separate
exclusive host. It does not reserve the dice table or either dice seat. Only source Misc
flags `leanBack=false|leanLeft=true|leanRight=true` are supported. The source
`so_leanSpot:use` persistent choice, unclamped RandomItem and disabled direction
changes are checked before emitting an equal left/right native RandomGate.
Native helper alignment is applied independently for left and right. Native
CallBehavior retains `ignoreDropUnloading=false`, and the context decorator owns
the non-looping wait lifetime. `gambler_schedule_activation.py` copies the native
`utils.money.hasmoney` and currency conversion helpers. Native
`SchedulerLinkActivation` drives a deterministic actor-specific funded tag;
the table and leaning choices require opposite values before acquisition.
The source-derived minimum is supplied to the native comparison. No polling
timer or globally toggled shared table is introduced.

The unfunded leaning choice has `HaltOnInvalid=true`: if funds are resolved
after initial scheduling, or the actor gains money, the inverted requirement
ceases to hold and leaning releases for a funded selection. The funded table
choice has `HaltOnInvalid=false`, preserving the native round's ownership while
paying a stake changes inventory; the copied native dice behavior owns round
completion and insufficient-money cleanup. Both choices remain beneath the
outer waking-clock edge, which halts at bedtime. This uses native scheduler
invalidation rather than assuming a LuaGate executes only once.

`gambler_dialogue_registration.py` registers the native `kostky` gameplay under
the retained `open_world/minihry` voice namespace, its dependency closure and
the project-scoped native dice fader holder. The audited debug branch and
unrelated native campaign codex reward are excluded. Native player aliases,
inherited types, dialogue dependencies and cutscene scene are validated.

`setup_gambler_work.upgrade(package, source, target)` discovers source-selected
actors, validates definitions, updates the map and mounted scheduler, and is
usable from fresh-build finalization and saved-package upgrades. The private
archive proof at `reports/jobs-completion/gambler-complete-proof/proof.json`
contains 24 resources (21 dice graph nodes, two leaning resources and an
independent leaning host), six
ownership rows, source minimum ten groschen (100 native currency units), and
the existing waking interval 352–1272 for `ska_e3_dicePlayer`. The incoming work
edge uses `HaltOnInvalid=true` so an acquired behavior expires at bedtime.
Running the helper again produced no file changes. Thirteen focused tests pass,
including preserved quest activity, clipped clock, rejection of quest ownership,
mounted scheduler updates and repeat upgrade checks. The proof is private;
it has not been installed or tested in the running game.

## Authored eligibility and destinations

KCD1 `Data/Scripts.pak`, `Libs/AI/quests/q_skalitz.xml`, tree
`gambler_playDiceTillYouRunOutOfMoney`:

- `Root/OnInit/Sequence/GraphSearch` resolves the direct `QuestPlace` links
  `diceTable` and `gamblerLeaningSpot` from `__object.id`, pruning parent and
  inventory edges.
- `Root/Behavior/LuaGate` checks
  `entity.inventory:GetMoney() >= SocialClass.GetEntitySocialClassData(entity).diceMinimumBet`.
- Its `Then/CallBehavior` invokes `diceOpponent` on the resolved table.
- Its `Else/CallBehavior` invokes `use` on the resolved leaning spot.

The source `Scripts/Script/SocialClass.lua` supplies `diceMinimumBet = 10` in
`SocialClass.defaultValues`; the inspected source has no class-specific
assignment to that property. The target still ships the compatibility file at
`Scripts/Systems/KCD1/SocialClass.lua`. Both engines' `Negotiation.lua`
`GetPlayerMoney` multiplies `inventory:GetMoney()` by ten, while the target
`Scripts/Entities/WH/Triggers/IndulgenceBoxTrigger.lua` compares the same getter
directly to its groschen price. The money getter is therefore available; missing
money API support is not the blocker. Availability of the Lua file alone does
not establish that its global has been initialized in every native AI context.

## Native resource and lifecycle mismatch

KCD2 `Data/Scripts.pak`, `AI/world/so_diceTable_new.xml`, tree `use_opponent`:

- `Root/OnInit` searches for `cupSlot1`, `hiddenSlot1`, `hiddenDiceOnTable1` and
  `diceOnTable1` links. The authored KCD1 table instead has `seat1`, `seat2`,
  `dice_cup`, `kibitzerPlace` and two `hiddenSlot` links. These are different
  resource graphs, not interchangeable label spellings.
- `Root/Behavior/Decision` uses decision `dice_gamblerState`. Its eligible
  gameplay branch enters `StanceElement` using `smartObject="$__resource.id"`,
  then owns cup/dice slots, opponent state and dice dialogue/message processing.
- The arriving/insufficient-money branch contains `CreateItem`. Directly
  adopting this behavior can grant an NPC money, contradicting the source
  instruction to stop playing when funds fall below the authored minimum.
- The native `dice_checkMoney` tree traverses inventory and sums currency stack
  amounts. Its internal amounts use tenths of groschen, unlike the source
  eligibility getter. The native minimum derives from a script parameter and
  must not silently replace the source social-class threshold.

KCD2 `Data/Tables.pak`,
`Libs/Tables/ai/smartEntity/SmartEntity__so_diceTable_new.xml` declares template
`9a3317b0-9c92-466e-bab6-571f23356bca` with brain
`4c3dd459-416a-7a92-6678-bd4222d57fa9`. `use_opponent` starts **Disabled**, has
one instance and native message inboxes. Registering a similarly named job
does not provide these dependencies or enable it correctly.

The native quest module
`Quests/Final/Barbora/open_world/minihry/kostky/dicebrary/enablediceminigame_.xml`
adds `dice_tableOverride` and `dice_readyToPlayMinigame` through
`LinkEffectNoData` and `SetEntityContext`. This is a native lifecycle contract
to preserve, not proof that a converted table is already usable.

## Leaning is conditional too

Source `Libs/AI/final/so_leanSpot.xml:use` reads the allowed leaning orientations
from the holder's script properties, chooses a permitted orientation and calls
`final/so_templates.xml:objectNewHelpers`. The authored gambler spot allows left
and right, not back. Native `AI/world/so_leaning_left.xml:use` and its right
counterpart use stance/unstance resources. Neither is a safe replacement for
the entire gambler job: the source selects leaning only below its money limit.

Runtime acceptance must check funded seating, a successful dialogue/game,
below-minimum leaning, and schedule cancellation without leaked reservations.
The independent resource branches and 83 native dialogue dependency graphs
pass static checks; actual engine acquisition and dialogue still require play
testing. No guessed timers, world coordinates, or unconditional idle fallback
are included.
