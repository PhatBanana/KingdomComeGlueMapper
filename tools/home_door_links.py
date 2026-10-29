"""Port authored KCD1 home door links to the native KCD2 home-door contract.

KCD1 decided night locking inside AnimDoor.lua: a door with
`esInteriorType="home"` locked outside its keep-open clock whenever an NPC
passed through it. KCD2 removed that rule from the door script. Its crime AI
finds a home's doors from the owner's scheduler hub through `home_area` and
`crime_door[type(...)]` links (AI/crime/gethomedoors.xml), and the area label
carries the trespass level. `door_locks.convert_properties` drops the interior
enum on purpose and `campaign_doors` names the missing piece "area-link
conversion". This module is that conversion for the homes that
`character_person_world.register_person_world` has already registered.

Source link names map to native door kinds: `entrance` -> entrance,
`stash_door` -> storage, an unlabelled link to a converted door -> basic.
Quest-specific link names are reported, not guessed. The label follows KCD1's
own home behaviour tree (Libs/AI/final/sa_home.xml): a home without the
`nonprivateHome` script key defaults to trespass level `personal`; both games
share the `trespassLevel` enumeration. Linked doors get the native
`bNeverLockByPassingNPC=0`, which native Trosky sets on nearly every house
door and which KCD1 home doors had in effect through their script rule.
Ownership links, shops and pubs are not changed here.
"""
import json
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from campaign_entity_links import append_links, native_guid
from upgrade_map import read, xml

VERSION = 1
LEVEL = 'Data/Levels/kcd1_travel/level.pak'
FILES = ('objects_mission0.xml', 'waitinglinks.xml')
DEFINITION = 'crime_door[type($enum:crime_doorKind.%s)]'
# KCD1 trespassLevel / courtTrespassMode script values -> native area labels.
TRESPASS = {'none': None, 'public': None, 'semipublic': 'private;semipublic',
            'semipersonal': 'private;semipersonal', 'personal': 'private;personal',
            'prohibited': 'private;prohibited'}
MODES = {'none': None, 'nightOnly': 'private;semipublic', 'always': 'private;personal'}
DEFAULT_LABEL = 'private;personal'


def door_kind(name):
    """Native crime-door kind for a source area link name, or None."""
    parts = [p.strip() for p in (name or '').split(',')]
    if 'entrance' in parts: return 'entrance'
    if 'stash_door' in parts: return 'storage'
    if parts == ['']: return 'basic'
    return None


def script_values(misc):
    """Parse the SmartAreaShape Script Misc string ('key:value;key2:value2')."""
    values = {}
    for item in re.split(r'[;,]', misc or ''):
        if not item.strip(): continue
        key, _, value = item.partition(':')
        values[key.strip()] = value.strip() or 'true'
    return values


def privacy_label(misc):
    values = script_values(misc)
    if values.get('nonprivateHome', 'false').lower() == 'true': return None
    if 'trespass' in values:
        if values['trespass'] not in TRESPASS:
            raise ValueError('Unsupported source trespass level: ' + values['trespass'])
        return TRESPASS[values['trespass']]
    if 'trespassMode' in values:
        if values['trespassMode'] not in MODES:
            raise ValueError('Unsupported source trespass mode: ' + values['trespassMode'])
        return MODES[values['trespassMode']]
    return DEFAULT_LABEL


def source_misc(area):
    script = area.find('Properties/Script')
    return script.get('Misc', '') if script is not None else ''


def source_areas(source):
    """Index source SmartAreaShape variants by native GUID, plus source door IDs.

    Quest-state layers can hold several variants of one area; all are kept so
    the conversion can refuse variants that disagree instead of picking one.
    """
    areas, doors = {}, set()
    with zipfile.ZipFile(Path(source) / 'Data/Levels/rataje/level.pak') as z:
        for name in z.namelist():
            lower = name.lower()
            if not lower.endswith('.xml') or not (lower.startswith('layers/') or lower == 'objects_mission0.xml'):
                continue
            data = read(z, name)
            if b'SmartAreaShape' not in data and b'"AnimDoor"' not in data: continue
            for entity in ET.fromstring(data).iter('Entity'):
                cls = entity.get('EntityClass')
                if cls == 'SmartAreaShape' and entity.get('EntityGuid'):
                    areas.setdefault(native_guid(int(entity.get('EntityGuid'), 16)), []).append(entity)
                elif cls == 'AnimDoor' and entity.get('EntityId'):
                    doors.add(entity.get('EntityId'))
    return areas, doors


def source_links(variants):
    """Door-relevant links shared by every variant, or None when they disagree."""
    policies = set()
    for area in variants:
        links = tuple(sorted((l.get('Name') or '', l.get('TargetId') or '') for l in area.findall('EntityLinks/Link')))
        policies.add((links, source_misc(area)))
    if len(policies) != 1: return None
    (links, misc), = policies
    return list(links), misc


def convert(files, areas, source_doors=frozenset()):
    """Add crime-door links and privacy labels to registered homes; repeatable."""
    mission = ET.fromstring(files['objects_mission0.xml'])
    entities = {e.get('EntityId'): e for e in mission.iter('Entity') if e.get('EntityId')}
    doors = {e.get('Name'): e for e in mission.iter('Entity') if e.get('EntityClass') == 'AnimDoor'}
    targets = {}
    for hub in mission.iter('Entity'):
        if hub.get('EntityClass') != 'SchedulerHub': continue
        for link in hub.findall('EntityLinks/Link'):
            area = entities.get(link.get('TargetId'))
            if link.get('Name') == 'home_area' and area is not None and area.get('EntityClass') == 'TriggerArea':
                targets.setdefault(area.get('EntityId'), []).append(hub.get('Name'))
    waiting, homes, changed = [], [], False
    for area_id in sorted(targets, key=int):
        area = entities[area_id]
        record = dict(area=area.get('Name'), guid=area.get('EntityGuid'), hubs=sorted(targets[area_id]),
                      label=None, doors=[], pending=[], skipped=[])
        variants = areas.get(area.get('EntityGuid'))
        if not variants:
            record['status'] = 'no_source_area'; homes.append(record); continue
        resolved = source_links(variants)
        if resolved is None:
            record['status'] = 'ambiguous_source_variants'; homes.append(record); continue
        links, misc = resolved
        label = privacy_label(misc)
        record.update(status='converted', label=label, source_policy=misc)
        props = area.find('Properties')
        if props is None: props = ET.SubElement(area, 'Properties', bSaved_by_game='0')
        if label is not None:
            existing = props.get('Label', '')
            if existing not in ('', label):
                raise ValueError('Converted home already carries a different label: ' + area.get('Name'))
            if existing != label: props.set('Label', label); changed = True
        container = area.find('EntityLinks')
        if container is None: container = ET.SubElement(area, 'EntityLinks')
        for name, source_id in links:
            door = doors.get('gm_door_' + source_id)
            kind = door_kind(name)
            if kind is None:
                if door is not None: record['skipped'].append(dict(link=name, door=door.get('Name')))
                continue
            if door is None:
                if kind != 'basic' or source_id in source_doors:
                    record['pending'].append(dict(link=name, source_id=source_id, kind=kind))
                continue
            definition = DEFINITION % kind
            if not any(l.get('TargetId') == door.get('EntityId') and l.get('Name') == definition
                       for l in container.findall('Link')):
                ET.SubElement(container, 'Link', TargetId=door.get('EntityId'), TargetGuid=door.get('EntityGuid'), Name=definition)
                changed = True
            waiting.append((area.get('EntityGuid'), door.get('EntityGuid'), definition))
            lock = door.find('Properties/Lock')
            if lock is None: raise ValueError('Converted door has no lock policy: ' + door.get('Name'))
            if lock.get('bNeverLockByPassingNPC') != '0':
                lock.set('bNeverLockByPassingNPC', '0'); changed = True
            record['doors'].append(dict(kind=kind, name=door.get('Name'), source_id=source_id, link=name,
                                        lock_types=lock.get('esLockTypes'), initially_locked=lock.get('bLocked') == '1'))
        homes.append(record)
    result = dict(files)
    if changed: result['objects_mission0.xml'] = xml(mission)
    if waiting:
        result['waitinglinks.xml'] = append_links(files.get('waitinglinks.xml'), waiting)
    converted = [h for h in homes if h.get('status') == 'converted']
    labels = {}
    for home in converted:
        labels[home['label'] or 'none'] = labels.get(home['label'] or 'none', 0) + 1
    report = dict(version=VERSION, homes=homes, registered_homes=len(homes),
                  homes_with_doors=sum(1 for h in converted if h['doors']),
                  doors=sum(len(h['doors']) for h in converted),
                  door_kinds={k: sum(1 for h in converted for d in h['doors'] if d['kind'] == k) for k in ('entrance', 'basic', 'storage')},
                  labels=labels, pending=sum(len(h['pending']) for h in homes), skipped=sum(len(h['skipped']) for h in homes),
                  policy=dict(default_label=DEFAULT_LABEL, nonprivate_home='no label', never_lock_by_passing_npc=False,
                              keep_unlocked_clock='authored KCD1 fKeepOpenFrom/Until retained', owners='unchanged'),
                  runtime_verified=False)
    return result, report


def stage(mod, source, output):
    """Write a rewritten level archive under output when any home changes."""
    from build_horse_trader_test import rewrite
    mod, source, output = map(Path, (mod, source, output))
    if output.exists(): raise FileExistsError('Choose a new home-door staging folder')
    level = mod / LEVEL
    with zipfile.ZipFile(level) as z:
        files = {n: read(z, n) for n in FILES if n in z.namelist()}
    if 'objects_mission0.xml' not in files: raise ValueError('Package level has no mission objects')
    areas, doors = source_areas(source)
    updated, report = convert(files, areas, doors)
    changed = {n: b for n, b in updated.items() if files.get(n) != b}
    if changed: rewrite(level, output / LEVEL, changed)
    report.update(changed_entries=sorted(changed))
    return report


def upgrade(package, source):
    from build_recipe import apply_overlay
    package = Path(package)
    with tempfile.TemporaryDirectory(prefix='home-doors-', dir=package.parent) as tmp:
        out = Path(tmp) / 'stage'
        report = stage(package, source, out)
        if not (out / LEVEL).exists(): return {}, report
        return apply_overlay(package, out, consume=True), report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mod', 'source', 'output'): parser.add_argument('--' + name, type=Path, required=True)
    print(json.dumps(stage(**vars(parser.parse_args())), indent=2))
