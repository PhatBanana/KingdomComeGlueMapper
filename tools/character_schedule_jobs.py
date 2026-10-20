"""Native job adapters selected by source behavior identity, never NPC name."""
import copy
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from campaign_entity_links import append_links
from campaign_entity_links import guid_value
from character_job_items import reservation_contract, register_item, bind_reservation
from character_person import resolve_link_targets
from upgrade_map import read, xml
import character_blacksmith_jobs


def native_job(target, name):
    with zipfile.ZipFile(Path(target)/'Data/Tables.pak') as archive:
        table=ET.fromstring(read(archive,'Libs/Tables/ai/smartEntity/SmartEntity__'+name+'.xml'))
    template=table.find('SmartEntitys/SmartEntityTemplate')
    with zipfile.ZipFile(Path(target)/'Data/Levels/trosecko/level.pak') as archive:
        entities=list(ET.fromstring(read(archive,'objects_mission0.xml')))
    byid={e.get('EntityId'):e for e in entities}
    for job in entities:
        p=job.find('Properties')
        if p is not None and p.get('guidSmartObjectType')==template.get('DatabaseId'):
            return copy.deepcopy(job),reservation_contract(job,byid)
    raise ValueError('No native job object for '+name)


def bind_jobs(files, schedules, archive, target, registered_items, convert_routes=False):
    """Activate supported job phases and explicitly report remaining phases.

The housework sweeping phase uses the real native reservation/hand-item path.
It does not represent the other housework activities as converted.
"""
    mission=ET.fromstring(files['objects_mission0.xml'])
    scheduler=ET.fromstring(files['tables/ai/scheduler.xml'])
    source_entities=list(ET.fromstring(read(archive,'objects_mission0.xml')))
    waiting=[];report=[]; renamed={}
    for person,entries in schedules.items():
        for entry in entries:
            behavior=entry['behavior']
            if entry.get('market_work'):
                from character_market_jobs import bind as bind_market, ACTIVITY
                job, item_report = bind_market(mission, scheduler, person, entry, target)
                renamed[job.get('EntityGuid')] = ACTIVITY
                report.append(item_report)
                continue
            if entry.get('station_work'):
                from character_station_work import resources
                template,_ = resources(entry['station_work'])
                job=next(e for e in mission if e.get('Name')=='gm_schedule_'+person+'_'+entry['arrival']['EntityId'])
                job.find('Properties').set('guidSmartObjectType',template)
                report.append(dict(person=person,job='source_station',source_behavior=dict(behavior),
                    source_destination=entry['arrival'],pending=[],runtime_verified=False))
                continue
            if (behavior['tree_file'].lower(),behavior['tree_name']) == ('final/sa_garrison.xml','Guard'):
                # Source fixed duty posts become native guard activities. The
                # native behavior owns authority/on-duty contexts and releases
                # them when interrupted; no permanent aggression override.
                with zipfile.ZipFile(Path(target)/'Data/Tables.pak') as native:
                    template=ET.fromstring(read(native,'Libs/Tables/ai/smartEntity/SmartEntity__so_guardSpotPoint.xml')).find('.//SmartEntityTemplate')
                activity='guardNonImportant'
                contract=template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='"+activity+"']")
                if contract is None or contract.get('InitialState')!='Enabled':
                    raise ValueError('Missing native guard activity contract')
                job=next(e for e in mission if e.get('Name')=='gm_schedule_'+person+'_'+entry['arrival']['EntityId'])
                job.set('EntityClass','DetailMovementSmartObject')
                job.remove(job.find('Properties'))
                props=ET.SubElement(job,'Properties',guidSmartObjectType=template.get('DatabaseId'),bSaved_by_game='0')
                ET.SubElement(props,'MovementDetails',esMovementSpeed='a_RelaxedWalk')
                renamed[job.get('EntityGuid')]=activity
                for link in scheduler.findall('.//S_ActivityLink'):
                    if link.get('TargetGuid')==str(guid_value(job.get('EntityGuid'))):
                        link.find('Parameters').set('BehaviorName',activity)
                report.append(dict(person=person,job='guard',native_behavior=activity,
                    source_workplace=entry['arrival'],source_workplace_links=entry.get('workplace_links',[]),
                    pending=['rain and secondary post selection'],runtime_verified=False))
                continue
            if (behavior['tree_file'].lower(),behavior['tree_name']) == character_blacksmith_jobs.SOURCE_BEHAVIOR:
                job=next(e for e in mission if e.get('Name')=='gm_schedule_'+person+'_'+entry['arrival']['EntityId'])
                links,item_report=character_blacksmith_jobs.bind(mission,scheduler,entry,job,archive,target,registered_items)
                waiting.extend(links);report.append(dict(person=person,**item_report))
                continue
            bartending = (behavior['tree_file'].lower(),behavior['tree_name']) == ('final/sa_pub_v3.xml','Bartender')
            if not bartending and (behavior['tree_file'].lower(),behavior['tree_name']) != ('final/sa_home.xml','housework'):
                report.append(dict(person=person, source_behavior=dict(behavior),
                    source_area=dict(entry['area']), source_links=copy.deepcopy(entry['target_links']),
                    pending=['source work program and its dependency graph require conversion'],
                    runtime_verified=False))
                continue
            native,contracts=native_job(target,'so_sweeping')
            area=ET.Element('Entity',entry['area']);links=ET.SubElement(area,'EntityLinks')
            for l in entry['target_links']:ET.SubElement(links,'Link',l)
            source_entities=resolve_link_targets(archive,area,source_entities,{})
            byid={e.get('EntityId'):e for e in source_entities}
            direct=[byid[l['TargetId']] for l in entry['target_links']]
            job=next(e for e in mission if e.get('Name')=='gm_schedule_'+person+'_'+entry['arrival']['EntityId'])
            job.remove(job.find('Properties'));job.append(copy.deepcopy(native.find('Properties')))
            item_reports=[]
            for contract in contracts:
                candidates={e.get('EntityId'):e for e in direct if e.get('EntityClass')=='ItemSlot'
                    and e.find('Properties').get('guidItemClassId','').lower()==contract['item_id']}
                if not candidates:raise ValueError('Missing source job tool')
                # The source GraphSearch short-circuits on an available slot;
                # multiple authored brooms are a pool, not an ambiguous identity.
                # Preserve the pool for the native scheduler's reservation search.
                for source_slot in candidates.values():
                    source_entities=resolve_link_targets(archive,source_slot,source_entities,{})
                    slot,item_report=register_item(mission,source_slot,{e.get('EntityId'):e for e in source_entities},contract,registered_items)
                    waiting.extend(bind_reservation(mission,job,slot,contract));item_reports.append(item_report)
            # Retain the source route identities for the path conversion phase.
            routes={e.get('EntityId'):e for e in direct if any(l['TargetId']==e.get('EntityId')
                    and l['Name']=='SweepingPath' for l in entry['target_links'])}
            if not routes:raise ValueError('Source housework has no sweeping route')
            route_report=None
            if convert_routes:
                from character_sweeping_routes import bind
                route_edges,route_report=bind(mission,job,routes.values(),read(archive,'ubernav.tmm'),files['ubernav.tmm'])
                waiting.extend(route_edges)
            report.append(dict(person=person, job='bartender_sweeping' if bartending else 'sweeping', tools=item_reports,
                source_routes=[e.attrib for e in routes.values()],
                route_conversion=route_report,
                pending=([] if convert_routes else ['source sweeping route traversal'])+(['patron drink/meal orders','table wiping','closing announcement'] if bartending else ['cooking','embroidery','water carrying','hanging out']),
                runtime_verified=False))
    result=dict(files)
    for entity in mission:
        for edge in entity.findall('EntityLinks/Link'):
            if edge.get('TargetGuid') in renamed and edge.get('Name')=='_,use':
                edge.set('Name','_,'+renamed[edge.get('TargetGuid')])
    authoring=ET.fromstring(files['waitinglinks.xml'])
    for record in authoring.findall('.//WaitingLink'):
        if record.get('TargetId') in renamed:
            for definition in record:
                if definition.text=='_,use':definition.text='_,'+renamed[record.get('TargetId')]
    result['objects_mission0.xml']=xml(mission)
    result['tables/ai/scheduler.xml']=xml(scheduler)
    result['waitinglinks.xml']=append_links(xml(authoring),waiting,allow_untagged=True)
    return result,report
