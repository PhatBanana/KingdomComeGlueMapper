"""Native job adapters selected by source behavior identity, never NPC name."""
import copy
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from campaign_entity_links import append_links
from character_job_items import reservation_contract, register_item, bind_reservation
from character_person import resolve_link_targets
from upgrade_map import read, xml


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


def bind_jobs(files, schedules, archive, target, registered_items):
    """Activate supported job phases and explicitly report remaining phases.

The housework sweeping phase uses the real native reservation/hand-item path.
It does not represent the other housework activities as converted.
"""
    mission=ET.fromstring(files['objects_mission0.xml'])
    source_entities=list(ET.fromstring(read(archive,'objects_mission0.xml')))
    waiting=[];report=[]
    for person,entries in schedules.items():
        for entry in entries:
            behavior=entry['behavior']
            if (behavior['tree_file'].lower(),behavior['tree_name']) != ('final/sa_home.xml','housework'):
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
                if len(candidates)!=1:raise ValueError('Missing or ambiguous source job tool')
                source_slot=next(iter(candidates.values()))
                source_entities=resolve_link_targets(archive,source_slot,source_entities,{})
                slot,item_report=register_item(mission,source_slot,{e.get('EntityId'):e for e in source_entities},contract,registered_items)
                waiting.extend(bind_reservation(mission,job,slot,contract));item_reports.append(item_report)
            # Retain the source route identities for the path conversion phase.
            routes={e.get('EntityId'):e for e in direct if any(l['TargetId']==e.get('EntityId')
                    and l['Name']=='SweepingPath' for l in entry['target_links'])}
            if not routes:raise ValueError('Source housework has no sweeping route')
            # The first phase is tested at the source arrival; route traversal
            # remains explicitly pending until its compiled points are imported.
            report.append(dict(person=person, job='sweeping', tools=item_reports,
                source_routes=[e.attrib for e in routes.values()],
                pending=['source sweeping route traversal','cooking','embroidery','water carrying','hanging out'],
                runtime_verified=False))
    result=dict(files)
    result['objects_mission0.xml']=xml(mission)
    result['waitinglinks.xml']=append_links(files['waitinglinks.xml'],waiting,allow_untagged=True)
    return result,report
