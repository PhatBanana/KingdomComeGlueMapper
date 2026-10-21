"""Shared clean-build/resume adapter for the selected opening quest layout."""
import json
from pathlib import Path
import zipfile

from campaign_quest_start_placement import apply, load, report
from upgrade_map import read


# Explicit slice selection, like setup_gameplay.SCENE_PEOPLE. Coordinates and
# actor identity are always resolved from source links. This is the intro
# relocation point, not the later sitting point or training-ground destination.
SELECTIONS = (('q_tutorial_swordOne', 'vanek', 'vanekTeleport'),)
RECORD = 'quest-start-placements.json'


def plans(source):
    return load(source, 'rataje', SELECTIONS)


def upgrade(package, source):
    """Called on a private package by the normal transactional finalizer."""
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    if source is None:
        raise ValueError('KCD1 source required to resolve quest starting placements')
    package = Path(package)
    records = plans(source)
    level = 'Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(package/level) as archive:
        mission, changes = apply(read(archive, 'objects_mission0.xml'), records)
    if changes:
        rewrite(package, level, {'objects_mission0.xml': mission})
    result = report(records)
    (package/RECORD).write_text(json.dumps(result, indent=2), encoding='utf-8')
    return {level: digest(package/level), RECORD: digest(package/RECORD)}, result


def validate(mission, evidence):
    from campaign_quest_start_placement import VERSION
    if (evidence.get('version') != VERSION or evidence.get('mode') != 'selected_quest_start_layout'
            or [(r['quest'], r['actor_role'], r['place_role']) for r in evidence.get('placements', [])]
            != list(SELECTIONS)):
        raise ValueError('Missing current quest start placement evidence')
    _, changes = apply(mission, evidence['placements'])
    if changes:
        raise ValueError('Quest actors or idle delegates still use base world placements')
    return evidence
