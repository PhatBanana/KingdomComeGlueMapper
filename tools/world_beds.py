"""Add native sleep contracts to active, authored KCD1 beds without replacing furniture."""
from collections import Counter
from contextlib import ExitStack
import copy
import math
import xml.etree.ElementTree as ET
import zipfile

from bed_alignment import alignment
from campaign_entity_links import append_links, guid_value
from chairs import inventory
from cooking_pots import rotate, vector
from entity_visuals import world_transform, quaternion_product as qmul
from seating_animations import install, HELPERS, ANIMATIONS
from upgrade_map import read, xml

PREFIX = 'gm_world_bed_'
SCHEDULER = 'tables/ai/scheduler.xml'
LEVEL_FILES = ('objects_mission0.xml', 'waitinglinks.xml', HELPERS, ANIMATIONS, SCHEDULER)
FAMILIES = {
    'Bed': 'Bed_1Place_High',
    'CampBed': 'Bed_1Place_Low',
    'Bed_StrictLeft': 'Bed_1Place_Low_Right',
    'ShelterBed': 'Bed_1Place_Tent',
    'TentBed': 'Bed_1Place_Tent',
    'SleepingBench': 'Bed_1Place_Bench',
    'SleepingBench_Left': 'Bed_1Place_Bench',
    'SleepingBench_Right': 'Bed_1Place_Bench',
}


def helper(root, family, name):
    matches = [e for e in root.findall('Helper')
               if e.get('className') == family and e.get('name') == name]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous bed helper: ' + family + '/' + name)
    e = matches[0]
    p = tuple(map(float, e.get('pos').split(',')))
    q = tuple(map(float, e.get('rot').split(',')))
    if len(p) != 3 or len(q) != 4 or not all(map(math.isfinite, p + q)):
        raise ValueError('Invalid bed helper transform')
    length = math.sqrt(sum(v*v for v in q))
    if length < 1e-8:
        raise ValueError('Zero bed helper rotation')
    return p, tuple(v/length for v in q)


def frame(source_helpers, native_helpers, family):
    """Keep furniture axes separate from the native animation coordinate frame."""
    if family not in FAMILIES:
        raise ValueError('Unsupported source bed family: ' + str(family))
    target = FAMILIES[family]
    src, dst = ET.fromstring(source_helpers), ET.fromstring(native_helpers)
    if family == 'Bed':
        return alignment(source_helpers, native_helpers)
    if family in ('CampBed', 'Bed_StrictLeft'):
        # Source beds lie along local X; native high/low beds lie along Y.
        # The native right-only low bed approaches from source negative Y.
        offset, rotation = alignment(source_helpers, native_helpers)
        p, _ = helper(src, family, 'lieSideRight' if family == 'CampBed' else 'lieSideLeft')
        return tuple(p[i] + offset[i] for i in range(3)), rotation
    anchor = 'sitting' if family.startswith('SleepingBench') else 'Entry'
    sp, sq = helper(src, family, anchor)
    np, nq = helper(dst, target, 'sitting' if anchor == 'sitting' else 'Place0')
    correction = qmul(sq, (nq[0], -nq[1], -nq[2], -nq[3]))
    rotated = rotate(correction, np)
    return tuple(sp[i] - rotated[i] for i in range(3)), correction


def donors(native):
    """Use complete native contracts whose hubs have no external town dependencies."""
    entities = {e.get('EntityId'): e for e in ET.fromstring(read(native, 'objects_mission0.xml')).iter('Entity') if e.get('EntityId')}
    hubs = {r.get('EntityGuid'): r for r in ET.fromstring(read(native, SCHEDULER)).findall('Schedulers/C_SmartHub')}
    result = {}
    for entity in sorted(entities.values(), key=lambda e: int(e.get('EntityId'))):
        props = entity.find('Properties')
        family = props.get('soclass_SmartObjectHelpers', '') if props is not None else ''
        if entity.get('EntityClass') != 'StanceSmartObject' or family not in set(FAMILIES.values()):
            continue
        links = entity.findall('EntityLinks/Link')
        hub = hubs.get(str(guid_value(entity.get('EntityGuid'))))
        if hub is None or hub.findall('.//S_ActivityLink'):
            continue
        if any(l.get('Name') != 'mTrigger' and l.get('TargetId') != entity.get('EntityId') for l in links):
            continue
        triggers = [entities[l.get('TargetId')] for l in links if l.get('Name') == 'mTrigger']
        if len(triggers) != 1 or triggers[0].get('EntityClass') not in ('BedTrigger', 'ActionTrigger'):
            continue
        if not any(a.get('sAction') == 'lying' for a in triggers[0].findall('Properties/*')):
            continue
        if not hub.findall('.//EffectHeal'):
            continue
        if any(l.get('TargetId') != entity.get('EntityId') for l in triggers[0].findall('EntityLinks/Link')):
            continue
        result.setdefault(family, (entity, triggers[0], hub, entities))
    # The one-sided native helper family uses the ordinary low-bed hub/trigger.
    if 'Bed_1Place_Low_Right' not in result and 'Bed_1Place_Low' in result:
        result['Bed_1Place_Low_Right'] = result['Bed_1Place_Low']
    missing = set(FAMILIES.values()) - result.keys()
    if missing:
        raise ValueError('Missing independent native bed donors: ' + ', '.join(sorted(missing)))
    return result


def convert(files, source, native, source_helpers, native_helpers, guid):
    sources, beds, deferred = inventory(source, 'Bed')
    templates = donors(native)
    frames = {f: frame(source_helpers, native_helpers, f)
              for f in {e.find('Properties').get('soclasses_SmartObjectHelpers') for e in beds}}
    root = ET.fromstring(files['objects_mission0.xml'])
    entities = {e.get('EntityId'): e for e in root.iter('Entity') if e.get('EntityId')}
    if any(e.get('Name', '').startswith(PREFIX) for e in entities.values()):
        raise ValueError('World beds already converted; use a pre-conversion baseline')
    names = {e.get('Name'): e for e in root.iter('Entity')}
    existing = [e for e in entities.values() if e.get('EntityClass') == 'StanceSmartObject'
                and e.find('Properties').get('sWH_AI_EntityCategory') == 'Bed']
    scheduler = ET.fromstring(files[SCHEDULER])
    rows = scheduler.find('Schedulers')
    if rows is None:
        raise ValueError('Missing scheduler container')
    registered = {r.get('EntityGuid') for r in rows}
    next_id = max((int(v) for v in entities), default=0) + 1
    records, preserved, network = [], [], []
    for source_bed in sorted(beds, key=lambda e: int(e.get('EntityId'))):
        sid = source_bed.get('EntityId')
        props = source_bed.find('Properties')
        family = props.get('soclasses_SmartObjectHelpers')
        target = FAMILIES[family]
        sp, sq, ss = world_transform(source_bed, sources)
        if max(abs(s-1) for s in ss) > .001:
            raise ValueError('Scaled bed needs a validated animation alignment: ' + sid)
        offset, correction = frames[family]
        translated = rotate(sq, offset)
        position = tuple(sp[i] + translated[i] for i in range(3))
        rotation = qmul(sq, correction)
        # Preserve the already linked rental and miller contracts, including owners.
        matches = [e for e in existing if math.dist(world_transform(e, entities)[0], position) < .02]
        if matches:
            if len(matches) != 1:
                raise ValueError('Ambiguous existing bed: ' + sid)
            bed = matches[0]
            if bed.find('Properties').get('soclass_SmartObjectHelpers') != target:
                raise ValueError('Existing bed helper mismatch: ' + sid)
            existing_rotation = world_transform(bed, entities)[1]
            if abs(sum(a*b for a,b in zip(rotation, existing_rotation))) < .99999:
                raise ValueError('Existing bed orientation mismatch: ' + sid)
            if str(guid_value(bed.get('EntityGuid'))) not in registered:
                raise ValueError('Existing bed has no scheduler hub: ' + sid)
            links = bed.findall("EntityLinks/Link[@Name='mTrigger']")
            if len(links) != 1 or links[0].get('TargetId') not in entities:
                raise ValueError('Existing bed has no trigger: ' + sid)
            existing_trigger = entities[links[0].get('TargetId')]
            if existing_trigger.get('EntityClass') not in ('BedTrigger', 'ActionTrigger') or links[0].get('TargetGuid') != existing_trigger.get('EntityGuid'):
                raise ValueError('Existing bed trigger mismatch: ' + sid)
            preserved.append({'source_id': sid, 'name': bed.get('Name')})
            continue
        visual = names.get('glue_item_' + sid)
        if visual is None or not visual.get('Geometry'):
            raise ValueError('Missing converted bed furniture: ' + sid)
        donor, donor_trigger, donor_hub, native_entities = templates[target]
        dp, dq, _ = world_transform(donor, native_entities)
        tp, tq, ts = world_transform(donor_trigger, native_entities)
        delta = qmul(rotation, (dq[0], -dq[1], -dq[2], -dq[3]))
        shift = rotate(delta, tuple(tp[i] - dp[i] for i in range(3)))
        mapped = {}
        for role, original, p, q, scale in (
                ('bed', donor, position, rotation, (1, 1, 1)),
                ('trigger', donor_trigger, tuple(position[i]+shift[i] for i in range(3)), qmul(delta, tq), ts)):
            node = copy.deepcopy(original)
            for attr in ('Prefab', 'EditorLayer', 'Layer', 'ParentId', 'ParentGuid'):
                node.attrib.pop(attr, None)
            node.set('Name', f'{PREFIX}{sid}_{role}')
            node.set('EntityId', str(next_id)); next_id += 1
            node.set('EntityGuid', guid(f'world_bed/{sid}/{role}'))
            node.set('Pos', vector(p)); node.set('Rotate', vector(q)); node.set('Scale', vector(scale))
            mapped[original.get('EntityId')] = node
        bed, trigger = mapped[donor.get('EntityId')], mapped[donor_trigger.get('EntityId')]
        bp = bed.find('Properties')
        bp.set('bOwnedByHome', '0')
        bp.set('soclass_SmartObjectHelpers', target)
        for attr in ('esSleepQuality', 'esReadingQuality'):
            value = props.find('Bed').get(attr)
            if value is not None:
                bp.find('Bed').set(attr, value)
        for action in trigger.findall('Properties/*'):
            if action.tag in ('Click', 'Hold'):
                action.set('bCheckOwner', '0'); action.set('bAllowNoOwner', '1')
                if action.get('sAction') == 'lying':
                    action.set('esActionType', 'Stance')
                    action.set('UseMessage', '@ui_hud_sleep')
        for node in mapped.values():
            for link in node.findall('EntityLinks/Link'):
                dest = mapped[link.get('TargetId')]
                link.set('TargetId', dest.get('EntityId')); link.set('TargetGuid', dest.get('EntityGuid'))
                if link.get('Name'):
                    network.append((node.get('EntityGuid'), dest.get('EntityGuid'), link.get('Name')))
            root.append(node)
        hub = copy.deepcopy(donor_hub)
        bed_id = str(guid_value(bed.get('EntityGuid')))
        if bed_id in registered:
            raise ValueError('Duplicate bed scheduler: ' + sid)
        registered.add(bed_id)
        hub.set('EntityGuid', bed_id); hub.attrib.pop('Position', None); rows.append(hub)
        records.append({'source_id': sid, 'source_family': family, 'native_family': target,
                        'source_model': props.get('object_Model'), 'position': list(position),
                        'bed_guid': bed.get('EntityGuid'), 'trigger_guid': trigger.get('EntityGuid'),
                        'ownership': 'temporarily_unowned', 'sleep_quality': bp.find('Bed').get('esSleepQuality')})
    result = dict(files)
    result['objects_mission0.xml'] = xml(root)
    result[SCHEDULER] = xml(scheduler)
    result['waitinglinks.xml'] = append_links(files['waitinglinks.xml'], network)
    result, animations = install(result, native, prefixes=(PREFIX,))
    return result, {'converted': len(records), 'preserved_existing': preserved,
                    'active_source_beds': len(beds), 'inactive_layers': deferred,
                    'families': dict(Counter(r['source_family'] for r in records)),
                    'records': records, 'animations': animations, 'runtime_verified': False,
                    'limitations': ['Ownership is temporarily unrestricted for newly converted beds.',
                        'Sleeping benches use the native bench animation family; source left/right restrictions need gameplay validation.',
                        'Ground, shelter and tent alignment and save/load require representative gameplay tests.']}


def build(files, source, target, guid):
    with ExitStack() as stack:
        src = stack.enter_context(zipfile.ZipFile(source/'Data/Levels/rataje/level.pak'))
        native = stack.enter_context(zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak'))
        old = stack.enter_context(zipfile.ZipFile(source/'Data/GameData.pak'))
        new = stack.enter_context(zipfile.ZipFile(target/'Data/IPL_GameData.pak'))
        return convert(files, src, native, read(old, 'Libs/SmartObjects.xml'), read(new, 'Libs/SmartObjects.xml'), guid)
