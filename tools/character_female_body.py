"""Select complete source female geometry before the shared rig conversion.

The standard KCD1 s2_body is limbs only. Its companion s2_body_v2 includes
upper torso geometry in the same source proportions and texture layout.
Do not replace it with a differently shaped native KCD2 body.
"""
from pathlib import PurePosixPath


def complete_source_body(model, available):
    path = PurePosixPath(model.replace("\\", "/").lower())
    if path.name != "s2_body.skin":
        return model
    replacement = str(path.with_name("s2_body_v2.skin"))
    if replacement not in available:
        raise ValueError("Complete source female body is missing: " + replacement)
    return replacement
