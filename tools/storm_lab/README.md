# Storm role evaluator (developer tool)

`storm_lab` computes, offline, the roles that KCD2's Storm program gives each
converted soul, and checks the role sets that native services look up (for
example trade). It reads a converted package and the retail install in place
with `zipfile`; it never extracts, modifies or launches anything.

It is a developer/CI tool. Setup never imports it and it is not part of any
installer payload.

```
python tools/storm_lab_test.py inventory <package> --target <KCD2> --output inventory.json
python tools/storm_lab_test.py audit <package> --target <KCD2> --output <dir> [--strict] [--native-selfcheck N]
python tools/storm_lab_test.py run scenario.json [...] --output <dir>
```

`<package>` is a converted package directory holding `Data/` (for example
`jobs/<job>/package/map`). `audit` writes `audit.json`, `roles_by_soul.json`,
`audit.html` and `junit.xml`. Exit codes: 0 pass, 1 error finding, failing
contract or unsupported selector (with `--strict`, review findings too), 2 the
tool could not run.

## What it models

- `Libs/Storm/storm.xml` resolved mod-first (a mod copy replaces the native
  file), every listed source resolved mod-first then native, task order, source
  order and rule order.
- Selector algebra: `selectors`/`and` = AND, `or`, `not`, `customSelector`
  (no mode or `mode="and"` = AND, `mode="or"` = OR), duplicate custom selector
  bodies (disagreement is reported as ambiguous), `customOperation` macros.
- Primitives: `hasName`, `hasVoice`, `hasACharacter`, `hasCharacterName`,
  `hasSocialClass`, `hasSoulArchetype`, `hasGender`, `hasFaction`,
  `hasFactionLabel`, `isPublicEnemy`, `hasCombatLevel`, `hasRole`. Runtime
  values (`hasRandomValue`, `isGameMode`, `isContentFilterActive`) are forks.
  `hasAttribute` and anything else is UNSUPPORTED.
- Roles task operations: `addRole`, `removeRole`, `addMetarole`. Operations of
  other tasks are recorded with provenance and inventory preset targets are
  resolved.

Every inferred semantic is listed in `selectors.ASSUMPTIONS` with its native
evidence and, where one exists, an alternative semantic. When a rule's outcome
for a soul would change under the alternative, the rule is listed in the
report's *Sensitivity* section instead of being silently decided.

## Outcomes

A selector result is a set of possible values plus the reasons it is not a
plain data fact: `fork:` (runtime value), `unsupported:` (not modeled),
`ambiguous:` (the data is ambiguous) and `assume:` (relies on an inferred
semantic). Roles are DEFINITE or CONDITIONAL. Scenario `has_role` assertions
pass only for DEFINITE roles; CONDITIONAL makes them UNSUPPORTED, never PASS.

## Contracts and findings

- `trade` for each NPC linked to a `Shop` as `shopKeeper` in a mod mission
  file: requires exactly one haggle role (`SMLOUVANI_<g>`, or any role whose
  role.xml row has metarole `SMLOUVANI`, which is how the shop finds the haggle),
  `VYJEDNAVANI_<g>`, and the `addShopRoles_ending_<g>` roles unless the keeper is
  on a ported KCD1 haggle role (KCD1 had no trade farewell; the native ending
  dialogs carry no scripts; `kcd1_shop_install`). A bound `GM_KCD1_OBCHODNIK` is
  reported as the keeper's trade path. The other `addShopRoles_essential_<g>` roles
  (`Z_DIALOGU`/`Z_CHATU`) open the native trade dialog: they are forbidden
  (second Trade option) only while a mod Skald Project/Level/Quest registers a
  generated FaderDialog whose `Shop` -> `OpenShop` sequence the keeper answers;
  otherwise they are the keeper's trade path. Source: `8edd58f`,
  `tools/shop_roles.py`.
- Findings: missing skald character or voice, `voice_group_name` without a
  skald character (a shape native data never has), merchant-side roles on a
  soul that is not a linked keeper, unknown roles, unknown inventory presets,
  native `hasName` rules that select a converted soul, hasRole readers placed
  before the source that writes the role, mod rules selecting no soul, and
  storm.xml sources missing from both layers (native-listed ones are tolerated).

`roles_by_soul.json` is an observation fixture for role-gated dialogue
scenarios in `quest_lab`.

Not modeled: native evaluation timing, runtime role changes from quests,
voice or line playback, and anything the engine does after Storm. Nothing
here is native-runtime verification. See `docs/storm-emulator-validation.md`.
