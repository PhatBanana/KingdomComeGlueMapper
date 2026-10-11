"""Native shop, work and sleeping contracts at Peshek's source mill."""
import copy
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from bed_alignment import alignment
from campaign_entity_links import append_links, guid_value
from character_person import register_person
from character_person_activity import source_lean_point, register_lean_activity, validate_scheduler_targets
from character_person_shop import register_shop_activity, register_shop_service
from character_person_world import register_person_world
from cooking_pots import rotate, vector
from entity_visuals import world_transform, quaternion_product as qmul
from lean_alignment import native_placement
from miller import NAMESPACE, ROLE
from region_travel_merchant import dialogue
from room_rental import register_bed_scheduler
from seating_animations import install as install_animations
from upgrade_map import read, xml

ENTRY = 'Quests/GlueTravel/entry/kcd1_travel.xml'
PROJECT = 'Quests/GlueTravel/GlueTravel_kcd1.xml'
DIALOG = 'rattay_miller'


def sleeping_activity(native, entities):
    """Use the shipped sleeper role, not the player's usedByPlayer behavior."""
    beds = {str(guid_value(e.get('EntityGuid'))) for e in entities.values()
            if e.get('EntityClass') == 'StanceSmartObject' and e.find('Properties') is not None
            and e.find('Properties').get('soclass_SmartObjectHelpers') == 'Bed_1Place_High'}
    for link in ET.fromstring(read(native, 'tables/ai/scheduler.xml')).iter('S_ActivityLink'):
        p = link.find('Parameters')
        if (link.get('TargetGuid') in beds and link.get('PositioningDelegate') == '0'
                and p.get('ProvidedRole') == 'sleeper' and p.get('BehaviorName') == 'use'
                and not any(k in p.attrib for k in ('RequiredRole', 'LinkTag', 'RequiredContext'))):
            return copy.deepcopy(link)
    raise ValueError('No native unrestricted bed sleeper activity')


def register(files, resources, person, shop, source, target, identity):
    files, resources = dict(files), dict(resources)
    mission, wh = ET.fromstring(files['objects_mission0.xml']), ET.fromstring(files['whdata_0'])
    if any(e.get('Name') == person['name'] for e in mission.iter('Entity')):
        raise ValueError('Miller already installed; use recorded baseline')
    next_id = max(int(e.get('EntityId', '0')) for e in mission.iter('Entity')) + 1
    network = []
    def add(name, cls, position, guid=None, rotation=None):
        nonlocal next_id
        e = ET.SubElement(mission, 'Entity', Name=name, EntityClass=cls, EntityId=str(next_id),
                          EntityGuid=guid or identity(name), Pos=position, CastShadowMinSpec='1')
        if rotation: e.set('Rotate', rotation)
        next_id += 1
        return e
    def link(a, b, label):
        links = a.find('EntityLinks')
        if links is None: links = ET.SubElement(a, 'EntityLinks')
        ET.SubElement(links, 'Link', Name=label, TargetId=b.get('EntityId'), TargetGuid=b.get('EntityGuid'))
        if label and not label.startswith(('_', '#')):
            network.append((a.get('EntityGuid'), b.get('EntityGuid'), label))
    def clone(name, original, position, rotation):
        e = add(NAMESPACE+'_'+name, original.get('EntityClass'), vector(position), rotation=vector(rotation))
        e.append(copy.deepcopy(original.find('Properties')))
        return e

    npc = register_person(add, wh, person)
    point, helper = source_lean_point(source, person, person['area'])
    point = native_placement(point, source, target, helper)
    work = add(NAMESPACE+'_work', 'SchedulerHub', point.get('Pos'))
    files['tables/ai/scheduler.xml'], lean = register_lean_activity(
        files['tables/ai/scheduler.xml'], add, npc, work, point, helper, target, NAMESPACE+'_lean')
    shop_entity = add(NAMESPACE+'_shop', 'Shop', person['shop_entity'].get('Pos'))
    ET.SubElement(shop_entity, 'Properties', sShopName=shop['shop_name'], iShopId=str(shop['shop_id']), bOwnerIsSpawned='1')
    files['tables/ai/scheduler.xml'] = register_shop_activity(
        files['tables/ai/scheduler.xml'], target, npc, work, shop_entity)
    for a, b, label in [(npc,work,'_|innkeeper'), (work,lean,'_use'), (npc,shop_entity,'owner'),
                        (npc,shop_entity,'shopKeeper'), (work,shop_entity,'#OpenShop[innkeeper]'),
                        (work,shop_entity,'#AddContext[innkeeper,shop_sellerReadyToSell]')]: link(a,b,label)
    holder = next(e for e in mission.iter('Entity') if e.get('EntityClass') == 'LevelHolder')
    link(holder, shop_entity, "asset['miller_shop']")
    resources[ENTRY] = register_shop_service(resources[ENTRY], person['soul']['soul_id'], 'miller_shop')

    with zipfile.ZipFile(Path(source)/'Data/GameData.pak') as original, zipfile.ZipFile(Path(target)/'Data/IPL_GameData.pak') as native_game:
        offset, correction = alignment(read(original,'Libs/SmartObjects.xml'), read(native_game,'Libs/SmartObjects.xml'))
    with zipfile.ZipFile(Path(source)/'Data/Levels/rataje/level.pak') as original:
        sources = {e.get('EntityId'): e for e in ET.fromstring(read(original,'objects_mission0.xml')).iter('Entity')}
    with zipfile.ZipFile(Path(target)/'Data/Levels/trosecko/level.pak') as native:
        entities = {e.get('EntityId'):e for e in ET.fromstring(read(native,'objects_mission0.xml')).iter('Entity')}
        donor, donor_trigger = entities['8449'], entities['8450']
        dp,dq,_ = world_transform(donor,entities)
        sp,sq,_ = world_transform(person['bed'],sources)
        translated=rotate(sq,offset);sp=tuple(sp[i]+translated[i] for i in range(3));sq=qmul(sq,correction)
        delta=qmul(sq,(dq[0],-dq[1],-dq[2],-dq[3]))
        bed=clone('bed',donor,sp,sq)
        bed.find('Properties').set('bOwnedByHome','0')
        tp,tq,_=world_transform(donor_trigger,entities)
        shift=rotate(delta,tuple(tp[i]-dp[i] for i in range(3)))
        trigger=clone('bed_trigger',donor_trigger,tuple(sp[i]+shift[i] for i in range(3)),qmul(delta,tq))
        link(bed,trigger,'mTrigger');link(trigger,bed,'');link(npc,bed,'owner')
        for l in donor.findall('EntityLinks/Link'):
            if l.get('TargetId')==donor.get('EntityId'):link(bed,bed,l.get('Name'))
        files['tables/ai/scheduler.xml']=register_bed_scheduler(files['tables/ai/scheduler.xml'],
            read(native,'tables/ai/scheduler.xml'),donor.get('EntityGuid'),bed.get('EntityGuid'))
        sleep=sleeping_activity(native,entities)
        sleep.set('TargetGuid',str(guid_value(bed.get('EntityGuid'))))
        scheduler=ET.fromstring(files['tables/ai/scheduler.xml'])
        row=next(r for r in scheduler.find('Schedulers') if r.get('EntityGuid')==str(guid_value(npc.get('EntityGuid'))))
        links=row.find('Links');work_link=copy.deepcopy(links[0]);links.clear()
        for window in person['windows']:
            activity=copy.deepcopy(work_link if window['activity']=='work' else sleep)
            params=activity.find('Parameters')
            params.set('TimeOfDayStart',str(window['start']));params.set('TimeOfDayEnd',str(window['end']))
            params.set('TimeVariation','0');links.append(activity)
        validate_scheduler_targets(scheduler)
        files['tables/ai/scheduler.xml']=xml(scheduler)
        files['objects_mission0.xml']=xml(mission);files['whdata_0']=xml(wh)
        files['waitinglinks.xml']=append_links(files['waitinglinks.xml'],network)
        files,homes=register_person_world(files,[person],source,target)
        files,animations=install_animations(files,native,prefixes=('gm_chair_','gm_bench_','gm_rental_',NAMESPACE+'_'))

    # Reuse the tested native Trade -> OpenShop handoff with distinct role,
    # resource, localization and diagnostic identities.
    blob=dialogue(person['name']).decode('utf-8')
    for old,new in [('GMTRAVEL_RATTAY_INNKEEPER',ROLE),('gmtravel_rattay_shop',NAMESPACE+'_shop'),
                    ('GLUE_RATTAY_SHOP','GLUE_MILLER_SHOP'),('rattay_innkeeper',DIALOG),
                    ('ui_gmtravel_rattay_trade','ui_gm_miller_trade')]: blob=blob.replace(old,new)
    path='Quests/GlueTravel/'+DIALOG+'.xml'
    resources[path]=blob.encode('utf-8')
    project=ET.fromstring(resources[PROJECT]);p=project.find('Skald/Project')
    ET.SubElement(p.find('Definitions'),'Definition',File=DIALOG+'.xml')
    ET.SubElement(p.find('Nodes'),DIALOG,Name=DIALOG)
    resources[PROJECT]=xml(project)
    return files,resources,dict(person=person['name'],position=npc.get('Pos'),work_point=point.get('Name'),
        source_bed=person['bed'].get('Name'),bed_position=bed.get('Pos'),schedule=person['windows'],
        work_activity=helper,sleep_activity='native use with sleeper role',homes=homes,animations=animations,
        limitations=['Work uses the authored lean point; mill machinery, carrying and sweeping sub-activities are not converted',
                     'Original miller quests, skill training and stolen-goods service rules are not converted'],runtime_verified=False)
