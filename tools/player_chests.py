"""Map authored KCD1 personal chests to KCD2's persistent shared inventory."""
import copy
from contextlib import ExitStack
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from campaign_entity_links import append_links
from entity_visuals import initial_layer, world_transform
from static_assets import asset_pack
from upgrade_map import read

PREFIX = 'gm_player_chest_'
ASSETS = 'gluebuild/player_chests/'
SHARED_LINKS = {'sharedStash', 'sharedStash_master', 'sleepoverStash'}


def source_chests(archive):
    entities, active = {}, set()
    for name in archive.namelist():
        main = name.lower() == 'objects_mission0.xml'
        if not main and not (name.lower().startswith('layers/') and name.lower().endswith('.xml')):
            continue
        for e in ET.fromstring(read(archive, name)).iter('Entity'):
            key = e.get('EntityId')
            entities.setdefault(key, e)
            if (main and not e.get('Layer')) or initial_layer(e.get('Layer', '')):
                active.add(key)
    classified = {}
    for entity in entities.values():
        for link in entity.findall('EntityLinks/Link'):
            definition = link.get('Name', '')
            # These two quest-authored playerChest aliases are explicitly
            # connected to sharedStash by the source quests. Do not match names
            # like playerStashWithConfiscatedItems or ordinary loot containers.
            personal_alias = re.search(r"Quest(?:Item|Place)\[\(?['\"]playerChest['\"]\)?\]", definition)
            if definition in SHARED_LINKS or personal_alias:
                target = link.get('TargetId')
                if target not in entities or entities[target].get('EntityClass') != 'Stash':
                    raise ValueError('Personal chest link has no source Stash: '+str(target))
                classified.setdefault(target, set()).add(definition)
    masters = [key for key, tags in classified.items() if 'sharedStash_master' in tags]
    if len(masters) != 1 or masters[0] not in active:
        raise ValueError('Expected one active source master chest')
    records = [{'source_id': key, 'links': sorted(tags), 'active': key in active,
                'layer': entities[key].get('Layer', ''), 'master': key == masters[0]}
               for key, tags in sorted(classified.items(), key=lambda pair: int(pair[0]))]
    return entities, records


def native_master(archive):
    entities = list(ET.fromstring(read(archive, 'objects_mission0.xml')).iter('Entity'))
    by_id = {e.get('EntityId'): e for e in entities}
    roots = [e for e in entities if e.get('Name') == 'Barbora']
    targets = {l.get('TargetId') for e in roots for l in e.findall('EntityLinks/Link')
               if l.get('Name') == "asset['player_stash']"}
    if len(targets) != 1:
        raise ValueError('Native campaign does not resolve one player master stash')
    master = by_id[targets.pop()]
    if master.get('EntityClass') != 'Stash': raise ValueError('Native master is not a stash')
    return copy.deepcopy(master)


def assets(source, entities, records):
    models = {entities[r['source_id']].find('Properties').get('object_Model').replace('\\', '/').lower()
              for r in records if r['active']}
    paths, resources = {}, {}
    with ExitStack() as stack:
        for index, model in enumerate(sorted(models)):
            prefix = ASSETS + str(index) + '/'
            files, emitted, material, mesh = asset_pack(stack, source.parent, prefix)
            destination = prefix + Path(model).name
            emitted[destination] = mesh(model)
            for lod in (1, 2, 3):
                entry = model[:-4]+f'_lod{lod}'+model[-4:]
                if entry in files: emitted[prefix+Path(entry).name] = mesh(entry)
            with zipfile.ZipFile(source/'Data/Objects.pak') as archive:
                for name in archive.namelist():
                    if (name.lower().startswith(model.rsplit('/', 1)[0]+'/')
                            and name.lower().endswith(('.anm', '.animevents'))):
                        emitted[prefix+Path(name).name.lower()] = read(archive, name)
            resources.update({n: b.read_bytes() if isinstance(b, Path) else b for n, b in emitted.items()})
            paths[model] = destination
    return paths, resources


def register(files, entities, records, master, models, guid):
    root = ET.fromstring(files['objects_mission0.xml'])
    if any(e.get('Name', '').startswith(PREFIX) for e in root.iter('Entity')):
        raise ValueError('Player chests already converted; use recorded baseline')
    master_guid = master.get('EntityGuid')
    if any(e.get('EntityGuid') == master_guid for e in root.iter('Entity')):
        raise ValueError('Destination already contains the native master stash identity')
    players = ET.fromstring(files['whdata_0']).findall('./SoulList/Souls/Soul')
    players = [s for s in players if s.findtext('Player') == '1']
    if len(players) != 1: raise ValueError('Expected one real destination player')
    player_guid = players[0].findtext('EntityGuid')
    counter = max((int(e.get('EntityId', '0')) for e in root.iter('Entity')), default=0)+1
    nodes = {}
    for record in records:
        if not record['active']: continue
        key = record['source_id']; source = entities[key]
        node = copy.deepcopy(master)
        for attr in ('Prefab', 'Material', 'Layer', 'EditorLayer', 'ParentId', 'ParentGuid'):
            node.attrib.pop(attr, None)
        old_links = node.find('EntityLinks')
        if old_links is not None: node.remove(old_links)
        node.set('Name', PREFIX+key)
        node.set('EntityId', str(counter)); counter += 1
        node.set('EntityGuid', master_guid if record['master'] else guid('player_chest/'+key))
        position, rotation, scale = world_transform(source, entities)
        for attr, values in [('Pos', position), ('Rotate', rotation), ('Scale', scale)]:
            node.set(attr, ','.join(format(v, '.9g') for v in values))
        props = node.find('Properties'); original = source.find('Properties')
        model = original.get('object_Model').replace('\\', '/').lower()
        props.set('object_Model', models[model])
        props.set('bOwnedByHome', '0')
        props.set('sPickPlaceAnimTag', '')  # Retain source CGA open/close animations.
        props.set('esChestContextLabel', 'empty')
        for tag in ('Database', 'Lock', 'Animation', 'Physics', 'Phase'):
            old = props.find(tag)
            if old is not None: props.remove(old)
        ET.SubElement(props, 'Database', nRestockPeriodDays='0', nDestockPeriodDays='0')
        ET.SubElement(props, 'Lock', bLocked='0', bCanLockPick='0', bCanUnlockWithDynamicKey='0')
        animation = original.find('Animation')
        if animation is not None: props.append(copy.deepcopy(animation))
        ET.SubElement(props, 'Physics', bRigidBody='0', bPhysicalize='1')
        ET.SubElement(props, 'Phase', esStashPhaseChangeEvent='Never')
        for attr in ('fUseAngle', 'fUseDistance', 'fUseZOffset'):
            if original.get(attr) is not None: props.set(attr, original.get(attr))
        nodes[key] = node
    master_node = next(nodes[r['source_id']] for r in records if r['master'])
    network = []
    for key, node in nodes.items():
        network.append((player_guid, node.get('EntityGuid'), 'owner'))
        if node is not master_node:
            links = ET.SubElement(node, 'EntityLinks')
            ET.SubElement(links, 'Link', Name='masterStash', TargetId=master_node.get('EntityId'), TargetGuid=master_guid)
            network.append((node.get('EntityGuid'), master_guid, 'masterStash'))
    # Publish the same asset alias used by the native campaign without copying
    # or enabling native story quests. Inventory identity stays engine-owned.
    for host in root.iter('Entity'):
        if host.get('EntityClass') == 'LevelHolder' or host.get('Name') == 'GlueTravel_kcd1':
            links = host.find('EntityLinks')
            if links is None: links = ET.SubElement(host, 'EntityLinks')
            ET.SubElement(links, 'Link', Name="asset['player_stash']", TargetId=master_node.get('EntityId'), TargetGuid=master_guid)
            network.append((host.get('EntityGuid'), master_guid, "asset['player_stash']"))
    names = {'glue_item_'+key for key in nodes}
    removed = 0
    for parent in root.iter():
        for child in list(parent):
            if child.get('Name') in names: parent.remove(child); removed += 1
    root.extend(nodes.values())
    result = dict(files)
    result['objects_mission0.xml'] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    result['waitinglinks.xml'] = append_links(files.get('waitinglinks.xml'), network)
    return result, {'converted': len(nodes), 'master_guid': master_guid,
                    'master_source_id': next(r['source_id'] for r in records if r['master']),
                    'replaced_static_chests': removed, 'records': records,
                    'positions': {key: node.get('Pos') for key, node in nodes.items()},
                    'scope': 'Current playthrough shared storage; no account-wide item copying',
                    'rental_access': 'Personal chest locations enabled for the test world; room rental gates are not converted'}


def build(files, source, target, guid):
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as archive:
        entities, records = source_chests(archive)
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as archive:
        master = native_master(archive)
    with zipfile.ZipFile(target/'Data/Levels/kutnohorsko/level.pak') as archive:
        other = native_master(archive)
    if master.get('EntityGuid') != other.get('EntityGuid'):
        raise ValueError('Native regions no longer share the master chest identity')
    models, resources = assets(source, entities, records)
    files, report = register(files, entities, records, master, models, guid)
    report['native_cross_region_identity_verified'] = True
    return files, resources, report
