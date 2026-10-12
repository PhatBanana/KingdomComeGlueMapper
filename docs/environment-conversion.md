# Environmental conversion

The production travel builder now imports environmental entities across the
main KCD1 `rataje` map's selected initial world. This is not a Skalitz-only patch.
The installed development build uses the same converter.

## Coverage

| Component | Converted |
| --- | ---: |
| Particle emitters | 1,307 |
| Fog volumes | 21 |
| Audio entities | 1,355 |
| Linked audio boundaries | 931 |

Audio output contains 1,004 `AudioAreaAmbience`, 70 `AudioAreaRandom`, 277
`AudioTriggerSpot` and four `AudioAreaEntity` instances. Thirty-two source
random emitters become area ambience because their native substitute loops;
they must not repeatedly start that loop on a one-shot timer.

The converter preserves source transforms, area geometry, obstruction flags,
priorities and fade distances, and remaps links to the new entity IDs. It
retains supported authored flowgraphs while removing authoring/debug input
nodes. Particle references resolve against native KCD2 particle definitions.
Missing sound and reverb names use explicit native equivalents in
`tools/environment_audio.py`. Bird and insect substitutions may represent
different species/recordings. No KCD1 audio banks or replacement global KCD2
audio libraries are installed.

## Exclusions and remaining validation

- 6,061 environmental source entities belong to inactive/quest/later-state
  layers and remain deferred. Separate source maps and DLC states are not
  covered by this pass.
- One empty particle reference has no effect to convert.
- 46 legacy global-mixer entities are retired because their old RTPC controls
  have no established native equivalent. They are not mapped to unrelated
  KCD2 gameplay parameters.
- 28 audio entities have no remaining native ambient action, including empty
  authoring placeholders and a quest-music control. Per-entity reasons and
  individual retired controls are retained in the build receipt.
- Map-wide placement is not map-wide visual/listening acceptance. Every
  region, time-of-day transition, reverb boundary and substituted recording
  still needs broader validation.

## Player-spawn failure and correction

The first build allocated entity ID `30583` (`0x7777`) to the pond ambience
`gm_environment_20724`. CryEngine reserves this identity for the local player,
so player creation failed with `OnClientConnect failed`.

The allocator now skips that ID for both emitters and audio boundaries and
rejects allocation beyond the static entity-ID range. All linked references
use the allocated IDs. Regression tests cross the reserved ID with both an
emitter and a boundary. See CryEngine's
[local-player identity documentation](https://www.cryengine.com/docs/static/engines/cryengine-5/categories/23756813/pages/26216222).

## Validation — 13 October 2026

- Seven focused environmental tests, 12 travel tests and three wildlife tests
  pass.
- The staged archive preserves all 1,011 entries other than
  `objects_mission0.xml`, including the accepted wildlife and ladder data.
- The corrected installed build reaches `LEVEL_LOAD_COMPLETE` and `RUNNING`.
  The live player has entity ID `0x7777`.
- Live script inventory confirms all 1,355 imported audio entities and 21 fog
  volumes. All 1,190 nonempty imported play-trigger references resolve in the
  live engine; this checks registration, not the audibility of each sound.
- The user confirmed that the corrected build works. No claim is made that
  all 1,307 particle emitters were individually inspected.

Local evidence is under `outputs/EnvironmentAudit/Build03/`: the staged
`level.pak`, per-source `report.json`, and `runtime.log`. The installed archive
was checked against staged SHA-256
`7df08b26760f7ba1f8d664bd0710ac776c613426cff8d0184ced6694dd412c80`.
The previous working archive remains in
`outputs/EnvironmentAudit/Build01/baseline-level.pak`.

## Reproduction

Normal builds call `world_environment.build` from `region_travel.build`.
For a staged additive conversion against a level without this conversion:

```powershell
python tools/build_environment_test.py --source <KCD1-root> --target <KCD2-root> --level <baseline-level.pak> --output <fresh-output-directory>
python -m unittest discover -s tests -p test_world_environment.py
```

The staging tool validates native references and unrelated archive entries;
it does not automatically install or launch the result. Repeated conversion
of an already converted mission is rejected.
