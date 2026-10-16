# Forest supply chest (developer test)

Opt-in overlay for the installed combined mod. Run `tools/build_debug_supplies.py`
with `--source`, `--target`, `--mod`, and a fresh `--output` directory. The output
contains replacement travel/level/localization PAKs and one namespaced chest asset
PAK inside the same mod. Install only while the game and editor are closed.
The report records baseline and output hashes. Keep the recorded input package
available for rollback. Rebuild from that baseline; do not stack the overlay twice.

The chest uses KCD1's `chest_02/chest02.cga`, converted materials/textures, two LODs
and original rigid chest animations. It is unlocked and legal to loot. Its native
inventory preset gives 200,000 decigroschen (20,000 displayed groschen), a hunting
sword, short gambeson, hose and shoes. Equipment uses native KCD2 item records;
this does not claim conversion of KCD1 wearable meshes. Sword requirements are
4 Strength / 6 Agility, and all supplied clothing has zero Strength requirement.

The optional smithing supplies now include native recipe documents for a bearded
axe, horseshoes, basic hunting sword and common longsword. Their native recipe
tables determine ingredients for ten crafts of each: 30 scrap iron, 20 iron,
60 scrap steel, 10 fastening materials, 10 coin pommels, 10 simple guards and
10 pigskins. Read the documents to learn the recipes; native eligibility still
applies. These additions do not expand the getting-started quest's required loot.

For an already built package, `tools/build_smithery_followup.py --game <KCD2Mod>
--mod <installed-mod> --output <fresh-directory>` stages the updated inventory
preset while preserving every unrelated archive entry. Install only when closed.
Existing saved chest inventories need a one-time addition; changing their preset
does not reliably refill them. On 16 October these items were added to the live
`gm_debug_supply_chest` and all eleven class counts were verified in the game log.
Save normally to retain that live inventory. The updated package is staged in
`outputs/SmithingSupplies01`, not installed over the running game's archive.
The abandoned enclosed-furnace staging directory `outputs/RattaySmithery02`
was never installed; keep the existing small open native forge.

Placement is sampled from the installed converted terrain at X=3787, Y=1817,
roughly 55 metres northwest of the return coachman. The search marker is a compiled
24-sided trigger area of radius 35 metres centered at X=3780, Y=1825. Its center
is deliberately offset from the chest. The chosen terrain height is in report.json;
grounding against local rocks, vegetation and chest animation still needs visual QA.

`Getting started` is a region-local side quest, started once on arrival.
Closing the chest finishes the first objective only after all supplied item types
are absent from the chest. Opening, entering the search area or taking only the
coins is insufficient. The second objective marks Zora at Neuhof and completes
when the player chooses `I am looking for a horse` in her dialogue. This unvoiced
introduction returns to the shop choices without purchasing or closing dialogue.
A repeatable advice topic explains stamina, capacity, courage and speed.
There is no restock timer, repeated AddItem call, or proximity-completion fallback.
The native stash owns loot persistence; the quest State owns journal persistence.
All GlueTravel journals are classified as Side without renaming their saved states.
Native campaign quests are untouched. Future Rattay visit builds also default to Side.
The internal quest and original objective state paths are retained. A save with
the former one-step quest completed advances once to the new seller objective on
arrival. Completing the seller step prevents that upgrade from restarting it.

## In-game checks

1. Enter the KCD1 region and select the side quest. Confirm a search area on the
   correct region's map, rather than a precise chest pin.
2. Find and open the chest. Verify 20,000 groschen and four equipment items.
3. Close without looting, then take only money and close: quest stays active.
4. Collect the remaining equipment and close: the forest marker clears, the first
   objective completes and the Zora objective/marker appears.
5. Talk to Zora and select the introduction: the quest completes, while horse
   choices remain available. Talking before collecting supplies must not skip steps.
6. Equip the items, save/reload, then travel away and back. Confirm the chest does
   not refill and the completed quest does not restart. Also check an older save
   with only the chest quest completed advances directly to Zora.

Automated tests cover objective gating, marker geometry and custom-only quest
classification. Native database serialization is checked before installation.
These checks do not replace in-game loot, animation, marker and persistence tests.
