# Developer tools

## Quest and NPC simulation

[Quest & NPC Tests](quest_lab/README.md) interprets converted quest graphs and
controller behaviors and bounded dialogue logic offline, with deterministic time, scenario assertions,
save/replay and explicit engine outcomes. Use `quest_lab_test.py demo` for
converter-generated examples, `run` for JSON/HTML/JUnit results, `inventory`
to inspect a converted package's coverage, and `audit --source-graphs` for every
installed quest plus dry runs of all KCD1 source quest-state graphs. This is a developer tool, separate
from consumer Setup; emulation does not establish native gameplay success.

## Character and clothing validation

[Clothing & Body Test](clothing_lab/README.md) is a standalone 3D workbench and command-line validator for converted male/female characters, clothing layers, and every KCD1 soul record. Launch `clothing_lab_app.py` for the viewer or `clothing_lab_test.py` for repeatable audit reports. It is separate from consumer Setup.

Use `clothing_lab_matrix.py` for the complete single/pair audit, bounded full-layer enumeration, resumable case reports, and isolated native-layer repair candidates. The [clothing validation checklist](../docs/clothing-validation-checklist.md) records exact combinations confirmed by the enabled checks and the remaining coverage gaps.
