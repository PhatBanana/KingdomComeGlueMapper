# Smithing feedback repair

The observed Rattay attempt reached HALF_FINISHED_WORKPIECE, then reported
COLD_WORKPIECE, ALMOST_BROKEN_WORKPIECE and BROKEN_WORKPIECE. This is evidence
that the minigame was advancing; it does not prove a completion logic fault.

Two confirmed asset integration issues are repaired by
`tools/build_smithing_repair.py` and incorporated into fresh smithery builds:

- Both copied Smithery entities now link `forgeCoal` to their own existing
  small-forge coal GeomEntity. The Tachov donor 46192 lacked this link; another
  native Trosky station 26564 links it to coal 26555. The development
  PlayerModule.dll names this link alongside the observed missing-coal error.
- An exact copy of the native short-sword material is supplied at
  `Objects/characters/assets/blacksmithing/blacksmithing_short_sword1.mtl`.
  All four native short-sword skins embed this trailing-1 reference, whereas
  IPL_Characters-part0.pak supplies only the unsuffixed material. Keeping the
  alias in the same directory preserves relative texture references.

Receipt and previous-package backups: `outputs/SmithingRepair01/`.
Only the mission XML and the additional material alias change in the two
packages. Other entries are checked by CRC and size, then installation hashes
are verified. Four focused tests passed, including station-specific links,
preservation of unrelated links, idempotence and rejection of wrong geometry.

No difficulty, quality, progress or temperature settings are changed. No shader
source or cache is changed. The prayer altar revision remains separately staged.

Runtime acceptance is still required after restarting: repeat the short-sword
recipe, heat and hammer, reheat when cold, and finish. Confirm the missing-coal
and short_sword1 material errors do not recur. These fixes restore missing
connections/resources but do not establish why the prior attempt failed.
The separate f_bl_forge and blacksmithing_piece audio-control errors remain
unresolved. Native warning dialogue playback was confirmed in the previous log.
