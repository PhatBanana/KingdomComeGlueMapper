"""Bind native inn rental to the source innkeeper's authored guest room."""
from contextlib import ExitStack
import copy
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile

from campaign_doors import NativeDoorCatalog, AnimatedDoorAssetAdapter
from campaign_entity_links import append_links, guid_value
from campaign_trigger_areas import TriggerArea, read_areas, write_areas
from chairs import inventory
from cooking_pots import rotate, vector
from entity_visuals import world_transform, quaternion_product as qmul
from room_rental_dialogue import attach, PROJECT
from seating_animations import install as install_animations
from static_assets import asset_pack
from bed_alignment import alignment as bed_alignment
from upgrade_map import read, xml


def register_bed_scheduler(blob, native_blob, donor_guid, bed_guid):
    """Register a native bed hub without copying unrelated town schedules."""
    root = ET.fromstring(blob)
    rows = root.find('Schedulers')
    if rows is None: raise ValueError('Missing scheduler container')
    donor_id, bed_id = str(guid_value(donor_guid)), str(guid_value(bed_guid))
    donors = [r for r in ET.fromstring(native_blob).findall('Schedulers/C_SmartHub')
              if r.get('EntityGuid') == donor_id]
    if len(donors) != 1: raise ValueError('Missing or ambiguous native bed scheduler')
    if donors[0].findall('.//S_ActivityLink'):
        raise ValueError('Native bed has external scheduler dependencies requiring conversion')
    if any(r.get('EntityGuid') == bed_id for r in rows):
        raise ValueError('Bed scheduler already registered')
    row = copy.deepcopy(donors[0])
    row.set('EntityGuid', bed_id)
    row.attrib.pop('Position', None)
    rows.append(row)
    return xml(root)


def source_room(entities, keeper):
    actor = next(e for e in entities.values() if e.get('Name') == keeper)
    homes = {l.get('TargetId') for l in actor.findall('EntityLinks/Link') if 'Home' in l.get('Name', '').split(',')}
    rooms = [e for e in entities.values() if any(l.get('Name') == 'sleepoverParentHome' and l.get('TargetId') in homes for l in e.findall('EntityLinks/Link'))]
    if len(rooms) != 1: raise ValueError('Expected one authored rental room for '+keeper)
    room = rooms[0]
    links = {l.get('Name'): l.get('TargetId') for l in room.findall('EntityLinks/Link')}
    return room, {role: entities[links[label]] for role, label in (
        ('bed','sleepoverBed'), ('chest','sleepoverStash'), ('door','sleepoverDoor'))}


def door_assets(source, target, door):
    with ExitStack() as stack:
        index, emitted, material, mesh = asset_pack(stack, source.parent, 'gluebuild/rental_door/')
        pack = SimpleNamespace(index=index, emitted=emitted, material=material, mesh=mesh)
        catalog = NativeDoorCatalog(target, stack)
        adapter = AnimatedDoorAssetAdapter(SimpleNamespace(adapter=pack), catalog, 'rental')
        model = door.find('Properties').get('object_Model').lower()
        plan = adapter.plan(model)
        materials = {identity: material(identity) for kind, identity in plan.dependencies}
        result_model, assets, report = adapter.convert(model, plan, {'assets': materials})
        contract = catalog.resolve(plan.source['rig'], door.find('Properties').get('soclasses_SmartObjectHelpers'))
        return result_model, {n: b.read_bytes() if isinstance(b, Path) else b for n,b in assets.items()}, contract, report


def register(files, source_entities, room, furniture, native, model, contract, guid, bed_frame):
    files = dict(files)
    root = ET.fromstring(files['objects_mission0.xml'])
    if any(e.get('Name', '').startswith('gm_rental_') for e in root.iter('Entity')): raise ValueError('Rental room already installed')
    natives = {e.get('EntityId'):e for e in ET.fromstring(read(native,'objects_mission0.xml')).iter('Entity')}
    next_id = max(int(e.get('EntityId','0')) for e in root.iter('Entity'))+1
    network = []
    def add(name, template, position=None, rotation=None):
        nonlocal next_id
        e = copy.deepcopy(template)
        for a in ('Prefab','EditorLayer','Layer','ParentId','ParentGuid'): e.attrib.pop(a,None)
        for c in list(e):
            if c.tag == 'EntityLinks': e.remove(c)
        e.set('Name','gm_rental_'+name); e.set('EntityGuid',guid('rental/'+room.get('EntityId')+'/'+name))
        e.set('EntityId',str(next_id)); next_id+=1
        if position is not None: e.set('Pos',vector(position))
        if rotation is not None: e.set('Rotate',vector(rotation))
        root.append(e)
        return e
    def link(a,b,name):
        links=a.find('EntityLinks')
        if links is None: links=ET.SubElement(a,'EntityLinks')
        ET.SubElement(links,'Link',Name=name,TargetId=b.get('EntityId'),TargetGuid=b.get('EntityGuid'))
        if name: network.append((a.get('EntityGuid'),b.get('EntityGuid'),name))
    # The native bed is a stance object plus BedTrigger; source geometry stays.
    dp,dq,_ = world_transform(natives['8449'],natives)
    sp,sq,_ = world_transform(furniture['bed'],source_entities)
    offset,correction=bed_frame
    translated=rotate(sq,offset)
    sp=tuple(sp[i]+translated[i] for i in range(3))
    sq=qmul(sq,correction)
    delta=qmul(sq,(dq[0],-dq[1],-dq[2],-dq[3]))
    bed=add('bed',natives['8449'],sp,sq)
    tp,tq,_=world_transform(natives['8450'],natives)
    offset=rotate(delta,tuple(tp[i]-dp[i] for i in range(3)))
    trigger=add('bed_trigger',natives['8450'],tuple(sp[i]+offset[i] for i in range(3)),qmul(delta,tq))
    bed.find('Properties').set('bOwnedByHome','0')
    link(bed,trigger,'mTrigger');link(trigger,bed,'')
    for original in natives['8449'].findall('EntityLinks/Link'):
        if original.get('TargetId')=='8449': link(bed,bed,original.get('Name'))
    files['tables/ai/scheduler.xml'] = register_bed_scheduler(
        files['tables/ai/scheduler.xml'], read(native, 'tables/ai/scheduler.xml'),
        natives['8449'].get('EntityGuid'), bed.get('EntityGuid'))
    # Source animated skin, native rig/animation/physical door implementation.
    sp,sq,ss=world_transform(furniture['door'],source_entities)
    door=add('door',natives['8504'],sp,sq);door.set('Scale',vector(ss))
    props=door.find('Properties');props.set('object_Model',model)
    props.set('esDoorAnimSet',contract['animation_set']);props.set('soclass_SmartObjectHelpers',contract['helper'])
    props.set('guidSmartObjectType',contract['smart_object']);props.set('bSaved_by_game','1')
    lock=props.find('Lock');lock.set('bLocked','1');lock.set('bNeverLockByPassingNPC','1')
    props.find('Physics').set('bPhysicalize','1')
    for parent in root.iter():
        for child in list(parent):
            if child.get('Name')=='glue_item_'+furniture['door'].get('EntityId'):parent.remove(child)
    chest=next(e for e in root.iter('Entity') if e.get('Name')=='gm_player_chest_'+furniture['chest'].get('EntityId'))
    chest.find('Properties/Lock').set('bLocked','1')
    waiting=ET.fromstring(files['waitinglinks.xml'])
    for row in list(waiting.find('WaitingLinks')):
        if row.get('TargetId')==chest.get('EntityGuid'):
            for definition in list(row):
                if definition.tag=='LinkDefinition' and definition.text=='owner':row.remove(definition)
            if not row.findall('LinkDefinition'):waiting.find('WaitingLinks').remove(row)
    files['waitinglinks.xml']=xml(waiting)
    rp,rq,rs=world_transform(room,source_entities)
    service=add('service',natives['1364'],rp,rq)
    area=add('room_area',natives['1363'],rp,rq)
    # TriggerArea's native compiled polygon uses WORLD-space vertices.
    authored=room.find('Area');points=[]
    for point in authored.findall('Points/Point'):
        p=tuple(map(float,point.get('Pos').split(',')))
        v=rotate(rq,tuple(p[i]*rs[i] for i in range(3)))
        points.append(tuple(rp[i]+v[i] for i in range(3)))
    area.append(copy.deepcopy(authored))
    old=read_areas(files['triggerareas.fubar'])
    files['triggerareas.fubar']=write_areas([*old['areas'],TriggerArea(guid_value(area.get('EntityGuid')),float(authored.get('Height'))*rs[2],tuple(points))],old['export_version'])
    for target,label in [(door,'door'),(bed,'bed'),(area,'antitrespassArea'),(area,'leaveArea')]:link(service,target,label)
    project=next(e for e in root.iter('Entity') if e.get('Name')=='GlueTravel_kcd1')
    for target,label in [(door,'rental_door'),(bed,'rental_bed'),(service,'rental_service'),(chest,'rental_chest')]:link(project,target,"asset['"+label+"']")
    files['objects_mission0.xml']=xml(root)
    files['waitinglinks.xml']=append_links(files['waitinglinks.xml'],network)
    files,animations=install_animations(files,native,prefixes=('gm_chair_','gm_bench_','gm_rental_'))
    return files, {'source_room':room.get('Name'),'source_ids':{k:v.get('EntityId') for k,v in furniture.items()},
                   'door_model':model,'bed_position':bed.get('Pos'),'chest_guid':chest.get('EntityGuid'),
                   'service_guid':service.get('EntityGuid'),'animations':animations,
                   'bed_scheduler_registered':True,
                   'bed_alignment':{'offset':bed_frame[0],'rotation':bed_frame[1]}}


def build(files, resources, source, target, guid, keeper='rato_innkeeper1'):
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as archive: entities,_,_=inventory(archive)
    room,furniture=source_room(entities,keeper)
    model,assets,contract,door_report=door_assets(source,target,furniture['door'])
    with zipfile.ZipFile(source/'Data/GameData.pak') as source_game, zipfile.ZipFile(target/'Data/IPL_GameData.pak') as native_game:
        bed_frame=bed_alignment(read(source_game,'Libs/SmartObjects.xml'),read(native_game,'Libs/SmartObjects.xml'))
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as native:
        files,report=register(files,entities,room,furniture,native,model,contract,guid,bed_frame)
    project=ET.fromstring(resources[PROJECT]).find('Skald/Project')
    soul=project.find("Assets/SoulAsset[@Name='rattay_innkeeper']").get('SharedSoulGuids')
    with zipfile.ZipFile(target/'Data/Scripts.pak') as scripts:resources,dialogue=attach(resources,scripts,soul)
    resources.update(assets);report.update(dialogue=dialogue,door_conversion=door_report,runtime_verified=False)
    return files,resources,report
