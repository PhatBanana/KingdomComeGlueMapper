"""Public, source-linked table benches for the bartender's resting phase.

Reserved/custom seating needs the source preference controller and is excluded.
The existing native bench retains its occupancy, animation and interruption.
"""
import copy
import xml.etree.ElementTree as E
from campaign_entity_links import append_links, guid_value
from character_city_benches import prepare_sources
from character_person import resolve_link_targets, unique, world_entity
from character_station_work import unquote
from character_work_pool import bind
from upgrade_map import read, xml


def public_edges(entity):
    return [l for l in entity.findall('EntityLinks/Link')
            if not {'parent', 'reserved'}.intersection(l.get('Name', '').split(','))]


def source_contract(pub, table):
    root = pub.find("BehaviorTree[@name='resting']/Root")
    query = unique([] if root is None else root.findall('.//GraphSearch'), 'pub rest table query')
    reserve = query.find('.//LinkTagFilter')
    if (unquote(query.get('Origin','')) != '__area.id' or unquote(query.get('depth','')) != '1'
            or unquote(query.get('EdgePruning','')) != 'parent'
            or query.find('CategoryFilter') is None
            or unquote(query.find('CategoryFilter').get('categories','')) != 'pubTable'
            or query.find('NegationOp') is None or reserve is None
            or unquote(reserve.get('tag','')) != 'reserved'
            or not any(unquote(n.get('BehaviorName','')) == 'getBench' for n in root.iter('CallBehavior'))):
        raise ValueError('Source pub rest selection changed')
    leaf = table.find("BehaviorTree[@name='getBench']/Root")
    queries = [] if leaf is None else leaf.findall('.//GraphSearch')
    if len(queries) != 2:
        raise ValueError('Source pub rest bench selection changed')
    for q in queries:
        category=q.find('CategoryFilter')
        if (unquote(q.get('Origin','')) != '__object.id' or unquote(q.get('depth','')) != '1'
                or unquote(q.get('EdgePruning','')) != 'parent' or category is None
                or unquote(category.get('categories','')) != 'Seat'):
            raise ValueError('Source pub rest bench query changed')


def resolve(entry, archive, source, reader):
    blobs=reader(source, {'pub':('Scripts.pak','Libs/AI/final/sa_pub_v3.xml'),
        'table':('Scripts.pak','Libs/AI/final/so_pub_table_2.xml')})
    source_contract(E.fromstring(blobs['pub']['data']),E.fromstring(blobs['table']['data']))
    area=E.Element('Entity',entry['area']);links=E.SubElement(area,'EntityLinks')
    for l in entry['target_links']: E.SubElement(links,'Link',l)
    for l in list(links):
        if l not in public_edges(area): links.remove(l)
    entities=resolve_link_targets(archive,area,list(E.fromstring(read(archive,'objects_mission0.xml'))),{})
    byid={e.get('EntityId'):e for e in entities};seats={}
    for link in links:
        table=byid[link.get('TargetId')];props=table.find('Properties')
        if props is None or 'pubTable' not in props.get('sWH_AI_EntityCategory','').split(','): continue
        query=E.Element('Entity',table.attrib)
        E.SubElement(query,'EntityLinks').extend(copy.deepcopy(public_edges(table)))
        entities=resolve_link_targets(archive,query,entities,{})
        byid={e.get('EntityId'):e for e in entities}
        for edge in query.findall('EntityLinks/Link'):
            seat=byid[edge.get('TargetId')];props=seat.find('Properties')
            if props is None or 'Seat' not in props.get('sWH_AI_EntityCategory','').split(','): continue
            if any('reserved' in l.get('Name','').split(',') for l in seat.findall('EntityLinks/Link')): continue
            if seat.get('EntityClass') != 'SmartObjectHolder' or not props.get('soclasses_SmartObjectHelpers','').startswith('Bench_'):
                raise ValueError('Unsupported public pub bench')
            seats[seat.get('EntityId')]=dict(world_entity(archive,seat,entities).attrib)
    return list(seats.values())


def upgrade_files(files,schedules,archive,target,source,reader):
    mission=E.fromstring(files['objects_mission0.xml']);scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
    waiting=[];reports=[]
    for person,entries in schedules.items():
        for entry in entries:
            if not any(e.get('Name') == 'gm_schedule_'+person+'_'+entry['arrival']['EntityId'] for e in mission):continue
            seats,activity=prepare_sources(mission,resolve(entry,archive,source,reader),target)
            if not seats:continue
            resources=[(s,E.Element('C_SmartHub',EntityGuid=str(guid_value(s.get('EntityGuid'))),IgnoreDeadEnds='false',StupidHub='false')) for s in seats]
            pool,added,clock=bind(mission,scheduler,person,entry,'pub_rest',resources,activity)
            waiting.extend(added)
            reports.append(dict(person=person,job='source_pub_rest',extension_only=True,intervals=clock,
                resources=[s.get('Name') for s in seats],runtime_verified=False,
                pending=['Source bartender phase ordering and reserved/custom seat preferences']))
    return dict(files,**{'objects_mission0.xml':xml(mission),'tables/ai/scheduler.xml':xml(scheduler),
        'waitinglinks.xml':append_links(files['waitinglinks.xml'],waiting,allow_untagged=True)}),reports
