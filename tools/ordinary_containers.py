"""Stage conservative ordinary storage; ownership and random loot remain explicit.

The initial supported contract is a chest with no authored inventory preset.
Do not use this converter to erase an inventory that needs translating.
"""
import copy
import xml.etree.ElementTree as ET

PREFIX = 'gm_container_'


def eligibility(record):
    if record.get('hidden'): return 'source container hidden in game'
    # A service-like name is not proof of ownership, but is enough to defer
    # ambiguous containers until their missing service links are understood.
    if any(token in record.get('name', '').lower() for token in ('shop', 'merchant')):
        return 'possible service storage requires review'
    if record['protected_roles']: return 'protected storage'
    if any(d not in ('', 'owner', 'automatedLinkedStash', 'clothesStash',
                     'ownershipIgnore', 'automatedLinkedStash,clothesStash')
           for d in record['link_definitions']): return 'special source links require review'
    if record['kind'] != 'chest': return 'container model contract not validated'
    if record['inventory_status'] != 'no_authored_inventory': return 'inventory conversion required'
    if record['phase'].get('bChangeAfterPlayerInteract', '0') != '0': return 'phase conversion required'
    key = record['lock'].get('guidItemClassId', '')
    if key not in ('', '0', '00000000-0000-0000-0000-000000000000'):
        return 'key conversion required'
    return None


def properties(record, model, contract=None):
    original = ET.fromstring(record['source_properties'])
    result = ET.Element('Properties', object_Model=model, bOwnedByHome='0',
        sPickPlaceAnimTag='', esChestContextLabel='none', sWH_AI_EntityCategory='Chest')
    for attr in ('fUseAngle', 'fUseDistance', 'fUseZOffset'):
        if attr in original.attrib: result.set(attr, original.get(attr))
    ET.SubElement(result, 'Database', sInventoryPreset='', sGeneratedInventory='',
        nRestockPeriodDays='0', nDestockPeriodDays='0', bReadOnly='0')
    lock = record['lock']
    difficulty = lock.get('fLockDifficulty', '0')
    if lock.get('bLockDifficultyOverride', '0') != '1':
        difficulty = '0'
        for name, value in (('chest_small_01', '.2'), ('chest_02', '.3'),
                            ('chest_05', '.4'), ('chest_04', '.6'),
                            ('chest_03', '.8'), ('chest_01', '1')):
            if name in record['model']: difficulty = value; break
    ET.SubElement(result, 'Lock', bLocked=lock.get('bLocked', '0'),
        bCanLockPick=lock.get('bCanLockPick', '1'), bCanUnlockWithDynamicKey='0',
        bLockDifficultyOverride='1', fLockDifficulty=difficulty,
        bLockFancinessOverride='1', esLockFanciness='Common', bSendMessage='0', guidItemClassId='')
    for tag in ('Animation', 'Sounds'):
        element = original.find(tag)
        if element is not None: result.append(copy.deepcopy(element))
    ET.SubElement(result, 'Physics', bPhysicalize='1', bRigidBody='0')
    ET.SubElement(result, 'Phase', esStashPhaseChangeEvent='Never', object_PhaseModel='')
    if contract is not None:
        result.set('sWH_AI_EntityCategory',original.get('sWH_AI_EntityCategory') or ('Chest' if record['kind']=='chest' else ''))
        result.set('esChestContextLabel','empty')
        database=result.find('Database')
        database.set('sGeneratedInventory','inventory_empty')
        database.set('sInventoryPreset',contract['preset'])
        database.set('nRestockPeriodDays',str(contract['restock_days']))
        database.set('bReadOnly','1' if contract['read_only'] else '0')
        key=lock.get('guidItemClassId','').lower()
        if key not in ('','0','00000000-0000-0000-0000-000000000000'):
            if key not in contract['registered_keys']: raise ValueError('Unregistered container key '+key)
            result.find('Lock').set('guidItemClassId',key)
        if record['phase'].get('bChangeAfterPlayerInteract','0')=='1':
            if 'phase_model' not in contract: raise ValueError('Missing source phase model contract')
            result.find('Phase').set('esStashPhaseChangeEvent','PlayerTakesItem')
            result.find('Phase').set('object_PhaseModel',contract['phase_model'])
    return result


def register(files, records, models, guid, contracts=None):
    root = ET.fromstring(files['objects_mission0.xml'])
    if len({r['source_id'] for r in records}) != len(records):
        raise ValueError('Duplicate source container selection')
    nodes = list(root.iter('Entity'))
    next_id = max((int(n.get('EntityId', '0')) for n in nodes), default=0) + 1
    identities = {n.get('EntityGuid') for n in nodes}
    converted = []
    for record in records:
        reason = eligibility(record) if contracts is None else None
        if reason: raise ValueError(record['source_id']+': '+reason)
        sid = record['source_id']
        identity = guid('ordinary_container/'+sid)
        if identity in identities: raise ValueError('Container already converted: '+sid)
        visuals = [n for n in nodes if n.get('Name') == 'glue_item_'+sid]
        if len(visuals) != 1 and not (contracts is not None and len(visuals)==0 and (record.get('hidden') or not record['model'])):
            raise ValueError('Expected one static container: '+sid)
        if next_id == 0x7777: next_id += 1
        node = ET.Element('Entity', EntityClass='Stash', EntityId=str(next_id),
            EntityGuid=identity, Name=PREFIX+sid, CastShadowMinSpec='1')
        next_id += 1; identities.add(identity)
        for attribute, values in (('Pos', record['position']), ('Rotate', record['rotation']), ('Scale', record['scale'])):
            node.set(attribute, ','.join(format(v, '.9g') for v in values))
        node.append(properties(record, models[record['model']], contracts[sid] if contracts is not None else None))
        if record.get('hidden'): node.set('HiddenInGame','1')
        if visuals:
            for parent in root.iter():
                if visuals[0] in list(parent): parent.remove(visuals[0]); break
        root.append(node)
        converted.append(dict(source_id=sid, entity_guid=identity, position=node.get('Pos'),
            ownership='temporarily_unowned', inventory=contracts[sid]['preset'] if contracts is not None else 'empty; no authored preset',
            omitted_source_links=record['link_definitions']))
    result = dict(files)
    result['objects_mission0.xml'] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    return result, dict(converted=len(converted), records=converted, runtime_tested=False,
        limitation='NPC/home generated contents and ownership are not converted. No source random inventory is replaced.')
