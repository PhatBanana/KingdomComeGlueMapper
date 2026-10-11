"""Convert authored KCD1 wash stations to the native KCD2 tub contract."""
import copy
import xml.etree.ElementTree as ET

from campaign_entity_links import append_links, guid_value
from chairs import inventory
from cooking_pots import rotate, vector
from entity_visuals import world_transform, quaternion_product as qmul
from seating_animations import install
from upgrade_map import read, xml

PREFIX = 'gm_wash_'
DONOR_TRIGGER = '3039'
PREFAB = 'Prefabs/Water/WaterTub.xml'


def convert(files, source, native, source_game, native_game, guid):
    entities, triggers, deferred = inventory(source, 'SequenceTrigger')
    is_wash = lambda e: e.find("Properties/Click[@UseMessage='@ui_use_wash']") is not None
    triggers = [e for e in triggers if is_wash(e)]
    deferred = [r for r in deferred if is_wash(entities[r['source_id']])]
    originals = {e.get('EntityId'): e for e in ET.fromstring(read(native, 'objects_mission0.xml')).iter('Entity')}
    trigger = originals[DONOR_TRIGGER]
    owner = originals[trigger.find('EntityLinks/Link').get('TargetId')]
    if trigger.get('EntityClass') != 'WaterTubeActionTrigger' or owner.find('Properties').get('soclass_SmartObjectHelpers') != 'watertube':
        raise ValueError('Native wash donor changed')
    native_rows = ET.fromstring(read(native, 'tables/ai/scheduler.xml')).find('Schedulers')
    effect = next(r for r in native_rows if r.get('EntityGuid') == str(guid_value(owner.get('EntityGuid'))))
    if effect.find('Links') is not None or effect.find('.//EffectClean') is None:
        raise ValueError('Native washing scheduler requires a dependency adapter')
    prefab = ET.fromstring(read(native_game, PREFAB))
    brush, = prefab.findall("Objects/Object[@Type='Brush']")
    source_helpers = ET.fromstring(read(source_game, 'Libs/SmartObjects.xml'))
    native_helpers = ET.fromstring(read(native_game, 'Libs/SmartObjects.xml'))
    old_helper, = [h for h in source_helpers.iter('Helper') if h.get('className') == 'water_tube_1' and h.get('name') == 'washPoint']
    new_helper, = [h for h in native_helpers.iter('Helper') if h.get('className') == 'watertube' and h.get('name') == 'Place0']
    v = lambda e,k: tuple(map(float,e.get(k).split(',')))
    oq,nq = v(old_helper,'rot'),v(new_helper,'rot')
    correction = qmul(oq,(nq[0],-nq[1],-nq[2],-nq[3]))
    offset = tuple(a-b for a,b in zip(v(old_helper,'pos'),rotate(correction,v(new_helper,'pos'))))
    mission = ET.fromstring(files['objects_mission0.xml'])
    if any(e.get('Name','').startswith(PREFIX) for e in mission.iter('Entity')):
        raise ValueError('Washing troughs already converted')
    visuals = {e.get('Name'): e for e in mission.iter('Entity')}
    scheduler = ET.fromstring(files['tables/ai/scheduler.xml']); rows = scheduler.find('Schedulers')
    next_id = max(int(e.get('EntityId','0')) for e in mission.iter('Entity'))+1
    network, records, seen = [], [], set()
    dp,dq,_ = world_transform(owner,originals)
    for source_trigger in triggers:
        source_owner = entities[source_trigger.find('EntityLinks/Link').get('TargetId')]
        key = source_owner.get('EntityId')
        if key in seen: raise ValueError('Multiple washing triggers for tub '+key)
        seen.add(key)
        if source_owner.find('Properties').get('soclasses_SmartObjectHelpers') != 'water_tube_1':
            raise ValueError('Unsupported source wash helper family')
        visual = visuals.get('glue_item_'+key)
        if visual is None: raise ValueError('Missing converted wash tub visual: '+key)
        sp,sq,scale = world_transform(source_owner,entities)
        if max(abs(s-1) for s in scale)>0.001: raise ValueError('Scaled wash tub requires animation alignment: '+key)
        shift = rotate(sq,offset)
        sp = tuple(a+b for a,b in zip(sp,shift));sq=qmul(sq,correction)
        delta=qmul(sq,(dq[0],-dq[1],-dq[2],-dq[3]))
        mapped={}
        for original in (owner,trigger):
            node=copy.deepcopy(original)
            for attr in ('Prefab','EditorLayer','Layer','ParentId','ParentGuid'):
                node.attrib.pop(attr,None)
            node.set('EntityId',str(next_id));next_id+=1
            node.set('EntityGuid',guid('washing/'+key+'/'+original.get('EntityClass')))
            node.set('Name',PREFIX+key+'_'+original.get('EntityClass'))
            p,q,_=world_transform(original,originals)
            diff=rotate(delta,tuple(a-b for a,b in zip(p,dp)))
            node.set('Pos',vector(tuple(a+b for a,b in zip(sp,diff))))
            node.set('Rotate',vector(qmul(delta,q)))
            mapped[original.get('EntityId')]=node
        for node in mapped.values():
            links=node.find('EntityLinks')
            for link in list(links):
                target=mapped.get(link.get('TargetId'))
                if target is None:
                    links.remove(link) # Trosky household refill reservations are not player-wash dependencies.
                    continue
                link.set('TargetId',target.get('EntityId'));link.set('TargetGuid',target.get('EntityGuid'))
                if link.get('Name'):network.append((node.get('EntityGuid'),target.get('EntityGuid'),link.get('Name')))
        new_owner=mapped[owner.get('EntityId')]
        row=copy.deepcopy(effect);row.set('EntityGuid',str(guid_value(new_owner.get('EntityGuid'))));row.attrib.pop('Position',None)
        rows.append(row)
        # The native tub model contains the native water surface/material. Replace
        # the old mesh in place so there are no overlapping water/collision surfaces.
        visual.set('Geometry',brush.get('Prefab'));visual.attrib.pop('Material',None)
        visual.set('Pos',vector(sp));visual.set('Rotate',vector(sq));visual.attrib.pop('Scale',None)
        visual.find('Properties').set('bInteractiveCollisionClass','1')
        mission.extend(mapped.values())
        records.append(dict(source_id=key,position=list(sp),guid=new_owner.get('EntityGuid')))
    result=dict(files)
    result.update({'objects_mission0.xml':xml(mission),'tables/ai/scheduler.xml':xml(scheduler),
                   'waitinglinks.xml':append_links(files.get('waitinglinks.xml'),network)})
    result,animations=install(result,native,prefixes=('gm_chair_','gm_bench_','gm_rental_'))
    return result,dict(converted=len(records),records=records,inactive_layer_troughs=deferred,
                       model=brush.get('Prefab'),animations=animations,runtime_tested=False)
