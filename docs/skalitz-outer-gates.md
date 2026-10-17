# Skalitz outer gate correction

The previous test override lifted two `castle_talmberk_grate.cgf`
placements at (665.927, 3467.762) and (725.795, 3473.848). These are castle
portcullises, not the outer town palisade gates requested for travel testing.

The intact source `sv_state0` layer has three `wall_wooden_gate.cgf`
gatehouses near (750.023, 3530.041), (862.792, 3395.717), and
(825.107, 3524.093). Each has separate `barn_door01tall_left.cgf` and
`barn_door01tall_right.cgf` brushes. `tools/skalitz_outer_gates.py` records
the six original transforms and rotates those leaves in opposite directions
by 90 degrees about their placement origins. It transforms their world-space
bounds with the same rotation and expands HLOD bounds conservatively.
Gatehouses and neighbouring walls remain unchanged. The two previously raised
castle portcullises return to their original positions; Talburg is unaffected.

This remains an explicit test-world override, not animated campaign door logic.
Unknown transforms, missing leaves, and duplicate placements fail validation.
Already corrected placements are accepted without further movement.

Setup recipe 7 applies this to fresh builds and migrates completed recipes
3–6 through the existing transactional resume path. Baking checkpoint code
and signatures were not changed. A running older setup cannot acquire new
Python code; resume with setup 0.3.7 to apply this correction.

Validation: read-only transformation of the installed Mod Tools level found
all six leaves and restored two portcullises. A second pass was byte-identical.
Unit tests cover transforms, collision/render bounds, unrelated brushes,
idempotence, malformed source transforms, and package receipt migration.
In-game passage and visual clearance still need testing.
