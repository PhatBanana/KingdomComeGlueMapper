# Clothing conversion: rework required

Status: deferred by the user on 16 October 2026.

The active clothing conversion code has been restored to commit
`02a2c53` (Connect source actor systems and playable Skalitz work slice).
This is the previous committed baseline, not a claim of correct clothing
appearance or complete independent equipment support.

The uncommitted clothing experiment is preserved locally under
`outputs/clothing-rework-shelved-20261016/`, with original files, a Git patch
and a manifest. Existing generated outputs remain available. The unfinished
`outputs/ClothingCurrent` package remains uninstalled. The proposed temporary
fixed-outfit build was cancelled before implementation. No installed game
packages were changed by this rollback; restoring source does not rebuild or
revert previously installed game assets.

## Why the experiment was deferred

KCD1's separate garment meshes require a complete translation into KCD2's
regional geometry selection, material features, body coverage and equipment
layer rules. The experimental shared region banks retained garment geometry
but did not supply a complete compatible coverage contract. Several regions
exceeded the proposed four-bit allocation. Those bits also overlap native
KCD2 hiding groups; the native torso table already assigns every bit.
Increasing the allocation or bypassing the readiness flag is not a fix.

Material/normal conversion and fitting changes have useful evidence in the
shelved work, but they do not establish correct overall clothing assembly.
The current committed baseline retains its known visual limitations.

## Acceptance required before resuming installation

- Define region selection and coverage for the complete supported wardrobe,
  including source bodies, native wearers and mixed equipment.
- Preserve native/system hiding semantics and reject capacity conflicts.
- Verify material channels and fitting independently of geometry selection.
- Validate appearance in motion, equip/unequip, item transfer and save/load.
- Regenerate and verify a package before installing it.

Separate uncommitted work on weapon inventories and world character props
was retained. Clothing rework should remain deferred while other work proceeds.
