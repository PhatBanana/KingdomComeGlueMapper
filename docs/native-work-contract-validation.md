# Native work-contract validation

Validated 14 October 2026 against the development game, build
`release_1_5_116656_117`. No game binary is modified or distributed.

`XGenAIModule.dll` SHA-256:
`e20db768f17284a6eca8d6bb7411e6d2f08876d41eb5279368679d4d3ccd4847`.

The original compiler used shipped runtime XML examples as its capability
catalog. Those examples do not exercise every registered native operation.
Absence from that catalog therefore does not establish lack of engine support.
Additional contracts require evidence; the proximity contract supplement is
restricted to the tested module hash. Other builds keep their example-derived
catalog until validated.

## Evidence and implemented conversions

| Contract | Evidence | Import behavior |
| --- | --- | --- |
| Nonempty string member defaults | A temporary native SmartObject brain read two custom types. Raw `1h` produced `1h`; quoted `'1h'` included the quotes in the resulting string. | Preserve raw string text, including text resembling enum expressions; do not expression-quote it. |
| `NumericalOperation:randRange` | Native execution with literal input `0`, variable input `high=4`, and output `$random`: 1,704 samples, values 0 through 4, no out-of-range samples. | Preserve constants and bare input variable names; emit output as a variable reference. Do not alter the original bounds. |
| `NotNearPlayer` | Registered native factory and successful native tree parsing using `target` and `result`. Probe branch was not executed. | Preserve target/result references. Runtime proximity outcome still needs actor-level testing. |
| `BehaviorTagCatch` | Native enum registration contains the original request/result names. The probe parsed RequestOK, BehSucces and BehFail handlers. | Preserve events, handler order and subtree lifetime. Actual event delivery remains part of work-cycle acceptance. |
| Link `defaultPruning` | Native `C_TagLibrary::Load` reads this attribute as a boolean. | Preserve source pruning on imported home/inverse links. |
| Exclusive named area/object request | Native `CallBehavior` examples establish unified target/name dispatch. | Translate single exclusive named requests, preserving supplied request flags. Target template registration remains a separate dependency. |

Local evidence is in `outputs/OpeningStart/WorkContractRuntime01`, including
`runtime02-probe.log` and `runtime03-probe.log`. Probe logging deliberately used
Error severity so engine logs would retain the values; these marker lines are
not engine failures. The diagnostic entity and temporary installed PAK were
removed, and the test game was closed after capture.

## Source conversion result

`ControllerAudit09` uses the same source discovery as `ControllerAudit07`.
Complete emitted trees increased from 239 to 279. The original `housework`
tree and `fatherPatch` scheduling wrapper now convert as whole trees, with no
unresolved sites. These totals include shared and alternative programs and
are not a quest completion percentage.

The full blacksmith cycle still requires animation, tool, LOD and cleanup
adapters. Mother's scheduling wrapper requires its dialogue helper conversion.
Full smart-area registration and actor execution are not established by these
tests. The production development scene was not replaced by the diagnostic
package; fresh New Game, interruption, save/load and attack-onset acceptance
remain separate runtime milestones.
