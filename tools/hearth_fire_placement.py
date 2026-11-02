"""Place the generated hearth cluster from its KCD1 counterparts, not the donor.

`cooking_pots` builds every converted fireplace from a Trosky donor cluster and
moves pot, cauldron, steam and ladle onto the authored KCD1 pot trigger. Two
pieces were not placed from KCD1 data:

- the log-pile fire prefab was pinned to the KCD1 flame origin. KCD1 fire
  prefabs are flame and light only, and the inset (black kitchen) hearths
  put that origin about 0.11 m above the hearth top, so the native log pile
  floated on the ledge beside the cooking pit (Skalitz, 821,3488);
- the cook-on-fire trigger stayed donor-relative, 0.57 m from the authored
  KCD1 `st_fire` trigger at corner hearths, 1.4 m at the inset hearths and
  0.75 m at camp fires, and 0.25 to 1.1 m above it.

This step applies the rule `cooking_pots.convert` now uses on clean builds to
an already built package, so both agree and a second run changes nothing:
the fire rests on the surface the fireplace's own pot stands on (never
raised, never moved sideways) and the cook trigger stands on the KCD1 fire
trigger. Kettle, cauldron, steam and ladle keep their KCD1 pot anchor.
"""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from cooking_pots import DONORS, PREFIX, cluster_placements, inventory, vector
from upgrade_map import read

VERSION = 1
LEVEL = 'Data/Levels/kcd1_travel/level.pak'
SOURCE_LEVEL = 'Data/Levels/rataje/level.pak'
TOLERANCE = 1e-6
ROLES = (("proceduralObject['fire']", 'fire'), ("kettleTrigger['pan']", 'pan'))
RULE = ('fire: x/y = KCD1 flame origin, z = min(origin z, resting height of the fireplace pot '
        'item, else its cooking trigger), never raised; pan trigger: the KCD1 st_fire trigger')


def plan(mission, source):
    """Return rewritten mission bytes (None when nothing moves) and a report."""
    source_entities, pots, _ = inventory(source)
    root = ET.fromstring(mission)
    by_id = {e.get('EntityId'): e for e in root.iter('Entity')}
    by_name = {e.get('Name'): e for e in root.iter('Entity')}
    moved, skipped, unchanged = [], [], 0
    for pot, owner, kind in pots:
        name = f"{PREFIX}{pot.get('EntityId')}_{DONORS[kind]}"
        fireplace = by_name.get(name)
        if fireplace is None:
            skipped.append({'source_pot': pot.get('EntityId'), 'reason': 'not converted'})
            continue
        links = {l.get('Name'): l.get('TargetId') for l in fireplace.findall('EntityLinks/Link')}
        placements = cluster_placements(owner, pot, source_entities)
        for link, role in ROLES:
            target = placements[role]
            if target is None:
                unchanged += 1  # donor-relative placement; no KCD1 counterpart
                continue
            entity = by_id.get(links.get(link))
            if entity is None:
                raise ValueError(f'{name}: converted fireplace has no {link} link')
            current = tuple(map(float, entity.get('Pos').split(',')))
            if max(abs(target[i] - current[i]) for i in range(3)) <= TOLERANCE:
                unchanged += 1
                continue
            entity.set('Pos', vector(target))
            moved.append({'entity': entity.get('Name'), 'role': role, 'fireplace': name,
                          'source_pot': pot.get('EntityId'), 'source_fireplace': owner.get('EntityId'),
                          'kind': kind, 'before': list(current), 'after': list(target),
                          'lowered_m': round(current[2] - target[2], 6)})
    report = {'version': VERSION, 'rule': RULE, 'fireplaces': len(pots), 'moved': moved,
              'moved_by_role': {role: sum(1 for m in moved if m['role'] == role) for _, role in ROLES},
              'unchanged': unchanged, 'skipped': skipped, 'runtime_verified': False}
    if not moved:
        return None, report
    return ET.tostring(root, encoding='utf-8', xml_declaration=True), report


def stage(mod, source, output):
    """Dry run into a new folder; the package is not modified."""
    from build_horse_trader_test import rewrite, digest
    mod, source, output = map(Path, (mod, source, output))
    if output.exists():
        raise FileExistsError('Choose a new hearth placement staging folder')
    level = mod / LEVEL
    with zipfile.ZipFile(level) as archive:
        mission = read(archive, 'objects_mission0.xml')
    with zipfile.ZipFile(source / SOURCE_LEVEL) as archive:
        updated, report = plan(mission, archive)
    report['baseline_sha256'] = digest(level)
    report['changed_entries'] = []
    if updated is not None:
        rewrite(level, output / LEVEL, {'objects_mission0.xml': updated})
        report['staged_sha256'] = digest(output / LEVEL)
        report['changed_entries'] = ['objects_mission0.xml']
    output.mkdir(parents=True, exist_ok=True)
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def upgrade(package, source):
    """Shared finalization step for clean builds and completed-package upgrades."""
    from setup_package_upgrade import rewrite
    from upgrade_map import digest as file_digest
    package, source = Path(package), Path(source)
    with zipfile.ZipFile(package / LEVEL) as archive:
        mission = read(archive, 'objects_mission0.xml')
    with zipfile.ZipFile(source / SOURCE_LEVEL) as archive:
        updated, report = plan(mission, archive)
    report['changed_entries'] = []
    if updated is not None:
        rewrite(package, LEVEL, {'objects_mission0.xml': updated})
        report['changed_entries'] = ['objects_mission0.xml']
    return {LEVEL: file_digest(package / LEVEL)}, report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mod', 'source', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    summary = stage(**vars(parser.parse_args()))
    print(json.dumps({k: v for k, v in summary.items() if k != 'moved'}, indent=2))
    for move in summary['moved']:
        print(move['role'], move['entity'], move['before'], '->', move['after'])
