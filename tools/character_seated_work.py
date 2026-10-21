"""Upgrade source seated needlework to the native bench activity/reservation graph.

Selection uses the source routine and its area links, never actor names or world
coordinates. KCD2 owns movement, stance, interruption and the shared seat resource.
"""
import copy
from pathlib import Path
import re
import xml.etree.ElementTree as E
import zipfile

from campaign_entity_links import guid_value
from character_person import resolve_link_targets, unique, world_entity
from character_station_work import unquote
from upgrade_map import read

SOURCE = ('final/sa_embroider.xml', 'embroider_sit')
ACTIVITY = 'embroidery'


def supports(entry):
    behavior = entry['behavior']
    return (behavior['tree_file'].replace('\\', '/').lower(), behavior['tree_name']) == SOURCE


def resolve(entry, archive, source, reader):
    if source is None or reader is None:
        raise ValueError('Seated work requires its effective source behavior')
    blob = reader(source, {'work': ('Scripts.pak', 'Libs/AI/' + SOURCE[0])})['work']['data']
    root = E.fromstring(blob).find("BehaviorTree[@name='embroider_sit']/Root")
    searches = [] if root is None else root.findall('.//GraphSearch')
    search = unique(searches, 'source seated-work search')
    attrs = {k: unquote(v) for k, v in search.attrib.items()}
    expected = dict(Origin='__area.id', depth='1', selection='true', includeOrigin='false',
                    EdgePruning='parent,inventory', AllowedEdges='', SubGraph='', AllowSubtraph='false')
    filters = [{k: unquote(v) for k, v in f.attrib.items()} for f in search]
    if (any(attrs.get(k) != v for k, v in expected.items())
            or [f.tag for f in search] != ['CategoryFilter', 'HasBehaviorFilter', 'HasBehaviorFilter', 'Nodalyzer']
            or filters[0].get('categories') != 'Seat'
            or [f.get('BehaviorList') for f in filters[1:3]] != ['embroider_needlework', 'use']
            or any(f.get('Source') != 'Child' or f.get('prune') != 'true' for f in filters[:3])):
        raise ValueError('Unsupported source seated-work selection contract')
    area = E.Element('Entity', entry['area'])
    edges = E.SubElement(area, 'EntityLinks')
    for edge in entry['target_links']:
        if not {'parent', 'inventory'}.intersection(edge.get('Name', '').split(',')):
            E.SubElement(edges, 'Link', edge)
    entities = resolve_link_targets(archive, area,
        list(E.fromstring(read(archive, 'objects_mission0.xml'))), {})
    by_id = {e.get('EntityId'): e for e in entities}
    seats = {}
    for edge in edges:
        entity = by_id[edge.get('TargetId')]
        props = entity.find('Properties')
        if props is None or 'Seat' not in props.get('sWH_AI_EntityCategory', '').split(','):
            continue
        # Source bench needlework is disabled on seats with a table. Do not
        # broaden the source query to chairs or arbitrary nearby seating.
        family = props.get('soclasses_SmartObjectHelpers', '')
        script = props.find('Script')
        if (entity.get('EntityClass') != 'SmartObjectHolder' or not family.startswith('Bench_')
                or 'hasTable:true' in (script.get('Misc', '') if script is not None else '')):
            continue
        seats[entity.get('EntityId')] = dict(world_entity(archive, entity, entities).attrib)
    if not seats:
        raise ValueError('Source seated work has no supported table-free bench')
    return dict(entry, arrival=next(iter(seats.values())), seated_work=dict(seats=list(seats.values())))


def native_contract(target):
    target = Path(target)
    with zipfile.ZipFile(target/'Data/Tables.pak') as archive:
        def template(name):
            return E.fromstring(read(archive, 'Libs/Tables/ai/smartEntity/SmartEntity__'+name+'.xml')).find('.//SmartEntityTemplate')
        work, seat = template('so_benchActivity'), template('so_sitPlace')
    behavior = work.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='embroidery']")
    use = seat.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='use']")
    resource = seat.find("Resources/Resource[@Name='use']")
    if (behavior is None or behavior.get('InitialState') != 'Enabled'
            or use is None or use.get('Resource') != 'use'
            or resource is None or resource.get('MaxInstances') != '1'):
        raise ValueError('Native seated-work reservation contract changed')
    location = behavior.find('TreeLocation')
    with zipfile.ZipFile(target/'Data/Scripts.pak') as archive:
        root = E.fromstring(read(archive, 'AI/'+location.get('FileName'))).find(
            "BehaviorTree[@name='"+location.get('TreeName')+"']/Root")
    if (root is None or root.find(".//StanceElement[@smartObject='$__resource.id'][@stance='sitting']") is None
            or root.find(".//EntityContextElement[@context='speech_readyForSwitchDialog']") is None
            or root.find(".//UnstanceAction[@unstance='tailor_embroidery']") is None):
        raise ValueError('Native seated-work stance/lifecycle contract changed')
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as archive:
        rows = E.fromstring(read(archive, 'tables/ai/scheduler.xml')).find('Schedulers')
    # Use the native override policy; the final use edge reserves the seat, and
    # the upstream embroidery override executes against that reserved resource.
    activities = [l for l in rows.findall('.//S_ActivityLink') if l.find('Parameters') is not None
        and l.find('Parameters').get('BehaviorName') == ACTIVITY
        and l.find('Parameters').get('BehaviorOverride') == 'true'
        and l.find('Parameters').get('AllowedGenders') == '2']
    if not activities:
        raise ValueError('Missing native embroidery scheduler override')
    return work.get('DatabaseId'), seat.get('DatabaseId')


def bind(mission, scheduler, person, entry, target):
    from character_schedule_world import ARRIVAL_TEMPLATE
    work_template, seat_template = native_contract(target)
    actor = unique((e for e in mission if e.get('Name') == person), 'seated worker')
    if actor.get('EntityClass') != 'NPC_Female':
        raise ValueError('Native embroidery is restricted to female actors')
    job = unique((e for e in mission if e.get('Name') ==
        'gm_schedule_'+person+'_'+entry['arrival']['EntityId']), 'seated-work arrival')
    if job.find('Properties').get('guidSmartObjectType') != ARRIVAL_TEMPLATE:
        raise ValueError('Seated work requires an importer-owned arrival')
    rows = scheduler.find('Schedulers')
    hub_id = str(guid_value(job.get('EntityGuid')))
    hub = unique((r for r in rows if r.get('EntityGuid') == hub_id), 'seated-work scheduler hub')
    incoming = [l for r in rows for l in r.findall('Links/S_ActivityLink') if l.get('TargetGuid') == hub_id]
    if len(hub) or not incoming or any(l.find('Parameters').get('BehaviorName') != 'use' for l in incoming):
        raise ValueError('Seated-work arrival has conflicting scheduler dependencies')
    seats = []
    for source_seat in entry['seated_work']['seats']:
        pattern = re.compile(r'gm_bench_'+re.escape(source_seat['EntityId'])+r'_\d+_StanceSmartObject')
        converted = [e for e in mission if pattern.fullmatch(e.get('Name', ''))]
        if not converted:
            raise ValueError('Missing converted work bench: '+source_seat['EntityId'])
        for seat in converted:
            props = seat.find('Properties')
            if (seat.get('EntityClass') != 'StanceSmartObject' or props is None
                    or props.get('guidSmartObjectType') != seat_template
                    or '_Table_' in props.get('soclass_SmartObjectHelpers', '')
                    or seat.find("EntityLinks/Link[@Name='withTable']") is not None):
                raise ValueError('Incompatible converted work bench: '+seat.get('Name'))
            seat_id = str(guid_value(seat.get('EntityGuid')))
            registered = [r for r in rows if r.get('EntityGuid') == seat_id]
            if registered and (len(registered) != 1 or len(registered[0]) or registered[0].tag != 'C_SmartHub'):
                raise ValueError('Work bench has conflicting scheduler dependencies')
            if seat not in seats:
                seats.append(seat)
    job.find('Properties').set('guidSmartObjectType', work_template)
    outgoing = E.SubElement(hub, 'Links')
    edges = job.find('EntityLinks')
    if edges is None:
        edges = E.SubElement(job, 'EntityLinks')
    waiting = []
    for seat in seats:
        identity = str(guid_value(seat.get('EntityGuid')))
        if not any(r.get('EntityGuid') == identity for r in rows):
            E.SubElement(rows, 'C_SmartHub', EntityGuid=identity, IgnoreDeadEnds='false', StupidHub='false')
        # The source interval remains solely on actor -> work. Seats are shared
        # all day, so another actor's clock cannot close this resource.
        link = copy.deepcopy(incoming[0])
        link.set('TargetGuid', identity)
        link.set('PositioningDelegate', '0')
        params = link.find('Parameters')
        params.set('BehaviorName', 'use')
        params.set('BehaviorOverride', 'false')
        params.set('AllowedGenders', '0')
        params.set('TimeOfDayStart', '0')
        params.set('TimeOfDayEnd', '1440')
        outgoing.append(link)
        E.SubElement(edges, 'Link', Name='_,use', TargetId=seat.get('EntityId'), TargetGuid=seat.get('EntityGuid'))
        waiting.append((job.get('EntityGuid'), seat.get('EntityGuid'), '_,use'))
    for link in incoming:
        params = link.find('Parameters')
        params.set('BehaviorName', ACTIVITY)
        params.set('BehaviorOverride', 'true')
        params.set('AllowedGenders', '2')
    return job, waiting, dict(person=person, job='native_seated_embroidery', source_behavior=entry['behavior'],
        source_area=entry['area'], source_seats=entry['seated_work']['seats'],
        target_seats=[dict(name=e.get('Name'), guid=e.get('EntityGuid'), position=e.get('Pos')) for e in seats],
        interval=[entry['start_minute'], entry['end_minute']], pending=[], runtime_verified=False)
