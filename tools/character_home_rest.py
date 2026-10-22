"""Native bench rest for otherwise unsupported source housework arrivals.

Only areas without an outdoor Seat choice are lowered: their source indoor
fallback is independent of weather. Existing active jobs are left intact.
"""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as E

from campaign_dependency_adapters import SourceTables
from campaign_entity_links import append_links, guid_value, native_guid
from campaign_sources import RetailSourceReader
from character_fence_work import supports
from character_person import resolve_link_targets, unique, world_entity
from character_station_work import unquote
from character_work_capabilities import housework_phases
from upgrade_map import read, xml
import character_city_benches as benches


def source_contract(entry, tables, program):
    definitions = {r['sa_behaviour_tag_id']: r for r in tables.get('ai/sa_behaviour_tag')['rows']}
    bindings = tables.get('ai/sa_smart_area2sa_behaviour_tag')['rows']
    behavior = unique((definitions[b['sa_behaviour_tag_id']] for b in bindings
        if b['sa_smart_area_id'] == entry['area_template']['sa_smart_area_id']
        and definitions[b['sa_behaviour_tag_id']]['sa_behaviour_tag_name'] == 'hangingOut'), 'home rest binding')
    if (behavior['tree_file'].replace('\\', '/').lower(), behavior['tree_name']) != ('final/sa_home.xml', 'hangingOut'):
        raise ValueError('Unsupported home rest behavior')
    root = program.find("BehaviorTree[@name='hangingOut']/Root")
    reserve = None if root is None else root.find('.//ReserveBehavior')
    if reserve is None or unquote(reserve.get('reserveFrom', '')) != 'bench' or unquote(reserve.get('behaviorName', '')) != 'use':
        raise ValueError('Source home rest reservation changed')
    selector = reserve.find('Search/ReserveBehaviorSearch/Selector')
    if selector is None or [c.tag for c in selector] != ['IfCondition', 'GraphSearch']:
        raise ValueError('Source home rest weather selection changed')
    if (unquote(selector[0].get('condition', '')) != '$t_weatherState.type == $enum:WeatherType.Normal'
            or unquote(selector[0].get('failOnCondition', '')) != 'true'):
        raise ValueError('Source home rest weather condition changed')
    searches = [selector[0].find('GraphSearch'), selector[1]]
    for index, search in enumerate(searches):
        expected = dict(Origin='__area.id', depth='$t_graphDepth', EdgePruning='parent,inventory', includeOrigin='false', AllowedEdges='', SubGraph='', SetOperationChoice='Intersection|And')
        if search is None or any(unquote(search.get(k, '')) != v for k, v in expected.items()):
            raise ValueError('Source home rest graph changed')
        tags = ['NegationOp', 'LinkTagFilter' if index == 0 else 'NegationOp', 'CategoryFilter', 'HasBehaviorFilter', 'Nodalyzer']
        if [c.tag for c in search] != tags:
            raise ValueError('Source home rest filters changed')
        dice = search[0].find('Child0/CategoryFilter')
        if (dice is None or unquote(dice.get('categories', '')) != 'diceTable'
                or any(unquote(search[0].get(k, '')) != v for k, v in dict(Results='true', Advance='false', EndOp='true').items())
                or unquote(search[2].get('categories', '')) != 'Seat'
                or unquote(search[3].get('BehaviorList', '')) != 'use'
                or unquote(search[3].get('FilterChoice', '')) != 'Requestable'):
            raise ValueError('Source home rest filters changed')
        outside = search[1] if index == 0 else search[1].find('Child0/LinkTagFilter')
        if outside is None or unquote(outside.get('tag', '')) != 'outside':
            raise ValueError('Source home rest outside filter changed')
        if index == 1 and any(unquote(search[1].get(k, '')) != v for k, v in dict(Results='true', Advance='true', EndOp='true').items()):
            raise ValueError('Source home rest outside negation changed')
    default = root.find("OnInit/Sequence/VariableExistsGate/Else/Expression")
    call = reserve.find('.//CallBehavior')
    if (default is None or unquote(default.get('expressions', '')).replace(' ', '') != '$t_graphDepth=1'
            or call is None or unquote(call.get('Target', '')) != 'bench' or unquote(call.get('BehaviorName', '')) != 'use'):
        raise ValueError('Source home rest depth/call changed')
    housework = program.find("BehaviorTree[@name='housework']/Root")
    if housework is None or 't_graphDepthParent' in E.tostring(housework, encoding='unicode'):
        raise ValueError('Unsupported home rest inherited depth')


def resolve(entry, archive):
    area = E.Element('Entity', entry['area']); links = E.SubElement(area, 'EntityLinks')
    for link in entry['target_links']:
        if not {'parent', 'inventory'}.intersection(link.get('Name', '').split(',')):
            E.SubElement(links, 'Link', link)
    entities = resolve_link_targets(archive, area, list(E.fromstring(read(archive, 'objects_mission0.xml'))), {})
    by_id = {e.get('EntityId'): e for e in entities}; seats = {}
    for link in links:
        seat = by_id[link.get('TargetId')]; p = seat.find('Properties')
        categories = set(p.get('sWH_AI_EntityCategory', '').split(',')) if p is not None else set()
        if 'Seat' not in categories or 'diceTable' in categories: continue
        # Outdoor-priority areas require a weather-aware dispatcher. Do not
        # silently turn their indoor fallback into an unconditional alternative.
        if 'outside' in link.get('Name', '').split(','): return []
        if seat.get('EntityClass') != 'SmartObjectHolder' or not p.get('soclasses_SmartObjectHelpers', '').startswith('Bench_'):
            raise ValueError('Unsupported source home rest seat')
        seats[seat.get('EntityId')] = dict(world_entity(archive, seat, entities).attrib)
    return list(seats.values())


def bind(mission, scheduler, person, entry, source_seats, target):
    from character_schedule_world import ARRIVAL_TEMPLATE
    actor = unique((e for e in mission if e.get('Name') == person), 'home rest actor')
    job = unique((e for e in mission if e.get('Name') == 'gm_schedule_'+person+'_'+entry['arrival']['EntityId']), 'home rest arrival')
    expected = native_guid(int.from_bytes(hashlib.sha256(('schedule-arrival/'+actor.get('EntityGuid')+'/'+entry['arrival']['EntityGuid']).encode()).digest()[:8], 'little'))
    rows = scheduler.find('Schedulers'); identity = str(guid_value(job.get('EntityGuid')))
    hub = unique((r for r in rows if r.get('EntityGuid') == identity), 'home rest hub')
    uses = [(r, l) for r in rows for l in r.findall('Links/S_ActivityLink') if l.get('TargetGuid') == identity]
    if (job.get('EntityGuid') != expected or job.get('EntityClass') != 'SmartObjectHolder'
            or job.find('Properties') is None or job.find('Properties').get('guidSmartObjectType') != ARRIVAL_TEMPLATE
            or job.findall('EntityLinks/Link') or hub.tag != 'C_SmartHub' or len(hub) or not uses
            or any(r.get('EntityGuid') != str(guid_value(actor.get('EntityGuid')))
                   or l.find('Parameters') is None
                   or l.find('Parameters').get('BehaviorName') != 'use' for r, l in uses)):
        raise ValueError('Cannot replace non-owned home rest arrival')
    seats, activity = benches.prepare_sources(mission, source_seats, target)
    if not seats: raise ValueError('Empty home rest seat pool')
    incoming = [l for _, l in uses]; choices = benches.choices(seats, activity, incoming)
    job.set('EntityClass', 'SchedulerHub'); job.remove(job.find('Properties'))
    E.SubElement(job, 'Properties', bSaved_by_game='0'); hub.set('Position', job.get('Pos')); E.SubElement(hub, 'Links')
    for link in incoming: link.find('Parameters').attrib.pop('BehaviorName')
    waiting = benches.attach(job, hub, rows, seats, choices)
    for link in actor.findall('EntityLinks/Link'):
        if link.get('TargetGuid') == job.get('EntityGuid') and link.get('Name') == '_,use': link.set('Name', '_')
    return job, waiting, seats


def upgrade(files, schedules, archive, target):
    from character_schedule_world import ARRIVAL_TEMPLATE
    mission = E.fromstring(files['objects_mission0.xml']); scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
    waiting = E.fromstring(files['waitinglinks.xml']); links = []; reports = []
    source = Path(archive.filename).parents[3]
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        program = E.fromstring(reader(source, {'home': ('Scripts.pak', 'Libs/AI/final/sa_home.xml')})['home']['data'])
        for person, entries in schedules.items():
            actor = next((e for e in mission if e.get('Name') == person), None)
            if actor is None or actor.get('EntityClass') not in ('NPC', 'NPC_Female'): continue
            phases = housework_phases(program.find("BehaviorTree[@name='housework']"), actor.get('EntityClass'))
            if 'hangingOut' not in phases: continue
            for entry in entries:
                if not supports(entry): continue
                job = next((e for e in mission if e.get('Name') == 'gm_schedule_'+person+'_'+entry['arrival']['EntityId']), None)
                if job is None or job.find('Properties') is None or job.find('Properties').get('guidSmartObjectType') != ARRIVAL_TEMPLATE: continue
                identity = str(guid_value(job.get('EntityGuid')))
                actual = {(int(l.find('Parameters').get('TimeOfDayStart')), int(l.find('Parameters').get('TimeOfDayEnd')))
                    for l in scheduler.findall('.//S_ActivityLink') if l.get('TargetGuid') == identity}
                clock = {(e['start_minute'], e['end_minute']) for e in entries if supports(e) and e['arrival']['EntityId'] == entry['arrival']['EntityId']}
                from character_sleep_work import waking_work_clock
                clock = waking_work_clock(mission, scheduler, actor, clock)
                if actual != clock: raise ValueError('Home rest clock differs from source')
                source_contract(entry, tables, program)
                selected = resolve(entry, archive)
                if not selected: continue
                job, added, seats = bind(mission, scheduler, person, entry, selected, target); links.extend(added)
                for record in waiting.findall('.//WaitingLink'):
                    if record.get('TargetId') == job.get('EntityGuid'):
                        for definition in record:
                            if definition.text == '_,use': definition.text = '_'
                reports.append(dict(person=person, job='native_home_bench_rest', source_behavior=entry['behavior'],
                    source_area=entry['area'], seats=[dict(name=s.get('Name'), guid=s.get('EntityGuid')) for s in seats],
                    intervals=sorted(clock), runtime_verified=False, pending=[p for p in phases if p != 'hangingOut']+
                    ['source rest duration and wait-to-time-change', 'housework phase selection']))
    return dict(files, **{'objects_mission0.xml': xml(mission), 'tables/ai/scheduler.xml': xml(scheduler),
        'waitinglinks.xml': append_links(xml(waiting), links, allow_untagged=True)}), reports
