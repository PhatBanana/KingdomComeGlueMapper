# Skalitz castle access gate

The narrow plank door beside the castle entrance is a static source brush,
not a native animated door. The source `rataje/level.pak` stores it at brush
offset `116970320` in `sv_state0` (layer 718), using
`objects/props/doors/wooden_door_a_left.cgf`. Its authored hinge is at
`708.626831, 3485.499268, 59.802177`; its closed bounds are about 1.14 m wide
and 2.22 m tall. The neighboring source structures are the castle wooden walls.

`setup_static_gate_repair.upgrade` extends the explicitly selected playable
world gate overrides. It reads the original transform and bounds from KCD1,
checks the source identity, and verifies that the generated target mesh has
the same geometry (allowing the existing face-area metadata conversion).
It rotates both the leaf and its collision bounds a quarter turn around the
authored hinge. It does not change native animated doors or castle portcullises.

The repair accepts only the source pose or the exact repaired pose; unexpected
changes, missing gates, duplicate placements and conflicting bounds fail.
Unrelated HLOD records stay byte-identical, and the containing streaming
cluster is expanded conservatively. Repeating the upgrade does not rewrite
the level archive. When a completed LOD encoding receipt exists, it must match
the old terrain and HLOD data before the repair proceeds. The geometry edit
refreshes that validated receipt with the new HLOD hash without re-encoding
LOD bytes. A stale receipt is rejected.

Validation on 23 October 2026: seven focused unit tests passed. A private copy
of the installed package opened one gate and a second upgrade changed zero
files; LOD marker validation passed before and after both upgrades. The proof
is in `reports/jobs-completion/static-gate-proof.json`.
The installed game was not modified by that test. In-game passage and the
opened leaf's visual placement still need confirmation.
