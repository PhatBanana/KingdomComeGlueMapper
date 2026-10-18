"""Build a source merchant service on an explicitly staged source actor.

The caller selects the actor, namespace and level. Stock, selling location,
clock, voice identity and physical storage come from source relationships.
No objective completion or item-grant scripts are injected.
"""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile
from upgrade_map import read, xml


def bind_storage(files, merchant, source, namespace, model):
    from merchant_stash import source_stash
    from ordinary_containers import properties
    from campaign_entity_links import append_links
    from region_travel import guid
    authored = source_stash(source,merchant['shop_entity'])
    original = authored.find('Properties')
    inventory = original.find('Database').get('guidInventoryDBId','')
    if inventory not in ('','0','00000000-0000-0000-0000-000000000000'):
        raise ValueError('Merchant stash has an independent inventory requiring conversion')
    record = dict(model=original.get('object_Model',''),kind='service',
        source_properties=E.tostring(original,encoding='unicode'),
        lock=dict(original.find('Lock').attrib),phase=dict(original.find('Phase').attrib) if original.find('Phase') is not None else {})
    props = properties(record,model,dict(preset='',restock_days=0,read_only=False,registered_keys=[]))
    mission = E.fromstring(files['objects_mission0.xml'])
    shop = next(e for e in mission if e.get('Name')==namespace+'_shop')
    npc = next(e for e in mission if e.get('Name')==merchant['name'])
    name = namespace+'_stash'
    if any(e.get('Name')==name for e in mission): raise ValueError('Merchant stash already registered')
    # Replace an existing static conversion of this precise source entity.
    for e in list(mission):
        if e.get('Name')=='glue_item_'+authored.get('EntityId'): mission.remove(e)
    stash = E.SubElement(mission,'Entity',Name=name,EntityClass='Stash',EntityGuid=guid(name),
        EntityId=str(max(int(e.get('EntityId','0')) for e in mission)+1),CastShadowMinSpec='1')
    for key in ('Pos','Rotate','Scale'):
        if authored.get(key) is not None:stash.set(key,authored.get(key))
    stash.append(props)
    edges = [(shop,stash,'shopStash'),(npc,stash,'owner')]
    for a,b,label in edges:
        links=a.find('EntityLinks')
        if links is None:links=E.SubElement(a,'EntityLinks')
        E.SubElement(links,'Link',Name=label,TargetId=b.get('EntityId'),TargetGuid=b.get('EntityGuid'))
    result=dict(files)
    result['objects_mission0.xml']=xml(mission)
    result['waitinglinks.xml']=append_links(files['waitinglinks.xml'],[(a.get('EntityGuid'),b.get('EntityGuid'),label) for a,b,label in edges])
    return result,dict(source_entity=authored.get('Name'),source_id=authored.get('EntityId'),model=model)


def build(source,target,baseline,stage,person,namespace,entry,level):
    from region_travel_services import resolve_merchant,shop_resources
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    from character_schedule import plan
    from character_schedule_world import resolve_arrivals,bind_arrivals
    from character_schedule_jobs import bind_jobs
    from character_station_work import resources as station_resources
    from campaign_merchant_work import register,add_trade_dialogue
    from dialogue_dubbing import import_source_voices,bind_soul_voice
    from build_actor_dialogues_test import actor_ui_name
    from merchant_stash import source_stash
    from world_item_definitions import native_items,native_item_registry
    from setup_package_upgrade import rewrite
    source,target,baseline,stage=map(Path,(source,target,baseline,stage))
    merchant=resolve_merchant(source,person);merchant['target']=target
    travel='Data/gluemappertravel.pak'; lp='Data/Levels/'+level+'/level.pak'
    with zipfile.ZipFile(stage/travel) as z:resources={n:read(z,n) for n in z.namelist() if n.startswith(('Libs/','Quests/'))}
    with zipfile.ZipFile(stage/lp) as z:files={n:read(z,n) for n in ('objects_mission0.xml','tables/ai/scheduler.xml','waitinglinks.xml')}
    patches=[];assets=set()
    for package in (baseline,stage):
        for p in (package/'Data').glob('*.pak'):
            with zipfile.ZipFile(p) as z:
                assets.update(n.replace('\\','/').lower() for n in z.namelist())
                patches.extend(read(z,n) for n in z.namelist() if n.lower().startswith('libs/tables/item/item__') and n.endswith('.xml'))
    stock_files,stock=shop_resources(merchant,target,namespace,patches)
    with RetailSourceReader(source) as reader,zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as z:
        tables=SourceTables(source,reader)
        schedule=plan(merchant,tables)
        if schedule['pending']:raise ValueError('Unresolved merchant schedule')
        schedules={person:resolve_arrivals(schedule,z,merchant,source,reader)}
        if any('station_work' not in e for e in schedules[person]):
            raise ValueError('Merchant service builder requires converted station work')
        files,arrivals=bind_arrivals(files,schedules,target)
        files,jobs=bind_jobs(files,schedules,z,target,native_item_registry(native_items(target,patches)))
        if any(j.get('pending') for j in jobs):raise ValueError('Merchant work is incomplete')
        for e in schedules[person]:resources.update(station_resources(e['station_work'])[1])
        character=tables.row('rpg/v_soul_character_data','soul_id',merchant['soul']['soul_id'])
        voices=tables.get('text/v_voice_abbreviation')['rows']
        voice=next(v for v in voices if v['voice_id']==character['voice_id'])
        with zipfile.ZipFile(target/'Data/Tables.pak') as native:
            resources,all_voices=import_source_voices(resources,read(native,'Libs/Tables/skald/voice.xml'),voices,{voice['abbreviation']})
        native_voice=next(v for v in E.fromstring(all_voices).iter('voice') if v.get('abbreviation')==voice['abbreviation'])
        # The explicit actor stage owns this role and its Storm assignment.
        role='gm_person_'+merchant['soul']['soul_id'].replace('-','')+'_role'
        roles=[r for n,b in resources.items() if n.startswith('Libs/Tables/rpg/role__') for r in E.fromstring(b).iter('role') if r.get('role_name')==role]
        if len(roles)!=1:raise ValueError('Missing staged merchant role')
        resources,_=bind_soul_voice(resources,target,namespace,person,native_voice.get('voice_technical_name'),role,actor_ui_name(resources,person))
    files,resources,service=register(files,resources,entry,merchant,stock,namespace,role='seller')
    authored=source_stash(source,merchant['shop_entity'])
    model=authored.find('Properties').get('object_Model').replace('\\','/').lower()
    converted='gluebuild/containers/'+hashlib.sha256(model.encode()).hexdigest()[:16]+'/'+Path(model).name
    if converted not in assets:raise ValueError('Missing converted merchant storage geometry: '+converted)
    files,storage=bind_storage(files,merchant,source,namespace,converted)
    resources=add_trade_dialogue(resources,entry,person,role,namespace)
    resources.update(stock_files)
    resources['Mods/kingdomcomegluemapper/Data/Levels/'+level+'/tables/ai/scheduler.xml']=files['tables/ai/scheduler.xml']
    report=dict(version=1,person=person,stock=stock,service=service,storage=storage,jobs=jobs,
        runtime_verified=False,quest_policy='Existing source inventory objective; no scripted grants or completion')
    resources['Libs/GlueMapper/'+namespace+'.json']=json.dumps(report,indent=2).encode()
    rewrite(stage,travel,resources);rewrite(stage,lp,files)
    return report


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source','target','baseline','stage','person','namespace','entry','level'):p.add_argument('--'+key,required=True)
    a=p.parse_args()
    print(json.dumps(build(**vars(a)),indent=2))
