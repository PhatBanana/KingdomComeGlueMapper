"""Convert the source innkeeper's pub work to a native lean that staffs the shop.

The source Innkeeper (sa_pub_v3) alternates two pub behaviours for the whole
shift: `leaning` at a free Lean spot linked to the pub area, then `resting` at
a free pubTable bench. The native shop is staffed only while the keeper is in
the shop hub, so the converted job is the lean, at the pub's Lean spot on the
keeper's floor nearest the keeper's authored position (the rule the upper-gate
innkeeper port already uses). The resting half is reported, not converted.
Selection is by work contract, never actor or quest identity.
"""
import xml.etree.ElementTree as E

from character_person import resolve_link_targets, unique, world_entity
from upgrade_map import read

SOURCE = ('final/sa_pub_v3.xml', 'Innkeeper')
ROLE = 'innkeeper'


def supports(entry):
    behavior = entry['behavior']
    return (behavior['tree_file'].replace('\\', '/').lower(), behavior['tree_name']) == SOURCE


def lean_side(point):
    script = point.find('Properties/Script')
    flags = dict(pair.split(':', 1) for pair in script.get('Misc', '').split('|') if ':' in pair) if script is not None else {}
    # Source so_leanSpot: an allowed back lean is the only lean and never changes.
    # Only without it are left/right offered, picked at random and changed in a loop.
    if flags.get('leanBack') == 'true': return 'leaning_back'
    side = unique((side for side in ('Left', 'Right') if flags.get('lean' + side) == 'true'),
                  'source lean direction')
    return 'leaning_' + side.lower()


def choose(points, origin):
    """The keeper's floor first, then the closest point: upper floors never win on plan distance."""
    def distance(pose):
        pos = tuple(map(float, pose.get('Pos').split(',')))
        return (abs(pos[2] - origin[2]), sum((a - b) ** 2 for a, b in zip(pos, origin)))
    return min(points, key=lambda pair: distance(pair[1]))


def resolve(entry, archive, person, source, target):
    from lean_alignment import native_placement
    if person is None or source is None or target is None:
        raise ValueError('Innkeeper work requires the keeper and both games')
    area = E.Element('Entity', entry['area'])
    links = E.SubElement(area, 'EntityLinks')
    for link in entry['target_links']:
        if 'Lean' in link.get('Name', '').split(','):
            E.SubElement(links, 'Link', link)
    if not len(links):
        raise ValueError('Source pub has no authored lean point')
    entities = resolve_link_targets(archive, area, list(E.fromstring(read(archive, 'objects_mission0.xml'))), {})
    points = []
    for link in links:
        point = unique((e for e in entities if e.get('EntityId') == link.get('TargetId')), 'source pub lean point')
        props = point.find('Properties')
        if props is None or 'Lean' not in props.get('sWH_AI_EntityCategory', '').split(','):
            raise ValueError('Source pub lean link is not a lean spot')
        points.append((point, world_entity(archive, point, entities)))
    origin = tuple(map(float, person['actor'].get('Pos').split(',')))
    point, pose = choose(points, origin)
    helper = lean_side(point)
    placed = native_placement(pose, source, target, helper)
    arrival = dict(placed.attrib)
    return dict(entry, arrival=arrival, inn_work=dict(helper=helper, source_point=dict(pose.attrib),
        source_alternate_points=[dict(EntityId=p.get('EntityId'), Pos=w.get('Pos')) for p, w in points if p is not point]))


def bind(mission, scheduler, person, entry, target):
    """Turn the arrival holder into the native unrestricted lean smart object."""
    from campaign_entity_links import guid_value
    from character_person_activity import native_lean_activity
    props, activity, _ = native_lean_activity(target, entry['inn_work']['helper'])
    job = unique((e for e in mission if e.get('Name') ==
                  'gm_schedule_' + person + '_' + entry['arrival']['EntityId']), 'innkeeper job')
    job.set('EntityClass', 'DetailMovementSmartObject')
    job.remove(job.find('Properties'))
    job.append(props)
    native = activity.find('Parameters')
    for link in scheduler.findall('.//S_ActivityLink'):
        if link.get('TargetGuid') == str(guid_value(job.get('EntityGuid'))):
            params = link.find('Parameters')
            for key, value in native.attrib.items():
                if key not in ('TimeOfDayStart', 'TimeOfDayEnd'):
                    params.set(key, value)
            link.set('PositioningDelegate', activity.get('PositioningDelegate', '0'))
    return job, dict(person=person, job='native_innkeeper_lean', native_behavior='use',
                     native_helper=entry['inn_work']['helper'], source_lean_point=entry['inn_work']['source_point'],
                     source_alternate_points=entry['inn_work']['source_alternate_points'],
                     pending=[], runtime_verified=False,
                     source_phases_not_converted=['resting at a free pubTable bench, alternating with leaning'],
                     policy='The keeper leans at one source Lean spot while the native shop hub staffs the shop')
