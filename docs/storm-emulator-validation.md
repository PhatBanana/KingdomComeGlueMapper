# Storm role evaluator validation

Date: 2026-10-25. Developer tool: [Storm role evaluator](../tools/storm_lab/README.md).

## Verified implementation

- [x] Standard-library command line tool; runs without the game. Reads packages and the retail install in place with `zipfile`.
- [x] Resolves `Libs/Storm/storm.xml` and every listed source mod-first, then native; records SHA-256 of every file read.
- [x] Tolerates storm.xml sources missing from the retail install (retail lists `names/quests/predaniVChramu.xml`), and reports sources that only the mod lists and that are missing as errors.
- [x] Selector algebra: AND for `selectors`/`and`/`customSelector` without mode, OR for `or`/`mode="or"`, `not`, recursive custom selectors with per-soul caching, and duplicate custom selector bodies (disagreement is reported as ambiguous, never decided).
- [x] Short-circuit evaluation: an unsupported selector never hides a definite sibling result.
- [x] Explicit outcomes: forks (`hasRandomValue`, `isGameMode`, `isContentFilterActive`), UNSUPPORTED (`hasAttribute`, unknown tags, missing inputs) and assumptions with native evidence and an alternative semantic.
- [x] Sensitivity: a rule that is false only under an inferred semantic is listed, with what it would add under the alternative.
- [x] `customOperation` macros are expanded recursively; `addRole`/`removeRole`/`addMetarole` are applied in task, source and rule order, with conditional roles carrying their reasons.
- [x] Late `hasRole` readers are re-checked against the final role set.
- [x] Trade service contract for every `shopKeeper`-linked NPC; the role names are derived from the native shop macros.
- [x] Findings: character/voice references, voice group without character, merchant-side roles on non-keepers, unknown roles and inventory presets, native name capture, order-sensitive rules, mod rules selecting no soul, missing sources.
- [x] `audit.json`, `roles_by_soul.json` (quest_lab observation fixture), searchable `audit.html` and `junit.xml`; `run` scenarios with `results.json`, `report.html` and `junit.xml`. Exit 0 pass, 1 fail/unsupported, 2 could not run.
- [x] Developer-only entry point `tools/storm_lab_test.py`; Setup does not import it.

## Tests run

| Check | Result | Meaning |
| --- | --- | --- |
| `tests/test_storm_lab.py` | 21 passed | Synthetic-blob tests: selector modes, `not`, glob anchoring and case, unsupported/fork handling, voice via skald character, character-less voice, faction ancestry and labels, gender, combat level, duplicate custom selectors, remove after add, macro expansion, conditional roles, late `hasRole`, trade contract (pass, missing haggle role, duplicate trade, wrong gender, keeper without soul), merchant-role and voice-group findings, unknown role vs native capture severities, missing sources, scenario runner, reports and exit code 2 |
| Full suite `python -m unittest discover -s tests` | 2210 passed, 29 skipped | No existing test changed |

## Native evidence for the modeled semantics

All of these come from the retail install, read offline.

- `hasVoice` names are `voice.xml` `voice_technical_name` values (1,041 uses); `ID` is `voice_id`.
- The soul → `skald_character_name` → `voice_id` join is consistent. 232 of 233 native Merchants-group souls pass `hasMerchantVoice` under it, and every one of the 1,239 native souls with a voice group has a character whose voice is in that group.
- `voice_group_name` is the baked output of `characters/voiceGroups.xml` (`assignVoiceGroup`):
  - 222 of 233 Merchants souls are traders;
  - 359 of 364 Bandits souls are `isBandit`;
  - 515 of 528 Guards souls are `isAuthorityFigure`.
- The `characters` task is commented out in retail `storm.xml`.
- `hasMerchantVoiceOrNoCharacter` (`base.xml`) is the evidence for treating character-less souls as voiceless.
- `role.xml` maps roles to metaroles (for example `VYJEDNAVANI_MUZ` → `VYJEDNAVANI`).

## Installed-package run

Run on `jobs/20261022-160453-a9a40cd-main-fresh/package/map`:

- 72 converted souls, 963 Storm sources (321 from the mod).
- Trade contract: 10 of 10 keepers PASS.
- 0 errors; 48 review findings (voice-group-without-character).
- Info: 10 keepers miss the explicit `VYJEDNAVANI` metarole because the mod sources follow `postprocess/negotiation.xml`. `role.xml` already maps the role.
- Unsupported evaluations: `hasAttribute` 202, `hasCombatLevel` without `combat_level` 168, duplicate `isSoldier` 12.
- Run time about 5 s.

Native self-check (`--native-selfcheck 9000`): all 8,206 native souls under all native rules, in about 5 minutes. This has no oracle; it measures coverage only.

- 55.76 M rule×soul evaluations: 511,393 APPLIES, 26,513 FORK and 33,313 UNSUPPORTED (0.06 %).
- UNSUPPORTED comes only from `hasAttribute` (23,835), `hasCombatLevel` on souls without `combat_level` (23,541) and the duplicate `isSoldier` (2,294).
- `hasVoice` is fully evaluated.

## Remaining boundaries

- [ ] Storm evaluation order and `hasRole` timing (assumption `rule-order`).
- [ ] Whether the engine gives character-less souls a voice at runtime (assumption `hasVoice-no-character`). The single confirming read is in the findings file §4.
- [ ] `hasAttribute`, soul stats and skills.
- [ ] Appearance targets (`setBody`, `setHead`, …) are recorded but not resolved.
- [ ] Runtime role changes from quests, and anything after Storm: dialogue availability, voice and line playback.

This is not native-runtime verification. No installed files, saves or game processes were touched.
