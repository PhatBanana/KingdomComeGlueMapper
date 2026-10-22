"""One native hammer-repair position per authored housework fence.

This is a bounded housework phase, not the full source phase controller. Shared
fence identity retains exclusive occupancy; no NPC names or coordinates select it.
"""
import copy
import hashlib
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from campaign_entity_links import guid_value, native_guid, append_links
from campaign_sources import RetailSourceReader
from character_person import resolve_link_targets, unique, world_entity
from character_station_work import unquote
from cooking_pots import rotate
from entity_visuals import quaternion_product
from upgrade_map import read, xml

SOURCE = ('final/sa_home.xml', 'housework')
SOURCE_TEMPLATE = '136155cc-80ad-4e2b-a2c3-ae115d86f042'
FAMILY = 'GenU_repairFenceHammer'
TABLE = 'Libs/Tables/ai/smartEntity/SmartEntity__so_fence.xml'


def supports(entry):
    b = entry['behavior']
    return (b['tree_file'].replace('\\', '/').lower(), b['tree_name']) == SOURCE


def selection_contract(blob):
    root = E.fromstring(blob).find("BehaviorTree[@name='repair_home_fence']/Root")
    search = unique([] if root is None else root.findall('.//GraphSearch'), 'housework fence query')
    attrs = {k: unquote(v) for k, v in search.attrib.items()}
    reserve = root.find('.//ReserveBehavior')
    call = root.find('.//CallBehavior')
    if (any(attrs.get(k) != v for k, v in dict(Origin='__area.id', depth='1',
            EdgePruning='parent', includeOrigin='false', AllowedEdges='', SubGraph='').items())
            or [c.tag for c in search] != ['CategoryFilter', 'HasBehaviorFilter', 'Nodalyzer']
            or unquote(search[0].get('categories', '')) != 'Fence'
            or unquote(search[1].get('BehaviorList', '')) != 'repairFence'
            or unquote(search[1].get('FilterChoice', '')) != 'Requestable'
            or reserve is None or unquote(reserve.get('reserveFrom', '')) != 'fence'
            or unquote(reserve.get('behaviorName', '')) != 'repairFence'
            or call is None or unquote(call.get('Target', '')) != 'fence'
            or unquote(call.get('BehaviorName', '')) != 'repairFence'):
        raise ValueError('Source fence selection/reservation contract changed')


def placement(point, helper):
    """Native generated helper is at its origin; retain the source contact pose."""
    vector = lambda value: tuple(map(float, value.split(',')))
    q = vector(point.get('Rotate', '1,0,0,0'))
    scale = vector(point.get('Scale', '1,1,1'))
    offset = rotate(q, tuple(a*b for a, b in zip(vector(helper.get('pos')), scale)))
    result = dict(point.attrib)
    result['Pos'] = ','.join(format(a+b, '.9g') for a, b in zip(vector(point.get('Pos')), offset))
    result['Rotate'] = ','.join(format(x, '.9g') for x in quaternion_product(q, vector(helper.get('rot'))))
    result.pop('Scale', None)
    return result


def resolve(entry, archive, source, reader):
    blobs = reader(source, {'fence': ('Scripts.pak', 'Libs/AI/final/so_fence.xml'),
                            'helpers': ('GameData.pak', 'Libs/SmartObjects.xml')})
    selection_contract(blobs['fence']['data'])
    helpers = E.fromstring(blobs['helpers']['data'])
    area = E.Element('Entity', entry['area'])
    links = E.SubElement(area, 'EntityLinks')
    for link in entry['target_links']:
        if 'parent' not in link.get('Name', '').split(','):
            E.SubElement(links, 'Link', link)
    entities = resolve_link_targets(archive, area, list(E.fromstring(read(archive, 'objects_mission0.xml'))), {})
    by_id = {e.get('EntityId'): e for e in entities}
    points = {}
    for link in links:
        point = by_id[link.get('TargetId')]
        props = point.find('Properties')
        if props is None or 'Fence' not in props.get('sWH_AI_EntityCategory', '').split(','):
            continue
        if (point.get('EntityClass') != 'SmartObjectHolder'
                or props.get('guidSmartObjectType', '').lower() != SOURCE_TEMPLATE):
            raise ValueError('Unsupported source fence object')
        family = props.get('soclasses_SmartObjectHelpers')
        positions = [h for h in helpers.iter('Helper') if h.get('className') == family
                     and "Animation('RepairFenceHammer','')" in h.get('description', '')]
        if not positions:
            raise ValueError('Source fence has no hammer-repair helper')
        pose = placement(world_entity(archive, point, entities), positions[0])
        pose['source_helper'] = positions[0].get('name')
        pose['remaining_helpers'] = [h.get('name') for h in positions[1:]]
        points[point.get('EntityGuid')] = pose
    return list(points.values())


def native_contract(target):
    target = Path(target)
    with zipfile.ZipFile(target/'Data/Tables.pak') as z:
        template = E.fromstring(read(z, TABLE)).find('.//SmartEntityTemplate')
    use = template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='use']")
    if use is None or use.get('MaxInstances') != '1' or use.get('InitialState') != 'Enabled':
        raise ValueError('Native fence lost exclusive use')
    location = use.find('TreeLocation')
    with zipfile.ZipFile(target/'Data/Scripts.pak') as z:
        root = E.fromstring(read(z, 'AI/'+location.get('FileName'))).find(
            "BehaviorTree[@name='"+location.get('TreeName')+"']/Root")
    seq = None if root is None else root.find('Behavior/Sequence')
    if (seq is None or [c.tag for c in seq] != ['UnstanceAction', 'Wait']
            or seq[0].get('unstance') != 'repairFenceHammer' or seq[0].get('locationObject') != '$__object.id'
            or seq[1].get('duration') != "'15s'" or seq[1].get('timeType') != 'GameTime'):
        raise ValueError('Native fence activity contract changed')
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as z:
        mission = E.fromstring(read(z, 'objects_mission0.xml'))
        rows = E.fromstring(read(z, 'tables/ai/scheduler.xml')).find('Schedulers')
        collections = E.fromstring(read(z, 'smartobjecthelpersetanimations.xml'))
    collection = unique((c for c in collections if c.get('HelperSetName') == FAMILY), 'native fence animations')
    from seating_animations import collection_hash
    collection_hash(collection)
    transforms = list(collection.iter('HelperTransformLocal'))
    if not transforms or any(t.attrib != dict(Rotation='1,0,0,0', Position='0,0,0') for t in transforms):
        raise ValueError('Native fence helper no longer uses the object origin')
    points = {str(guid_value(e.get('EntityGuid'))): e for e in mission
        if e.get('EntityClass') == 'SmartObjectHolder' and e.find('Properties') is not None
        and e.find('Properties').get('guidSmartObjectType') == template.get('DatabaseId')
        and e.find('Properties').get('soclass_SmartObjectHelpers') == FAMILY}
    for link in rows.findall('.//S_ActivityLink'):
        point = points.get(link.get('TargetGuid'))
        p = link.find('Parameters')
        if point is None or p is None or link.get('PositioningDelegate') != '0':
            continue
        if any(p.get(k) != v for k, v in dict(BehaviorName='use', BehaviorOverride='false',
                AllowedGenders='1', ProvidedRole='use', TimeOfDayStart='0', TimeOfDayEnd='1440').items()):
            continue
        if any(k in p.attrib for k in ('RequiredRole', 'LinkTag', 'RequiredContext')):
            continue
        terminal = unique((r for r in rows if r.get('EntityGuid') == link.get('TargetGuid')), 'native fence leaf')
        edges = point.findall('EntityLinks/Link')
        if (terminal.tag == 'C_SmartHub' and terminal.find('Links') is None and len(edges) == 1
                and edges[0].get('Name') == '+Soil[use,2]' and edges[0].get('TargetGuid') == point.get('EntityGuid')
                and terminal.find("PostSearchData/SmartHubPostSearchData/SchedulerEffect/EffectSoil[@Role='use'][@SoilRate='2.000000']") is not None):
            return copy.deepcopy(point.find('Properties')), copy.deepcopy(link), copy.deepcopy(terminal)
    raise ValueError('Missing native fence scheduler contract')


def bind(mission, scheduler, person, entry, points, target):
    from character_schedule_world import ARRIVAL_TEMPLATE
    props, activity, terminal = native_contract(target)
    actor = unique((e for e in mission if e.get('Name') == person), 'fence worker')
    job = unique((e for e in mission if e.get('Name') == 'gm_schedule_'+person+'_'+entry['arrival']['EntityId']), 'fence arrival')
    expected = native_guid(int.from_bytes(hashlib.sha256(('schedule-arrival/'+actor.get('EntityGuid')+'/'+entry['arrival']['EntityGuid']).encode()).digest()[:8], 'little'))
    rows = scheduler.find('Schedulers'); identity = str(guid_value(job.get('EntityGuid')))
    hub = unique((r for r in rows if r.get('EntityGuid') == identity), 'fence arrival hub')
    uses = [(r, l) for r in rows for l in r.findall('Links/S_ActivityLink') if l.get('TargetGuid') == identity]
    if (not points or actor.get('EntityClass') != 'NPC' or job.get('EntityGuid') != expected
            or job.get('EntityClass') != 'SmartObjectHolder' or job.find('Properties') is None
            or job.find('Properties').get('guidSmartObjectType') != ARRIVAL_TEMPLATE
            or job.findall('EntityLinks/Link')
            or hub.tag != 'C_SmartHub' or len(hub) or not uses
            or any(r.get('EntityGuid') != str(guid_value(actor.get('EntityGuid')))
                   or l.find('Parameters').get('BehaviorName') != 'use' for r, l in uses)):
        raise ValueError('Cannot replace non-owned fence-work arrival')
    waiting = []; destinations = []
    for pose in points:
        guid = native_guid(int.from_bytes(hashlib.sha256(('work/fence/'+pose['EntityGuid'].lower()).encode()).digest()[:8], 'little'))
        name = 'gm_schedule_fence_'+pose['EntityGuid'].lower()
        matches = [e for e in mission if e.get('EntityGuid') == guid]
        if matches:
            point = unique(matches, 'shared fence')
            edges = point.findall('EntityLinks/Link')
            if (point.get('Name') != name or point.get('EntityClass') != 'SmartObjectHolder'
                    or point.get('Pos') != pose['Pos'] or point.get('Rotate') != pose['Rotate']
                    or E.tostring(point.find('Properties')) != E.tostring(props)
                    or len(edges) != 1 or edges[0].get('Name') != '+Soil[use,2]'
                    or edges[0].get('TargetGuid') != guid or edges[0].get('TargetId') != point.get('EntityId')):
                raise ValueError('Conflicting shared repair fence')
        else:
            point = E.SubElement(mission, 'Entity', Name=name, EntityClass='SmartObjectHolder', EntityGuid=guid,
                EntityId=str(max(int(e.get('EntityId', '0')) for e in mission)+1), Pos=pose['Pos'], Rotate=pose['Rotate'])
            point.append(copy.deepcopy(props))
            E.SubElement(E.SubElement(point, 'EntityLinks'), 'Link', Name='+Soil[use,2]', TargetId=point.get('EntityId'), TargetGuid=guid)
        leaf_id = str(guid_value(guid)); leaf = copy.deepcopy(terminal); leaf.set('EntityGuid', leaf_id)
        leaf.attrib.pop('Position', None)
        existing = [r for r in rows if r.get('EntityGuid') == leaf_id]
        from character_city_benches import signature
        if existing and (len(existing) != 1 or signature(existing[0]) != signature(leaf)):
            raise ValueError('Conflicting fence scheduler resource')
        if not existing: rows.append(leaf)
        waiting.append((guid, guid, '+Soil[use,2]'))
        destinations.append(point)
    job.set('EntityClass', 'SchedulerHub'); job.remove(job.find('Properties'))
    E.SubElement(job, 'Properties', bSaved_by_game='0'); hub.set('Position', job.get('Pos'))
    links = E.SubElement(hub, 'Links')
    edges = job.find('EntityLinks')
    if edges is None: edges = E.SubElement(job, 'EntityLinks')
    for _, incoming in uses: incoming.find('Parameters').attrib.pop('BehaviorName')
    for point in destinations:
        for _, incoming in uses:
            link = copy.deepcopy(activity); link.set('TargetGuid', str(guid_value(point.get('EntityGuid'))))
            for key in ('TimeOfDayStart', 'TimeOfDayEnd'):
                link.find('Parameters').set(key, incoming.find('Parameters').get(key))
            links.append(link)
        E.SubElement(edges, 'Link', Name='_,use', TargetId=point.get('EntityId'), TargetGuid=point.get('EntityGuid'))
        waiting.append((job.get('EntityGuid'), point.get('EntityGuid'), '_,use'))
    # The incoming edge now dispatches through a hub, not a behavior.
    for link in actor.findall('EntityLinks/Link'):
        if link.get('TargetGuid') == job.get('EntityGuid') and link.get('Name') == '_,use': link.set('Name', '_')
    return job, waiting


def upgrade(files, schedules, archive, target):
    """Extend only owned male housework arrivals; existing live pools stay intact."""
    from character_schedule_world import ARRIVAL_TEMPLATE
    from character_work_capabilities import housework_phases
    mission = E.fromstring(files['objects_mission0.xml']); scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
    waiting = E.fromstring(files['waitinglinks.xml']); links = []; reports = []
    source = Path(archive.filename).parents[3]
    with RetailSourceReader(source) as reader:
        tree = E.fromstring(reader(source, {'home': ('Scripts.pak', 'Libs/AI/final/sa_home.xml')})['home']['data']).find("BehaviorTree[@name='housework']")
        for person, entries in schedules.items():
            actor = next((e for e in mission if e.get('Name') == person), None)
            if actor is None or actor.get('EntityClass') != 'NPC': continue
            phases = housework_phases(tree, actor.get('EntityClass'))
            if 'repair_home_fence' not in phases: continue
            for entry in entries:
                if not supports(entry): continue
                name = 'gm_schedule_'+person+'_'+entry['arrival']['EntityId']
                job = next((e for e in mission if e.get('Name') == name), None)
                if job is None or job.find('Properties') is None or job.find('Properties').get('guidSmartObjectType') != ARRIVAL_TEMPLATE: continue
                hub_id = str(guid_value(job.get('EntityGuid')))
                actual = {(int(l.find('Parameters').get('TimeOfDayStart')), int(l.find('Parameters').get('TimeOfDayEnd')))
                    for l in scheduler.findall('.//S_ActivityLink') if l.get('TargetGuid') == hub_id}
                clock = {(e['start_minute'], e['end_minute']) for e in entries if supports(e) and e['arrival']['EntityId'] == entry['arrival']['EntityId']}
                from character_sleep_work import waking_work_clock
                clock = waking_work_clock(mission, scheduler, actor, clock)
                if actual != clock: raise ValueError('Fence arrival clock differs from source')
                points = resolve(entry, archive, source, reader)
                if not points: continue
                job, added = bind(mission, scheduler, person, entry, points, target); links.extend(added)
                for record in waiting.findall('.//WaitingLink'):
                    if record.get('TargetId') == job.get('EntityGuid'):
                        for definition in record:
                            if definition.text == '_,use': definition.text = '_'
                reports.append(dict(person=person, job='native_fence_repair', source_behavior=entry['behavior'],
                    source_area=entry['area'], points=points, intervals=sorted(clock), runtime_verified=False,
                    pending=[p for p in phases if p != 'repair_home_fence'] + ['remaining fence helper traversal', 'source housework phase selection', 'unarmed repair variant']))
    return dict(files, **{'objects_mission0.xml': xml(mission), 'tables/ai/scheduler.xml': xml(scheduler),
        'waitinglinks.xml': append_links(xml(waiting), links, allow_untagged=True)}), reports
