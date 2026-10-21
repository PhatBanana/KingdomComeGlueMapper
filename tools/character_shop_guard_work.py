"""Source shop guardWork pools using native, exclusively occupied leaning posts.

No actor identity, faction override, forced animation or initialization hook is
needed. This adapter covers source back-only leaning posts; other post kinds
must be converted separately rather than being silently replaced.
"""
import copy
import hashlib
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from campaign_entity_links import guid_value, native_guid
from character_person import resolve_link_targets, unique, world_entity
from character_station_work import unquote
from lean_alignment import native_placement
from upgrade_map import read

SOURCE = ('final/sa_shop2.xml', 'guard')
TABLE = 'Libs/Tables/ai/smartEntity/SmartEntity__leaningSpot_back.xml'
SOURCE_TEMPLATE = '43a88f22-a70d-6e0c-1976-208a72b7be85'


def supports(entry):
    b = entry['behavior']
    return (b['tree_file'].replace('\\', '/').lower(), b['tree_name']) == SOURCE


def resolve(entry, archive, source, reader, target):
    if source is None or reader is None or target is None:
        raise ValueError('Shop guard conversion requires both games and source behavior')
    blob = reader(source, {'work': ('Scripts.pak', 'Libs/AI/'+SOURCE[0])})['work']['data']
    root = E.fromstring(blob).find("BehaviorTree[@name='guard']/Root")
    search = unique([] if root is None else root.findall('.//GraphSearch'), 'source shop guard search')
    attrs = {k: unquote(v) for k, v in search.attrib.items()}
    expected = dict(Origin='__area.id', depth='1', selection='true', includeOrigin='false',
                    EdgePruning='parent,inventory', AllowedEdges='', SubGraph='', AllowSubtraph='false')
    children = [{k: unquote(v) for k, v in f.attrib.items()} for f in search]
    call = root.find('.//CallBehavior')
    if (any(attrs.get(k) != v for k, v in expected.items())
            or [f.tag for f in search] != ['LinkTagFilter', 'HasBehaviorFilter', 'Nodalyzer']
            or children[0].get('tag') != 'guardWork' or children[0].get('prune') != 'true'
            or children[1].get('BehaviorList') != 'use' or children[1].get('Source') != 'Child'
            or children[1].get('prune') != 'true' or children[2].get('Child') != 'workPlace'
            or call is None or unquote(call.get('Target', '')) != 'workPlace'
            or unquote(call.get('BehaviorName', '')) != 'use'):
        raise ValueError('Unsupported source shop guard selection contract')
    area = E.Element('Entity', entry['area'])
    links = E.SubElement(area, 'EntityLinks')
    for link in entry['target_links']:
        tags = set(link.get('Name', '').split(','))
        if 'guardWork' in tags and not tags.intersection({'parent', 'inventory'}):
            E.SubElement(links, 'Link', link)
    entities = resolve_link_targets(archive, area, list(E.fromstring(read(archive, 'objects_mission0.xml'))), {})
    by_id = {e.get('EntityId'): e for e in entities}
    points = {}
    for link in links:
        entity = by_id[link.get('TargetId')]
        props = entity.find('Properties')
        script = None if props is None else props.find('Script')
        flags = dict(part.split(':', 1) for part in (script.get('Misc', '') if script is not None else '').split('|') if ':' in part)
        if (entity.get('EntityClass') != 'SmartObjectHolder' or props is None
                or props.get('guidSmartObjectType', '').lower() != SOURCE_TEMPLATE
                or props.get('soclasses_SmartObjectHelpers') != 'LeaningSpot'
                or flags.get('leanBack') != 'true' or flags.get('leanLeft') != 'false'
                or flags.get('leanRight') != 'false' or entity.findall('EntityLinks/Link')):
            raise ValueError('Unsupported source shop guard post: '+entity.get('Name', ''))
        pose = world_entity(archive, entity, entities)
        # Preserve the animation contact, not just the editor object's origin.
        placed = native_placement(pose, source, target, 'leaning_back')
        points[entity.get('EntityId')] = dict(placed.attrib)
    if not points:
        raise ValueError('Source shop guard has no authored work posts')
    return dict(entry, arrival=next(iter(points.values())), shop_guard_work=dict(points=list(points.values())))


def native_contract(target):
    target = Path(target)
    with zipfile.ZipFile(target/'Data/Tables.pak') as z:
        template = E.fromstring(read(z, TABLE)).find('.//SmartEntityTemplate')
    use = template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='use']")
    if use is None or use.get('InitialState') != 'Enabled' or use.get('MaxInstances') != '1':
        raise ValueError('Native shop guard post lost exclusive occupancy')
    tree = use.find('TreeLocation')
    with zipfile.ZipFile(target/'Data/Scripts.pak') as z:
        root = E.fromstring(read(z, 'AI/'+tree.get('FileName'))).find("BehaviorTree[@name='"+tree.get('TreeName')+"']/Root")
    if (root is None or root.find(".//UnstanceAction[@unstance='LeaningBack'][@locationObject='$__object.id']") is None
            or root.find(".//EntityContextElement[@context='speech_readyForSwitchDialog']") is None
            or root.find('.//MoveParamsDecorator') is None):
        raise ValueError('Native shop guard movement/lifecycle contract changed')
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as z:
        mission = E.fromstring(read(z, 'objects_mission0.xml'))
        rows = E.fromstring(read(z, 'tables/ai/scheduler.xml')).find('Schedulers')
    points = {str(guid_value(e.get('EntityGuid'))): e for e in mission
              if e.get('EntityClass') == 'DetailMovementSmartObject' and e.find('Properties') is not None
              and e.find('Properties').get('guidSmartObjectType') == template.get('DatabaseId')
              and e.find('Properties').get('soclass_SmartObjectHelpers') == 'leaning_back'
              and not e.findall('EntityLinks/Link')}
    by_guid = {}
    for row in rows:
        by_guid.setdefault(row.get('EntityGuid'), []).append(row)
    for link in rows.findall('.//S_ActivityLink'):
        if link.get('TargetGuid') not in points:
            continue
        p = link.find('Parameters')
        terminals = by_guid.get(link.get('TargetGuid'), [])
        if (link.get('PositioningDelegate') == '0'
                and p is not None and p.get('BehaviorName') == 'use' and p.get('BehaviorOverride') == 'false'
                and p.get('AllowedGenders') == '0' and p.get('TimeOfDayStart') == '0' and p.get('TimeOfDayEnd') == '1440'
                and not any(k in p.attrib for k in ('RequiredRole', 'ProvidedRole', 'LinkTag', 'RequiredContext'))
                and len(terminals) == 1 and terminals[0].tag == 'C_SmartHub' and not len(terminals[0])):
            return copy.deepcopy(points[link.get('TargetGuid')].find('Properties')), copy.deepcopy(link)
    raise ValueError('Missing native shop guard scheduler contract')


def bind(mission, scheduler, person, entry, target):
    from character_schedule_world import ARRIVAL_TEMPLATE
    props, activity = native_contract(target)
    job = unique((e for e in mission if e.get('Name') ==
        'gm_schedule_'+person+'_'+entry['arrival']['EntityId']), 'shop guard arrival')
    if job.find('Properties') is None or job.find('Properties').get('guidSmartObjectType') != ARRIVAL_TEMPLATE:
        raise ValueError('Shop guard requires an importer-owned arrival')
    rows = scheduler.find('Schedulers')
    hub_id = str(guid_value(job.get('EntityGuid')))
    hub = unique((r for r in rows if r.get('EntityGuid') == hub_id), 'shop guard hub')
    incoming = [l for l in rows.findall('.//S_ActivityLink') if l.get('TargetGuid') == hub_id]
    if len(hub) or not incoming or any(l.find('Parameters').get('BehaviorName') != 'use' for l in incoming):
        raise ValueError('Shop guard arrival has conflicting scheduler dependencies')
    destinations = []
    for pose in entry['shop_guard_work']['points']:
        guid = native_guid(int.from_bytes(hashlib.sha256(('work/shop-guard/'+pose['EntityGuid'].lower()).encode()).digest()[:8], 'little'))
        name = 'gm_schedule_shop_guard_'+pose['EntityGuid'].lower()
        matches = [e for e in mission if e.get('EntityGuid') == guid]
        if matches:
            point = unique(matches, 'shared shop guard post')
            if (point.get('Name') != name or point.get('EntityClass') != 'DetailMovementSmartObject'
                    or point.get('Pos') != pose['Pos'] or point.get('Rotate') != pose.get('Rotate', '1,0,0,0')
                    or E.tostring(point.find('Properties')) != E.tostring(props) or point.findall('EntityLinks/Link')):
                raise ValueError('Conflicting shared shop guard post')
        else:
            point = E.SubElement(mission, 'Entity', Name=name, EntityGuid=guid,
                EntityId=str(max(int(e.get('EntityId', '0')) for e in mission)+1),
                EntityClass='DetailMovementSmartObject', Pos=pose['Pos'], Rotate=pose.get('Rotate', '1,0,0,0'))
            point.append(copy.deepcopy(props))
        identity = str(guid_value(guid))
        terminals = [r for r in rows if r.get('EntityGuid') == identity]
        if terminals and (len(terminals) != 1 or terminals[0].tag != 'C_SmartHub' or len(terminals[0])):
            raise ValueError('Shared shop guard post has conflicting scheduler dependencies')
        if not terminals:
            E.SubElement(rows, 'C_SmartHub', EntityGuid=identity, IgnoreDeadEnds='false', StupidHub='false')
        destinations.append(point)
    if not destinations:
        raise ValueError('Empty shop guard post pool')
    job.set('EntityClass', 'SchedulerHub')
    job.remove(job.find('Properties')); E.SubElement(job, 'Properties', bSaved_by_game='0')
    hub.set('Position', job.get('Pos'))
    for link in incoming:
        link.find('Parameters').attrib.pop('BehaviorName')
    outgoing = E.SubElement(hub, 'Links')
    edges = E.SubElement(job, 'EntityLinks') if job.find('EntityLinks') is None else job.find('EntityLinks')
    waiting = []
    for point in destinations:
        link = copy.deepcopy(activity)
        link.set('TargetGuid', str(guid_value(point.get('EntityGuid'))))
        # Work hours belong to each actor. Shared posts remain usable all day.
        outgoing.append(link)
        E.SubElement(edges, 'Link', Name='_,use', TargetId=point.get('EntityId'), TargetGuid=point.get('EntityGuid'))
        waiting.append((job.get('EntityGuid'), point.get('EntityGuid'), '_,use'))
    return job, waiting, dict(person=person, job='native_shop_guard_leaning', source_behavior=entry['behavior'],
        source_area=entry['area'], posts=[dict(e.attrib) for e in destinations],
        interval=[entry['start_minute'], entry['end_minute']], pending=[], runtime_verified=False)
