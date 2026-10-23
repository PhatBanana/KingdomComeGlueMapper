"""Source-selected dice jobs using native table ownership and a money fallback."""
import copy
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from campaign_bindings import parse_link_labels
from campaign_entity_links import append_links, guid_value
from character_person import resolve_link_targets, unique, world_entity
from character_work_pool import identity, source_job
from character_city_benches import signature
from character_dice_resources import build, linked, scheduler_rows, TABLE_TEMPLATE
from character_dice_policy import opponent, lean_program, validate_leaning
from lean_alignment import native_placement
from upgrade_map import read, xml

SOURCE=('quests/q_skalitz.xml','gambler_playDiceTillYouRunOutOfMoney')


def supports(entry):
    b=entry['behavior']
    return (b['tree_file'].replace('\\','/').lower(),b['tree_name'])==SOURCE


def resolve(entry,archive):
    area=E.Element('Entity',entry['area']);links=E.SubElement(area,'EntityLinks')
    selected={}
    for link in entry['target_links']:
        for label in parse_link_labels(link.get('Name','')):
            if label['tag']=='QuestPlace' and label['positional'] in (['diceTable'],['gamblerLeaningSpot']) and not label['named']:
                key=label['positional'][0]
                if key in selected:raise ValueError('Ambiguous source dice destination')
                selected[key]=link;E.SubElement(links,'Link',link)
    if set(selected)!={'diceTable','gamblerLeaningSpot'}:raise ValueError('Missing source dice destinations')
    entities=resolve_link_targets(archive,area,list(E.fromstring(read(archive,'objects_mission0.xml'))),{})
    by_id={e.get('EntityId'):e for e in entities}
    table=by_id[selected['diceTable']['TargetId']];lean=by_id[selected['gamblerLeaningSpot']['TargetId']]
    entities=resolve_link_targets(archive,table,entities,{})
    by_id={e.get('EntityId'):e for e in entities}
    for side in ('1','2'):entities=resolve_link_targets(archive,linked(table,by_id,'seat'+side),entities,{})
    # Resolve all source parents now, then flatten before per-resource mapping.
    selected_ids={table.get('EntityId'),lean.get('EntityId')}
    owners=(table,linked(table,by_id,'seat1'),linked(table,by_id,'seat2'))
    selected_ids.update(l.get('TargetId') for owner in owners for l in owner.findall('EntityLinks/Link'))
    flat={e.get('EntityId'):world_entity(archive,e,entities) for e in entities if e.get('EntityId') in selected_ids}
    return flat[table.get('EntityId')],flat[lean.get('EntityId')],flat


def native_data(target):
    target=Path(target)
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as z:
        entities={e.get('EntityId'):e for e in E.fromstring(read(z,'objects_mission0.xml'))}
        scheduler=E.fromstring(read(z,'tables/ai/scheduler.xml'))
    donor=next((e for e in entities.values() if e.find('Properties') is not None and
                e.find('Properties').get('guidSmartObjectType')==TABLE_TEMPLATE),None)
    if donor is None:raise ValueError('Missing native dice table graph')
    with zipfile.ZipFile(target/'Data/Tables.pak') as z:
        template=E.fromstring(read(z,'Libs/Tables/ai/smartEntity/SmartEntity__so_diceTable_new.xml')).find('.//SmartEntityTemplate')
        lean={side:E.fromstring(read(z,'Libs/Tables/ai/smartEntity/SmartEntity__leaningSpot_'+side+'.xml')).find('.//SmartEntityTemplate')
              for side in ('left','right')}
    with zipfile.ZipFile(target/'Data/Scripts.pak') as z:
        program=E.fromstring(read(z,'AI/world/so_diceTable_new.xml'))
        caller=E.fromstring(read(z,'AI/quests/setkaniVRatbori1/setkanivratbori1.xml')).find("BehaviorTree[@name='moveAndWait']/Root/.//CallBehavior")
    activities=[l for l in scheduler.findall('.//S_ActivityLink') if l.find('Parameters') is not None
        and l.find('Parameters').get('BehaviorName')=='use_opponent'
        and l.find('Parameters').get('BehaviorOverride')=='true'
        and l.find('Parameters').get('ProvidedRole')=='opponent'
        and not any(k in l.find('Parameters').attrib for k in ('LinkTag','RequiredContext','RequiredRole'))]
    if not activities or caller is None:raise ValueError('Missing native dice activation/call contract')
    return entities,scheduler,donor,template,program,lean,caller,activities[0]


def stage(entry,archive,source,target,first_id):
    source,target=Path(source),Path(target)
    table,lean,source_entities=resolve(entry,archive)
    script=lean.find('Properties/Script')
    flags=dict(v.split(':',1) for v in (script.get('Misc','') if script is not None else '').split('|') if ':' in v)
    if flags!={'leanBack':'false','leanLeft':'true','leanRight':'true'}:
        raise ValueError('Only authored persistent left/right dice fallback is supported')
    with zipfile.ZipFile(source/'Data/GameData.pak') as z:helpers=E.fromstring(read(z,'Libs/SmartObjects.xml'))
    with zipfile.ZipFile(source/'Data/Scripts.pak') as z:
        tree=E.fromstring(read(z,'Libs/AI/'+SOURCE[0])).find("BehaviorTree[@name='"+SOURCE[1]+"']")
        social=read(z,'Scripts/Script/SocialClass.lua').decode('utf-8-sig')
        validate_leaning(E.fromstring(read(z,'Libs/AI/final/so_leanSpot.xml')).find("BehaviorTree[@name='use']"))
    native,scheduler,donor,template,program,lean_templates,caller,activity=native_data(target)
    objects=build(table,source_entities,donor,native,first_id,helpers)
    rows=scheduler_rows(table,objects,donor,native,scheduler)
    template,behavior,policy=opponent(tree,social,program,template)
    leaning=lean_program(behavior,policy['minimum_groschen'],caller)
    owner=next(e for e in objects if e.get('Name')=='gm_dice_'+table.get('EntityId')+'_table')
    owner.find('Properties').set('guidSmartObjectType',template.get('DatabaseId'))
    lean_host=E.Element('Entity',Name='gm_dice_'+table.get('EntityId')+'_lean_host',EntityId=str(first_id+len(objects)),
        EntityGuid=identity('dice-lean-host/'+lean.get('EntityGuid')),EntityClass='SmartObjectHolder',
        Pos=lean.get('Pos'),Rotate=lean.get('Rotate','1,0,0,0'))
    # SmartEntity database identities are UUIDs, unlike entity graph WUIDs.
    import uuid
    lean_template=str(uuid.uuid5(uuid.NAMESPACE_URL,'kingdomcomegluemapper/dice-lean-template/v1'))
    E.SubElement(lean_host,'Properties',guidSmartObjectType=lean_template,bSaved_by_game='0')
    E.SubElement(lean_host,'EntityLinks');objects.append(lean_host)
    rows.append(E.Element('C_SmartHub',EntityGuid=str(guid_value(lean_host.get('EntityGuid'))),IgnoreDeadEnds='false',StupidHub='false'))
    for side in ('left','right'):
        definition=lean_templates[side]
        use=definition.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='use']")
        if use is None or use.get('MaxInstances')!='1' or use.get('InitialState')!='Enabled':
            raise ValueError('Native lean ownership changed')
        pose=native_placement(lean,source,target,'leaning_'+side)
        entity=E.Element('Entity',Name='gm_dice_'+table.get('EntityId')+'_lean_'+side,
            EntityId=str(first_id+len(objects)),EntityGuid=identity('dice-lean/'+lean.get('EntityGuid')+'/'+side),
            EntityClass='DetailMovementSmartObject',Pos=pose.get('Pos'),Rotate=pose.get('Rotate','1,0,0,0'))
        E.SubElement(entity,'Properties',soclass_SmartObjectHelpers='leaning_'+side,
                     guidSmartObjectType=definition.get('DatabaseId'),bSaved_by_game='0')
        objects.append(entity)
        rows.append(E.Element('C_SmartHub',EntityGuid=str(guid_value(entity.get('EntityGuid'))),IgnoreDeadEnds='false',StupidHub='false'))
        E.SubElement(lean_host.find('EntityLinks'),'Link',Name='gm_sourceLean'+side.title(),
                     TargetId=entity.get('EntityId'),TargetGuid=entity.get('EntityGuid'))
    database=E.Element('database',name='barbora');E.SubElement(database,'SmartEntitys',version='1').append(template)
    trees=E.Element('BehaviorTrees');trees.append(behavior)
    name='source_dice_'+str(policy['minimum_groschen'])
    files={'Libs/Tables/ai/smartEntity/SmartEntity__'+name+'.xml':xml(database),'AI/gluemapper/'+name+'.xml':xml(trees)}
    lean_db=E.Element('database',name='barbora')
    lt=E.SubElement(E.SubElement(lean_db,'SmartEntitys',version='1'),'SmartEntityTemplate',
                    DatabaseId=lean_template,Name='gm_source_dice_lean',UpdatePriority='false')
    lb=E.SubElement(E.SubElement(lt,'BehaviorTemplates'),'SmartBehaviorTemplate',Name='use',InitialState='Enabled',MaxInstances='1')
    E.SubElement(lb,'TreeLocation',FileName='gluemapper/source_dice_lean.xml',TreeName='use')
    lean_trees=E.Element('BehaviorTrees');lean_trees.append(leaning)
    files.update({'Libs/Tables/ai/smartEntity/SmartEntity__source_dice_lean.xml':xml(lean_db),
                  'AI/gluemapper/source_dice_lean.xml':xml(lean_trees)})
    report=dict(source_table=table.get('EntityGuid'),source_lean=lean.get('EntityGuid'),resources=len(objects),
                source_seats=[linked(table,source_entities,'seat'+side).get('EntityId') for side in ('1','2')],
                policy=policy,runtime_verified=False)
    return objects,rows,owner,copy.deepcopy(activity),files,report


def extend(files,person,entry,archive,source,target):
    """Replace only the owned placeholder, retaining its authored clock."""
    from character_schedule_world import ARRIVAL_TEMPLATE, baseline_schedule_names, bind_arrivals
    source_table,_,_=resolve(entry,archive)
    entry=dict(entry,arrival=dict(source_table.attrib))
    expected_job='gm_schedule_'+person+'_'+entry['arrival']['EntityId']
    if not any(e.get('Name')==expected_job for e in E.fromstring(files['objects_mission0.xml'])):
        if person not in baseline_schedule_names(files,{person}):raise ValueError('Gambler has a non-owned existing job')
        from character_sleep_work import waking_work_clock
        m=E.fromstring(files['objects_mission0.xml']);s=E.fromstring(files['tables/ai/scheduler.xml'])
        a=unique((e for e in m if e.get('Name')==person),'gambler actor')
        clock=waking_work_clock(m,s,a,{(entry['start_minute'],entry['end_minute'])})
        if not clock:raise ValueError('Gambler has no authored waking work interval')
        files,_=bind_arrivals(files,{person:[dict(entry,start_minute=start,end_minute=end) for start,end in sorted(clock)]},target)
    mission=E.fromstring(files['objects_mission0.xml']);scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
    actor,owner,incoming=source_job(mission,scheduler,person,entry)
    job=unique((e for e in mission if e.get('Name')=='gm_schedule_'+person+'_'+entry['arrival']['EntityId']),'gambler source job')
    prefix='gm_dice_'+source_table.get('EntityId')+'_'
    existing=[e for e in mission if e.get('Name','').startswith(prefix)]
    first=min(int(e.get('EntityId')) for e in existing) if existing else max(int(e.get('EntityId','0')) for e in mission)+1
    objects,rows,table,activity,definitions,report=stage(entry,archive,source,target,first)
    if existing and (len(existing)!=len(objects) or {signature(e) for e in existing}!={signature(e) for e in objects}):
        raise ValueError('Existing dice resources differ from source/native contract')
    hub=unique((r for r in scheduler.find('Schedulers') if r.get('EntityGuid')==str(guid_value(job.get('EntityGuid')))),'gambler arrival hub')
    activity.set('TargetGuid',str(guid_value(table.get('EntityGuid'))))
    activity.find('Parameters').set('TimeOfDayStart','0');activity.find('Parameters').set('TimeOfDayEnd','1440')
    tag='gm_dice_funded_'+actor.get('EntityGuid').replace('-','').lower()
    p=activity.find('Parameters');p.set('LinkTag',tag);p.set('InvertLinkTagRequirement','false');p.set('HaltOnInvalid','false')
    lean_host=next(e for e in objects if e.get('Name').endswith('_lean_host'))
    lean_activity=copy.deepcopy(activity);lean_activity.set('TargetGuid',str(guid_value(lean_host.get('EntityGuid'))))
    p=lean_activity.find('Parameters');p.set('BehaviorName','use');p.set('BehaviorOverride','false')
    p.attrib.pop('ProvidedRole',None);p.set('InvertLinkTagRequirement','true');p.set('HaltOnInvalid','true')
    planned=E.Element('Links');planned.extend((activity,lean_activity))
    complete=job.get('EntityClass')=='SchedulerHub' and hub.find('Links') is not None
    if complete:
        if (not existing or signature(hub.find('Links'))!=signature(planned)
                or any(l.find('Parameters').get('BehaviorName') is not None for l in incoming)):
            raise ValueError('Existing gambler dispatcher differs from contract')
    else:
        if existing or job.find('Properties') is None or job.find('Properties').get('guidSmartObjectType')!=ARRIVAL_TEMPLATE or len(hub):
            raise ValueError('Gambler arrival is not an unmodified owned placeholder')
        if any(l.find('Parameters').get('BehaviorName')!='use' for l in incoming):
            raise ValueError('Gambler source activity has conflicting behavior')
    # Ordinary converted benches at these same authored seats must not expose a
    # second independent occupancy resource. Reject any external schedule user.
    legacy=[e for e in mission if any(e.get('Name','').startswith('gm_bench_'+sid+'_') for sid in report['source_seats'])]
    old_guids={e.get('EntityGuid') for e in legacy};old_numbers={str(guid_value(g)) for g in old_guids}
    if any(l.get('TargetGuid') in old_numbers for l in scheduler.findall('.//S_ActivityLink')):
        raise ValueError('Dice seat is already owned by another converted schedule')
    if any(l.get('TargetGuid') in old_guids for e in mission if e not in legacy for l in e.findall('EntityLinks/Link')):
        raise ValueError('Dice seat has external converted interaction ownership')
    waiting=E.fromstring(files['waitinglinks.xml'])
    for parent in waiting.iter():
        for record in list(parent):
            if record.tag=='WaitingLink' and (record.get('SourceId') in old_guids or record.get('TargetId') in old_guids):parent.remove(record)
    for e in legacy:mission.remove(e)
    for row in list(scheduler.find('Schedulers')):
        if row.get('EntityGuid') in old_numbers:scheduler.find('Schedulers').remove(row)
    if not complete:
        mission.extend(objects)
        job.set('EntityClass','SchedulerHub');job.remove(job.find('Properties'));E.SubElement(job,'Properties',bSaved_by_game='0')
        hub.set('Position',job.get('Pos'));hub.append(planned)
        for link in incoming:link.find('Parameters').attrib.pop('BehaviorName')
        for link in actor.findall('EntityLinks/Link'):
            if link.get('TargetGuid')==job.get('EntityGuid'):link.set('Name','_')
        for record in waiting.iter('WaitingLink'):
            if record.get('TargetId')==job.get('EntityGuid'):
                for child in record:
                    if child.text=='_,use':child.text='_'
        edges=job.find('EntityLinks')
        if edges is None:edges=E.SubElement(job,'EntityLinks')
        E.SubElement(edges,'Link',Name='_,use_opponent',TargetId=table.get('EntityId'),TargetGuid=table.get('EntityGuid'))
        E.SubElement(edges,'Link',Name='_,use',TargetId=lean_host.get('EntityId'),TargetGuid=lean_host.get('EntityGuid'))
    # Expiry must cancel an already acquired dice/lean behavior, not only stop
    # future selections. This is the same contract as generated sleep/work.
    for link in incoming:link.find('Parameters').set('HaltOnInvalid','true')
    for row in rows:
        found=[r for r in scheduler.find('Schedulers') if r.get('EntityGuid')==row.get('EntityGuid')]
        if found and (len(found)!=1 or signature(found[0])!=signature(row)):raise ValueError('Conflicting dice scheduler resource')
        if not found:scheduler.find('Schedulers').append(row)
    graph_links=[(e.get('EntityGuid'),l.get('TargetGuid'),l.get('Name','')) for e in objects for l in e.findall('EntityLinks/Link')]
    graph_links.append((job.get('EntityGuid'),table.get('EntityGuid'),'_,use_opponent'))
    graph_links.append((job.get('EntityGuid'),lean_host.get('EntityGuid'),'_,use'))
    updated=dict(files,**{'objects_mission0.xml':xml(mission),'tables/ai/scheduler.xml':xml(scheduler),
        'waitinglinks.xml':append_links(xml(waiting),graph_links,allow_untagged=True)})
    report.update(person=person,actor_guid=actor.get('EntityGuid'),funded_tag=tag,job='source_gambler_dice_or_lean',intervals=sorted({(l.find('Parameters').get('TimeOfDayStart'),
        l.find('Parameters').get('TimeOfDayEnd')) for l in incoming}),removed_duplicate_seats=len(legacy))
    return updated,definitions,report


def extend_people(files, people, tables, archive, source, target):
    from character_schedule import plan
    names={e.get('Name') for e in E.fromstring(files['objects_mission0.xml'])}
    result=files;definitions={};reports=[]
    for name,person in people.items():
        if name not in names:continue
        schedule=plan(person,tables)
        entries=[e for e in schedule['resolved'] if supports(e)]
        if not entries:continue
        if schedule['pending'] or len(entries)!=1:
            raise ValueError('Gambler requires one fully resolved source work interval: '+name)
        result,new_definitions,report=extend(result,name,entries[0],archive,source,target)
        for path,data in new_definitions.items():
            if path in definitions and definitions[path]!=data:raise ValueError('Conflicting shared dice policy')
            definitions[path]=data
        reports.append(report)
    return result,definitions,reports
