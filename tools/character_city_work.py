"""Source town-walking destinations as native, interruptible KCD2 activities.

This converts the walking phase, not the source bench/shop/weather controller.
Authored destinations form a shared resource pool; each NPC retains its source
clock. KCD2 owns pathfinding, arrival, waiting and occupancy at each point.
"""
import copy
import hashlib
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from campaign_entity_links import guid_value, native_guid
from character_person import resolve_link_targets, unique, world_entity
from upgrade_map import read

SOURCE = ('final/sa_city.xml', 'CityWalk')
TABLE = 'Libs/Tables/ai/smartEntity/SmartEntity__so_citywalk_point.xml'
PRUNED = {'parent', 'inventory', 'look', 'startTest'}


def supports(entry):
    behavior = entry['behavior']
    return (behavior['tree_file'].replace('\\', '/').lower(), behavior['tree_name']) == SOURCE


def resolve(entry, archive):
    """Match CityWalk's one-hop point query; look targets are not destinations."""
    area = E.Element('Entity', entry['area'])
    links = E.SubElement(area, 'EntityLinks')
    for link in entry['target_links']:
        if 'cityWalk' in link.get('Name', '').split(','):
            E.SubElement(links, 'Link', link)
    start_link = unique(links, 'source city-walk start link')
    entities = resolve_link_targets(archive, area,
        list(E.fromstring(read(archive, 'objects_mission0.xml'))), {})
    start = unique((e for e in entities if e.get('EntityId') == start_link.get('TargetId')),
                   'source city-walk start point')
    if start.get('EntityClass') != 'TagPoint':
        raise ValueError('Source city-walk start must be a TagPoint')
    # Resolve only the walking query's edges. Other branches are recorded, not
    # mistaken for destinations or pulled in as dependencies of this phase.
    query = E.Element('Entity', start.attrib)
    edges = E.SubElement(query, 'EntityLinks')
    skipped = []
    for link in start.findall('EntityLinks/Link'):
        if PRUNED.intersection(link.get('Name', '').split(',')):
            skipped.append(dict(link.attrib))
        else:
            edges.append(copy.deepcopy(link))
    entities = resolve_link_targets(archive, query, entities, {})
    by_id = {e.get('EntityId'): e for e in entities}
    points = {start.get('EntityId'): start}
    for edge in edges:
        child = by_id[edge.get('TargetId')]
        if child.get('EntityClass') == 'TagPoint':
            points[child.get('EntityId')] = child
        else:
            skipped.append(dict(edge.attrib, EntityClass=child.get('EntityClass')))
    result = []
    identities = set()
    for point in points.values():
        identity = int(point.get('EntityGuid', '0'), 16)
        if not identity or identity in identities:
            raise ValueError('Missing or duplicate source city-walk point GUID')
        identities.add(identity)
        pose = dict(world_entity(archive, point, entities).attrib)
        pose.setdefault('Rotate', '1,0,0,0')
        pose.pop('Scale', None)
        result.append(pose)
    if len(result) < 2:
        raise ValueError('Source city-walk pool needs at least two authored destinations')
    return dict(entry, arrival=result[0], city_work=dict(points=result, excluded_links=skipped))


def native_contract(target):
    """Use a shipped unrestricted activity, including its leaf registration."""
    target = Path(target)
    with zipfile.ZipFile(target/'Data/Tables.pak') as archive:
        template = E.fromstring(read(archive, TABLE)).find('.//SmartEntityTemplate')
    behavior = template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='use']")
    if behavior is None or behavior.get('InitialState') != 'Enabled':
        raise ValueError('Missing enabled native city-walk activity')
    resource = template.find("Resources/Resource[@Name='" + behavior.get('Resource', '') + "']")
    if resource is None or resource.get('MaxInstances') != '1':
        raise ValueError('Native city-walk destination no longer has exclusive occupancy')
    tree = behavior.find('TreeLocation')
    with zipfile.ZipFile(target/'Data/Scripts.pak') as archive:
        program = E.fromstring(read(archive, 'AI/' + tree.get('FileName'))).find(
            "BehaviorTree[@name='" + tree.get('TreeName') + "']/Root")
    if (program is None or program.find(".//ExactMove[@destinationSpecification='$__object.id']") is None
            or program.find(".//EntityContextElement[@context='activity_cityWalk_standing']") is None
            or program.find('.//Wait') is None):
        raise ValueError('Native city-walk movement/lifecycle contract changed')
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as archive:
        mission = E.fromstring(read(archive, 'objects_mission0.xml'))
        rows = E.fromstring(read(archive, 'tables/ai/scheduler.xml')).find('Schedulers')
    points = {str(guid_value(e.get('EntityGuid'))): e for e in mission
              if e.get('EntityClass') == 'DetailMovementSmartObject'
              and e.find('Properties') is not None
              and e.find('Properties').get('guidSmartObjectType') == template.get('DatabaseId')}
    by_guid = {r.get('EntityGuid'): r for r in rows}
    for row in rows:
        for link in row.findall('Links/S_ActivityLink'):
            p = link.find('Parameters')
            if (link.get('TargetGuid') not in points or link.get('PositioningDelegate') != '0'
                    or p is None or p.get('BehaviorName') != 'use'
                    or p.get('BehaviorOverride') != 'false'
                    or p.get('TimeOfDayStart') != '0' or p.get('TimeOfDayEnd') != '1440'
                    or any(k in p.attrib for k in ('RequiredRole', 'ProvidedRole', 'LinkTag', 'RequiredContext'))):
                continue
            terminal = by_guid.get(link.get('TargetGuid'))
            point = points[link.get('TargetGuid')]
            if terminal is None or len(terminal) or point.findall('EntityLinks/Link'):
                continue
            return copy.deepcopy(point.find('Properties')), copy.deepcopy(link), copy.deepcopy(terminal)
    raise ValueError('Missing unrestricted native city-walk scheduler contract')


def bind(mission, scheduler, person, entry, target):
    """Replace one owned arrival leaf with a pool of native work destinations."""
    props, activity, terminal = native_contract(target)
    job = unique((e for e in mission if e.get('Name') ==
        'gm_schedule_' + person + '_' + entry['arrival']['EntityId']), 'city-walk arrival')
    rows = scheduler.find('Schedulers')
    hub_id = str(guid_value(job.get('EntityGuid')))
    hub = unique((r for r in rows if r.get('EntityGuid') == hub_id), 'city-walk scheduler hub')
    if len(hub):
        raise ValueError('City-walk arrival already has scheduler dependencies')
    incoming = [l for r in rows for l in r.findall('Links/S_ActivityLink') if l.get('TargetGuid') == hub_id]
    if not incoming or any(l.find('Parameters').get('BehaviorName') != 'use' for l in incoming):
        raise ValueError('City-walk pool requires an importer-owned arrival activity')
    # The hub dispatches; only leaves execute a behavior. Retain the actor's
    # interval on the incoming edge and on each alternative for midnight wraps.
    job.set('EntityClass', 'SchedulerHub')
    job.remove(job.find('Properties'))
    E.SubElement(job, 'Properties', bSaved_by_game='0')
    hub.set('Position', job.get('Pos'))
    for link in incoming:
        link.find('Parameters').attrib.pop('BehaviorName')
    links = E.SubElement(hub, 'Links')
    waiting = []
    destinations = []
    for pose in entry['city_work']['points']:
        # Shared destination identity provides one occupancy reservation even
        # when several people or areas reference the same authored point.
        guid = native_guid(int.from_bytes(hashlib.sha256(
            ('work/citywalk/' + pose['EntityGuid'].lower()).encode()).digest()[:8], 'little'))
        name = 'gm_citywalk_' + pose['EntityGuid'].lower()
        point = next((e for e in mission if e.get('EntityGuid') == guid), None)
        if point is None:
            point = E.SubElement(mission, 'Entity', Name=name, EntityGuid=guid,
                EntityId=str(max(int(e.get('EntityId', '0')) for e in mission)+1),
                EntityClass='DetailMovementSmartObject', Pos=pose['Pos'], Rotate=pose['Rotate'])
            point.append(copy.deepcopy(props))
        elif (point.get('Name') != name or point.get('EntityClass') != 'DetailMovementSmartObject'
              or point.get('Pos') != pose['Pos'] or point.get('Rotate') != pose['Rotate']
              or E.tostring(point.find('Properties')) != E.tostring(props)):
            raise ValueError('Conflicting native city-walk destination: ' + pose['EntityGuid'])
        point_id = str(guid_value(guid))
        registered = [r for r in rows if r.get('EntityGuid') == point_id]
        if not registered:
            leaf = copy.deepcopy(terminal)
            leaf.set('EntityGuid', point_id)
            leaf.attrib.pop('Position', None)
            rows.append(leaf)
        elif len(registered) != 1 or len(registered[0]):
            raise ValueError('City-walk destination has conflicting scheduler dependencies')
        for source_link in incoming:
            link = copy.deepcopy(activity)
            link.set('TargetGuid', point_id)
            for field in ('TimeOfDayStart', 'TimeOfDayEnd'):
                link.find('Parameters').set(field, source_link.find('Parameters').get(field))
            if not any(E.tostring(old) == E.tostring(link) for old in links):
                links.append(link)
        E.SubElement(job.find('EntityLinks') if job.find('EntityLinks') is not None
                     else E.SubElement(job, 'EntityLinks'), 'Link',
                     Name='_,use', TargetId=point.get('EntityId'), TargetGuid=guid)
        waiting.append((job.get('EntityGuid'), guid, '_,use'))
        destinations.append(dict(source=pose, target_guid=guid))
    return job, waiting, dict(person=person, job='native_city_walk', destinations=destinations,
        source_behavior=entry['behavior'], source_area=entry['area'],
        interval=[entry['start_minute'], entry['end_minute']],
        excluded_links=entry['city_work']['excluded_links'],
        pending=['bench visits', 'shop browsing', 'weather shelter', 'source look-target selection'],
        policy='Native scheduler selects authored walking destinations; native use owns movement and waiting',
        runtime_verified=False)
