"""Audit converted container locks against their KCD1 sources (read-only).

A Skalitz play session on 2026-10-29 reported chests that "still show
locked". `ordinary_containers` copies each authored Stash's `bLocked`,
lockpick flag and key item, and KCD2's Stash script locks a chest at spawn
only when `bLocked` is set, so a converted chest is locked exactly when its
KCD1 original was. This audit lists every `gm_container_<id>` whose lock flag
or key differs from its source, so a dry run or review can show that set is
empty, and can list the containers inside a region with both states.
"""
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from upgrade_map import read

LEVEL = 'Data/Levels/kcd1_travel/level.pak'
SOURCE_LEVEL = 'Data/Levels/rataje/level.pak'
CONVERTED = re.compile(r'^gm_container_(\d+)$')
TRUE = frozenset(('1', 'true', 'True'))
ZERO_KEYS = frozenset(('', '0', '00000000-0000-0000-0000-000000000000'))


def lock_state(entity):
    lock = entity.find('Properties/Lock')
    if lock is None:
        return False, ''
    key = lock.get('guidItemClassId', '').lower()
    return lock.get('bLocked', '0') in TRUE, '' if key in ZERO_KEYS else key


def source_stashes(source):
    stashes = {}
    for name in source.namelist():
        lower = name.replace('\\', '/').lower()
        if lower != 'objects_mission0.xml' and not (lower.startswith('layers/') and lower.endswith('.xml')):
            continue
        for entity in ET.fromstring(read(source, name)).iter('Entity'):
            if entity.get('EntityClass') == 'Stash':
                stashes.setdefault(entity.get('EntityId'), entity)
    return stashes


def audit(mission, source, region=None):
    """Compare every converted container with its KCD1 stash; never modifies anything."""
    stashes = source_stashes(source)
    containers = locked = 0
    mismatches, inside = [], []
    for entity in ET.fromstring(mission).iter('Entity'):
        match = CONVERTED.match(entity.get('Name', ''))
        if not match or entity.get('EntityClass') != 'Stash':
            continue
        containers += 1
        converted_locked, converted_key = lock_state(entity)
        locked += converted_locked
        original = stashes.get(match.group(1))
        if original is None:
            mismatches.append({'name': entity.get('Name'), 'field': 'source', 'converted': 'present', 'source': 'missing'})
            continue
        source_locked, source_key = lock_state(original)
        if converted_locked != source_locked:
            mismatches.append({'name': entity.get('Name'), 'field': 'bLocked', 'converted': converted_locked, 'source': source_locked})
        if converted_key != source_key:
            mismatches.append({'name': entity.get('Name'), 'field': 'guidItemClassId', 'converted': converted_key, 'source': source_key})
        if region is not None:
            x, y, _ = map(float, entity.get('Pos', '0,0,0').split(','))
            if region[0] <= x <= region[2] and region[1] <= y <= region[3]:
                inside.append({'name': entity.get('Name'), 'pos': entity.get('Pos'), 'locked': converted_locked,
                               'key': converted_key, 'source_locked': source_locked, 'source_key': source_key,
                               'source_layer': original.get('Layer', '').split('{')[0]})
    report = {'containers': containers, 'locked': locked, 'unlocked': containers - locked,
              'mismatches': mismatches, 'rule': 'KCD2 Stash:Reset locks only when Properties.Lock.bLocked is set; '
              'the converter copies bLocked, bCanLockPick and the key item from the KCD1 stash'}
    if region is not None:
        report['region'] = {'box': list(region), 'containers': inside,
                            'locked': sum(1 for c in inside if c['locked'])}
    return report


def stage(mod, source, output, region=None):
    mod, source, output = map(Path, (mod, source, output))
    with zipfile.ZipFile(mod / LEVEL) as archive:
        mission = read(archive, 'objects_mission0.xml')
    with zipfile.ZipFile(source / SOURCE_LEVEL) as archive:
        report = audit(mission, archive, region)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'container-lock-audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mod', 'source', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--region', type=float, nargs=4, metavar=('X0', 'Y0', 'X1', 'Y1'))
    arguments = parser.parse_args()
    summary = stage(arguments.mod, arguments.source, arguments.output, arguments.region)
    print(json.dumps({k: v for k, v in summary.items() if k != 'region'}, indent=2))
    if 'region' in summary:
        print('region containers', len(summary['region']['containers']), 'locked', summary['region']['locked'])
