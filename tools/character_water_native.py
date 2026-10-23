"""Read the native refill graph, tool decision and well animation contract."""
import copy
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from campaign_entity_links import guid_value
from character_job_items import reservation_contract
from character_person import unique
from upgrade_map import read


def base_geometry(prefab, donor):
    """Keep the prefab's static well body alongside its separate animated rig."""
    from room_layout import geometry
    from cooking_pots import rotate, vector
    from entity_visuals import quaternion_product as qmul
    brush = unique(prefab.findall("Objects/Object[@Type='Brush']"), 'native well base')
    holder = unique(prefab.findall("Objects/Object[@EntityClass='SmartObjectHolder']"), 'prefab well holder')
    if holder.find('Properties').get('guidSmartObjectType') != donor.find('Properties').get('guidSmartObjectType'):
        raise ValueError('Well prefab and interaction contract differ')
    def transform(e):
        if e.get('Scale', '1,1,1') != '1,1,1':
            raise ValueError('Scaled well prefab needs a geometry adapter')
        return (tuple(map(float, e.get('Pos', '0,0,0').split(','))),
                tuple(map(float, e.get('Rotate', '1,0,0,0').split(','))))
    hp, hq = transform(holder); bp, bq = transform(brush); dp, dq = transform(donor)
    delta = qmul(dq, (hq[0], -hq[1], -hq[2], -hq[3]))
    offset = rotate(delta, tuple(b-h for b,h in zip(bp,hp)))
    node = geometry(dict(name='well_base', model=brush.get('Prefab', '')))
    node.set('EntityId', 'well_base')
    node.set('Pos', vector(tuple(d+o for d,o in zip(dp,offset))))
    node.set('Rotate', vector(qmul(delta,bq)))
    if brush.get('Material'): node.set('Material', brush.get('Material'))
    node.find('Properties').set('bInteractiveCollisionClass', '1')
    return node


def load(target):
    target = Path(target)
    with zipfile.ZipFile(target/'Data/Tables.pak') as z:
        templates = {name: E.fromstring(read(z, 'Libs/Tables/ai/smartEntity/SmartEntity__'+name+'.xml'))
                     .find('.//SmartEntityTemplate') for name in ('so_waterTube', 'so_waterWell')}
    tub, well = templates['so_waterTube'], templates['so_waterWell']
    behavior = tub.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='refillWatertube']")
    wb = well.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='refillWatertube']")
    if (behavior is None or behavior.get('InitialState') != 'Enabled' or behavior.get('Resource') != 'use'
            or tub.find("Resources/Resource[@Name='use'][@MaxInstances='1']") is None
            or wb is None or wb.get('MaxInstances') != '1' or wb.get('InitialState') != 'Enabled'):
        raise ValueError('Native water reservation contract changed')
    loc = behavior.find('TreeLocation')
    with zipfile.ZipFile(target/'Data/Scripts.pak') as z:
        tree = E.fromstring(read(z, 'AI/'+loc.get('FileName').replace('\\', '/')))
    root = tree.find("BehaviorTree[@name='"+loc.get('TreeName')+"']/Root")
    hand = root.find(".//HandContentElement[@decisionLabel='housekeeper_refillWatertube_bucket']")
    if (hand is None or hand.get('hand') != 'Right' or hand.get('useDecision') != 'true'
            or root.find(".//AnimationAction[@fragment=\"'Well'\"][@alignObject='$__resource.id'][@slaveObject='$animObject']") is None
            or root.find(".//AnimationAction[@fragment=\"'BucketPour'\"][@alignObject='$__object.id']") is None
            or not all(root.find('.//'+tag) is not None for tag in ('EventData_place', 'EventData_pickup', 'EventData_phaseitem'))):
        raise ValueError('Native water pickup/fill/pour sequence changed')
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as z:
        mission = E.fromstring(read(z, 'objects_mission0.xml'))
        rows = E.fromstring(read(z, 'tables/ai/scheduler.xml')).find('Schedulers')
    entities = {e.get('EntityId'): e for e in mission.iter('Entity')}
    by_guid = {str(guid_value(e.get('EntityGuid'))): e for e in entities.values() if e.get('EntityGuid')}
    by_row = {r.get('EntityGuid'): r for r in rows}
    def is_type(e, template):
        return e is not None and e.find('Properties') is not None and e.find('Properties').get('guidSmartObjectType') == template.get('DatabaseId')
    wells = [e for e in entities.values() if is_type(e, well) and
             all(l.get('TargetId') in entities for l in e.findall('EntityLinks/Link'))]
    donor = next((e for e in wells if {l.get('Name') for l in e.findall('EntityLinks/Link')} == {'animObject', 'slot'}), None)
    if donor is None: raise ValueError('Missing native well graph')
    from campaign_sources import retail_sources
    prefab = retail_sources(target, {'well': ('IPL_GameData.pak', 'Prefabs/Water/well.xml')})['well']['data']
    base = base_geometry(E.fromstring(prefab), donor)
    group = {l.get('Name'): entities[l.get('TargetId')] for l in donor.findall('EntityLinks/Link')}
    if (group['animObject'].get('EntityClass') != 'AnimObject' or group['slot'].get('EntityClass') != 'ItemSlot'
            or group['slot'].find('Properties').get('bSpawnOnStart') != '0'):
        raise ValueError('Native well dependencies changed')
    number = str(guid_value(donor.get('EntityGuid')))
    well_leaf = by_row[number]
    if well_leaf.tag != 'C_SmartHub' or len(well_leaf): raise ValueError('Native well has unexpected scheduler dependencies')
    water_edge = next((l for l in rows.findall('.//S_ActivityLink') if l.get('TargetGuid') == number
        and l.find('Parameters').get('BehaviorName') == 'refillWatertube'
        and l.find('Parameters').get('BehaviorOverride') == 'false'
        and l.find('Parameters').get('AllowedGenders') == '0'), None)
    for edge in rows.findall('.//S_ActivityLink'):
        obj = by_guid.get(edge.get('TargetGuid')); p = edge.find('Parameters')
        if not is_type(obj, tub) or p is None or any(p.get(k) != v for k, v in dict(
                BehaviorName='refillWatertube', BehaviorOverride='true', ProvidedRole='refillWatertube',
                AllowedGenders='2', Priority='0', Privileged='false', TimeOfDayStart='0', TimeOfDayEnd='1440').items()): continue
        if any(l.get('TargetId') not in entities for l in obj.findall('EntityLinks/Link')
               if l.get('Name', '').startswith('schedulerReservedItem')): continue
        try: contract = unique(reservation_contract(obj, entities), 'native bucket reservation')
        except (KeyError, ValueError): continue
        row = by_row[edge.get('TargetGuid')]
        links = row.findall('Links/S_ActivityLink')
        if len(links) != 1 or links[0].find('Parameters').get('RequiredRole') != 'refillWatertube': continue
        if contract['behavior'] != 'refillWatertube' or contract['decision'] != 'housekeeper_refillWatertube_bucket': continue
        if contract['item_id'] != group['slot'].find('Properties').get('guidItemClassId'): continue
        if row.find(".//EffectSoil[@Role='refillWatertube']") is None or row.find('.//EffectClean') is None: continue
        if water_edge is None: raise ValueError('Missing native well activity')
        source_links = [l.get('Name') for l in obj.findall('EntityLinks/Link')
                        if l.get('Name', '').startswith('_refillWatertube|')]
        if len(source_links) != 1: continue
        return copy.deepcopy(dict(tub_template=tub.get('DatabaseId'), activity=edge, tub_row=row,
            source_edge=links[0], source_definition=source_links[0], well_edge=water_edge, well=donor, group=group,
            well_leaf=well_leaf, bucket=contract, base=base))
    raise ValueError('Missing complete native tub refill graph')
