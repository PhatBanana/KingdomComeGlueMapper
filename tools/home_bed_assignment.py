"""Explicit household bed assignments layered onto existing sleep schedules."""
import copy
import xml.etree.ElementTree as E
from campaign_entity_links import append_links, guid_value
from character_sleep_work import identity, owned_links, restrict_work_to_waking_hours
from upgrade_map import xml


def choices(mission,actor):
    assignments=actor.findall("EntityLinks/Link[@Name='sleepBed']")
    if not assignments:return []
    by_guid={e.get('EntityGuid'):e for e in mission}
    result=[]
    for edge in assignments:
        bed=by_guid.get(edge.get('TargetGuid'))
        if bed is None or bed.get('EntityId')!=edge.get('TargetId') or bed.get('EntityClass')!='StanceSmartObject':
            raise ValueError('Invalid assigned household bed')
        if not any(l.get('TargetGuid')==actor.get('EntityGuid') for l in bed.findall("EntityLinks/Link[@Name='preferedSleeper']")):
            raise ValueError('Assigned bed lacks its preferred sleeper')
        result.append(dict(source_id=bed.get('Name'),entity_name=bed.get('Name'),kind='assigned_home',rank=100,
                           position=tuple(map(float,bed.get('Pos').split(','))),evidence='explicit_sleepBed_link'))
    return result


def apply(files):
    """Prefer assigned beds at night and keep generated work within waking hours."""
    mission=E.fromstring(files['objects_mission0.xml']);scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
    rows=scheduler.find('Schedulers');network=[]
    by_guid={e.get('EntityGuid'):e for e in mission}
    for actor in mission:
        selected=choices(mission,actor)
        if not selected:continue
        row=next((r for r in rows if r.get('EntityGuid')==str(guid_value(actor.get('EntityGuid')))),None)
        if row is None or not owned_links(mission,rows,actor,row):
            raise ValueError('Assigned sleeper has no validated sleep schedule')
        pool=by_guid[identity(actor)]
        hub=next(r for r in rows if r.get('EntityGuid')==str(guid_value(pool.get('EntityGuid'))))
        preferred=next(e for e in mission if e.get('Name')==max(selected,key=lambda c:c['rank'])['entity_name'])
        pool.set('Pos',preferred.get('Pos'));hub.set('Position',preferred.get('Pos'))
        outgoing=hub.find('Links');old=list(outgoing)
        intervals=[]
        for link in old:
            p=link.find('Parameters');key=(p.get('TimeOfDayStart'),p.get('TimeOfDayEnd'))
            if key not in intervals:intervals.append(key)
        outgoing[:]=[]
        for start,end in intervals:
            group=[l for l in old if (l.find('Parameters').get('TimeOfDayStart'),l.find('Parameters').get('TimeOfDayEnd'))==(start,end)]
            outgoing.extend(group)
            for choice in selected:
                bed=next(e for e in mission if e.get('Name')==choice['entity_name'])
                number=str(guid_value(bed.get('EntityGuid')))
                existing=[l for l in group if l.get('TargetGuid')==number]
                if existing:
                    if len(existing)!=1 or existing[0].find('Parameters').get('Priority')!='100':
                        raise ValueError('Conflicting assigned-bed activity')
                    continue
                template=next((l for l in group if l.find('Parameters').get('ProvidedRole')=='sleeper'
                               and l.find('Parameters').get('BehaviorName')=='use'),None)
                if template is None:raise ValueError('Sleep pool has no native sleeper activity')
                edge=copy.deepcopy(template);edge.set('TargetGuid',number)
                edge.find('Parameters').set('Priority','100');outgoing.append(edge)
        links=pool.find('EntityLinks')
        for choice in selected:
            bed=next(e for e in mission if e.get('Name')==choice['entity_name'])
            if not any(l.get('TargetGuid')==bed.get('EntityGuid') for l in links):
                E.SubElement(links,'Link',Name='_,use',TargetId=bed.get('EntityId'),TargetGuid=bed.get('EntityGuid'))
            network.append((pool.get('EntityGuid'),bed.get('EntityGuid'),'_,use'))
    restrict_work_to_waking_hours(mission,scheduler)
    return dict(files,**{'objects_mission0.xml':xml(mission),'tables/ai/scheduler.xml':xml(scheduler),
                         'waitinglinks.xml':append_links(files['waitinglinks.xml'],network)})
