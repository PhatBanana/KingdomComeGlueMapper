"""Upgrade source smithy work to the shipped native workstation controller.

Selection uses source behavior identity and category links, never actor names.
The native behavior owns phase decisions, hand contents, unstances and cleanup.
This adapter imports its complete workstation graph, not an animation timer.
Original tempering and quest cooperation are reported separately: the native
ordinary-work controller does not implement those source behaviors.
"""
import copy
import hashlib
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_entity_links import native_guid, guid_value
from character_job_items import register_item, bind_reservation, reservation_contract
from character_person import resolve_link_targets
from entity_visuals import quaternion_product
from cooking_pots import rotate
from upgrade_map import read

SOURCE_BEHAVIOR = ('final/sa_smithy.xml', 'BlackSmith_new')


def vector(e, key='Pos'):
    return tuple(map(float, e.get(key, '1,0,0,0' if key == 'Rotate' else '0,0,0').split(',')))


def pose(e, q, translation):
    result = copy.deepcopy(e)
    result.set('Pos', ','.join(format(a+b, '.10g') for a,b in zip(rotate(q, vector(e)), translation)))
    result.set('Rotate', ','.join(format(v, '.10g') for v in quaternion_product(q, vector(e, 'Rotate'))))
    return result


def workstation_transform(native_contacts, source_contacts, tolerance=.3):
    """Fit a rigid upright workshop to authored heating/hammer contact points.

    Reject incompatible layouts instead of stretching animations or moving the
    source building. No scale is applied to characters or animation root motion.
    """
    old, new = [vector(e) for e in native_contacts], [vector(e) for e in source_contacts]
    if len(old) != 2 or len(new) != 2: raise ValueError('Expected two workstation contacts')
    def angle(points):
        a,b=points
        if math.hypot(b[0]-a[0], b[1]-a[1]) < .5: raise ValueError('Degenerate workstation contacts')
        return math.atan2(b[1]-a[1], b[0]-a[0])
    yaw = angle(new)-angle(old)
    q = (math.cos(yaw/2), 0, 0, math.sin(yaw/2))
    offsets = [tuple(b-a for a,b in zip(rotate(q,x),y)) for x,y in zip(old,new)]
    translation = tuple(sum(v[i] for v in offsets)/2 for i in range(3))
    errors = [math.dist(tuple(a+b for a,b in zip(rotate(q,x),translation)),y) for x,y in zip(old,new)]
    if max(errors)>tolerance: raise ValueError('Source workshop cannot fit native animations: '+str(errors))
    return q,translation,errors


def native_contract(target):
    with zipfile.ZipFile(Path(target)/'Data/Tables.pak') as z:
        table=ET.fromstring(read(z,'Libs/Tables/ai/smartEntity/SmartEntity__so_blacksmith.xml'))
    template=table.find('SmartEntitys/SmartEntityTemplate')
    with zipfile.ZipFile(Path(target)/'Data/Levels/trosecko/level.pak') as z:
        entities=list(ET.fromstring(read(z,'objects_mission0.xml')))
    byid={e.get('EntityId'):e for e in entities}
    job=next(e for e in entities if e.find('Properties') is not None and
             e.find('Properties').get('guidSmartObjectType')==template.get('DatabaseId'))
    links={l.get('Name'):byid[l.get('TargetId')] for l in job.findall('EntityLinks/Link')}
    required={'swordSlot','swordHeatingSlot','swordHeatingPlaceSlot','hammerSlot','forgeBag'}
    if not required <= links.keys(): raise ValueError('Incomplete native smithy contract')
    # Verify the actual loaded tree, including hand decisions and bellows binding.
    tree=next(x for x in template.findall('BehaviorTemplates/SmartBehaviorTemplate') if x.get('Name')=='use').find('TreeLocation')
    with zipfile.ZipFile(Path(target)/'Data/Scripts.pak') as z:
        trees=ET.fromstring(read(z,'AI/'+tree.get('FileName')))
    use=next(x for x in trees if x.get('name')==tree.get('TreeName'))
    runtime=use.find('Root')
    unstances={x.get('unstance') for x in runtime.iter('UnstanceAction')}
    if unstances!={'blacksmith_heating','blacksmith_forging'}: raise ValueError('Changed native blacksmith state contract')
    if {x.get('decisionLabel') for x in runtime.iter('HandContentElement')}!={'blacksmith_sword','blacksmith_hammer'}:
        raise ValueError('Changed native hand-item decisions')
    return job,links,reservation_contract(job,byid),tree.attrib


def bind(mission, scheduler, entry, job, archive, target, registered):
    """Replace an importer-owned arrival with a fully linked native job object."""
    native, native_links, reservations, tree = native_contract(target)
    source=list(ET.fromstring(read(archive,'objects_mission0.xml')))
    area=ET.Element('Entity',entry['area']);ls=ET.SubElement(area,'EntityLinks')
    for link in entry['target_links']:ET.SubElement(ls,'Link',link)
    source=resolve_link_targets(archive,area,source,{})
    byid={e.get('EntityId'):e for e in source}
    direct=[byid[l['TargetId']] for l in entry['target_links']]
    def category(es,name):
        found={e.get('EntityId'):e for e in es if e.find('Properties') is not None and e.find('Properties').get('sWH_AI_EntityCategory')==name}
        if len(found)!=1:raise ValueError('Missing or ambiguous work dependency: '+name)
        return next(iter(found.values()))
    def children(e):
        nonlocal source,byid
        source=resolve_link_targets(archive,e,source,{})
        byid={e.get('EntityId'):e for e in source}
        return [byid[l.get('TargetId')] for l in e.findall('EntityLinks/Link')]
    forge=category(direct,'Furnace');anvil=category(direct,'Anvil')
    forge_children=children(forge);anvil_children=children(anvil)
    heating=category(forge_children,'Product');hammer=category(anvil_children,'Hammer')
    sword=category(direct,'Product');bellows=category(forge_children,'ForgeBag')
    q,translation,errors=workstation_transform([native_links['swordHeatingSlot'],native_links['hammerSlot']], [heating,hammer])
    transformed=pose(native,q,translation)
    for k in ('Pos','Rotate'):job.set(k,transformed.get(k))
    properties_index=list(job).index(job.find('Properties'))
    job.remove(job.find('Properties'));job.insert(properties_index,copy.deepcopy(native.find('Properties')))
    waiting=[];item_reports=[];targets={}
    for name,slot in [('swordSlot',sword),('hammerSlot',hammer),('swordHeatingSlot',heating)]:
        children(slot)
        props=slot.find('Properties');contract=dict(item_id=props.get('guidItemClassId').lower(),properties=native_links[name].find('Properties'))
        imported,report=register_item(mission,slot,byid,contract,registered)
        imported.find('Properties').set('bOnlyNPC','1')
        targets[name]=imported;item_reports.append(dict(role=name,**report))
    def create(role,prototype):
        guid=native_guid(int.from_bytes(hashlib.sha256(('workstation/'+entry['area']['EntityGuid']+'/'+role).encode()).digest()[:8],'little'))
        old=next((e for e in mission if e.get('EntityGuid')==guid),None)
        if old is not None: return old
        e=pose(prototype,q,translation)
        for k in ('Prefab','EditorLayer','Layer','ParentId','Scale'):e.attrib.pop(k,None)
        for child in list(e):
            if child.tag!='Properties':e.remove(child)
        e.set('EntityGuid',guid);e.set('EntityId',str(max(int(x.get('EntityId','0')) for x in mission)+1))
        e.set('Name','gm_job_'+role+'_'+entry['area']['EntityGuid'].lower());mission.append(e)
        return e
    targets['swordHeatingPlaceSlot']=create('swordHeatingPlaceSlot',native_links['swordHeatingPlaceSlot'])
    # Use the native animated skeleton: merely linking the old decorative CDF
    # does not supply the slave animation database that the unstance requires.
    targets['forgeBag']=create('forgeBag',native_links['forgeBag'])
    for e in list(mission):
        if e is not targets['forgeBag'] and (e.get('Name') in {'glue_entity_'+bellows.get('EntityId'),'glue_prop_'+bellows.get('EntityId'),'gm_environment_'+bellows.get('EntityId')}
            or e.get('EntityGuid')==native_guid(int(bellows.get('EntityGuid'),16))):
            mission.remove(e)
    def connect(a,b,name):
        links=a.find('EntityLinks')
        if links is None:links=ET.SubElement(a,'EntityLinks')
        existing=[l for l in links if l.get('Name')==name]
        if existing and any(l.get('TargetId')!=b.get('EntityId') for l in existing):raise ValueError('Conflicting workstation link '+name)
        if not existing:ET.SubElement(links,'Link',TargetId=b.get('EntityId'),TargetGuid=b.get('EntityGuid'),Name=name)
        waiting.append((a.get('EntityGuid'),b.get('EntityGuid'),name))
    for name,e in targets.items():connect(job,e,name)
    for contract in reservations:waiting.extend(bind_reservation(mission,job,targets[contract['direct_links'][0]],contract))
    rows=scheduler.find('Schedulers')
    hubs={r.get('EntityGuid') for r in rows}
    for e in [job,*targets.values()]:
        identity=str(guid_value(e.get('EntityGuid')))
        if identity not in hubs:
            ET.SubElement(rows,'C_SmartHub',EntityGuid=identity,IgnoreDeadEnds='false',StupidHub='false');hubs.add(identity)
    return waiting,dict(job='blacksmith',native_tree=tree,source_behavior=entry['behavior'],tools=item_reports,
        contact_errors_metres=errors,source_area=entry['area'],native_phases=['heating','forging'],
        pending=['source tempering cycle','source quest cooperation and phase locks'],runtime_verified=False)
