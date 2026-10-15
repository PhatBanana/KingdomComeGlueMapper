"""Export the actor-side schedule required by native EnableBehavior.

EnableBehavior supplies parameters and availability; it does not create a
schedule entry. Authoring links are not executable scheduler records: export
the compiled actor activity and terminal host as well as the scene links.
"""
import re
import copy
import uuid
import xml.etree.ElementTree as E
from campaign_entity_links import native_guid, guid_value


def connect(objects, additions, actor, host, behavior, priority, speed, identity,
            scheduler, activity_template):
    if not re.fullmatch(r'\w+', behavior) or speed not in ('Instant', 'Fast', 'Slow'):
        raise ValueError('Unsupported native behavior schedule')
    if not isinstance(priority, int) or not 0 <= priority <= 255:
        raise ValueError('Unsupported schedule priority')
    rows = scheduler.find('Schedulers')
    if rows is None:
        raise ValueError('Missing compiled scheduler table')
    actor_guid, host_guid = (str(guid_value(e.get('EntityGuid'))) for e in (actor, host))
    actor_rows = [r for r in rows if r.get('EntityGuid') == actor_guid]
    if len(actor_rows) != 1:
        raise ValueError('Actor baseline schedule is missing or ambiguous')
    activity_links = actor_rows[0].find('Links')
    if activity_links is None:
        activity_links = E.SubElement(actor_rows[0], 'Links')
    if any(l.get('TargetGuid') == host_guid and l.find('Parameters').get('BehaviorName') == behavior
           for l in activity_links.findall('S_ActivityLink')):
        raise ValueError('Behavior already has a compiled schedule entry')
    guid = native_guid(uuid.uuid5(uuid.NAMESPACE_URL, identity + '/schedule-anchor').int & ((1 << 64) - 1))
    if any(e.get('EntityGuid') == guid for e in objects):
        raise ValueError('Schedule anchor identity collision: ' + identity)
    anchor = E.SubElement(objects, 'Entity', Name=identity + '_schedule_anchor',
        EntityClass='TagPoint', EntityGuid=guid,
        EntityId=str(max(int(e.get('EntityId', '0')) for e in objects) + 1),
        Pos=actor.get('Pos'))
    E.SubElement(anchor, 'Properties', bSaved_by_game='0')
    for source, target, label in [(actor, anchor, f'_{priority},!{speed},{behavior}'),
                                  (anchor, host, '^delegate')]:
        links = source.find('EntityLinks')
        if links is None:
            links = E.SubElement(source, 'EntityLinks')
        E.SubElement(links, 'Link', Name=label, TargetId=target.get('EntityId'), TargetGuid=target.get('EntityGuid'))
        additions.append((source.get('EntityGuid'), target.get('EntityGuid'), label))
    activity = copy.deepcopy(activity_template)
    activity.set('TargetGuid', host_guid)
    activity.set('PositioningDelegate', str(guid_value(guid)))
    params = activity.find('Parameters')
    if params is None:
        raise ValueError('Missing native activity parameter contract')
    params.set('BehaviorName', behavior)
    params.set('Priority', str(priority))
    params.set('Urgency', speed)
    activity_links.append(activity)
    # KCD2 resolves activity destinations through this table, including leaves.
    if not any(r.get('EntityGuid') == host_guid for r in rows):
        E.SubElement(rows, 'C_SmartHub', EntityGuid=host_guid, IgnoreDeadEnds='false', StupidHub='false')
    return anchor


def source_policy(patch):
    """Keep the authored priority and immediate request in an upgraded schedule."""
    values = patch['values']
    priority = re.search(r'(?:^|,)\s*priority\((\d+)\)', values)
    immediate = re.search(r'(?:^|,)\s*immediate\((true|false)\)', values)
    if not priority or not immediate:
        raise ValueError('Unresolved source daycycle priority/immediate policy')
    return int(priority[1]), 'Instant' if immediate[1] == 'true' else 'Slow'


def validate_compiled(objects, scheduler, additions):
    """Reject authoring-only routes before publishing a package."""
    entities = {e.get('EntityGuid'): e for e in objects}
    for actor, anchor, label in additions:
        match = re.fullmatch(r'_(\d+),!(Instant|Fast|Slow),(\w+)', label)
        if not match:
            continue
        point = entities[anchor]
        delegate = point.find("EntityLinks/Link[@Name='^delegate']")
        if delegate is None or delegate.get('TargetGuid') not in entities:
            raise ValueError('Missing behavior positioning delegate')
        host = delegate.get('TargetGuid')
        row = scheduler.find(f"Schedulers/C_SmartHub[@EntityGuid='{guid_value(actor)}']")
        candidates = [] if row is None else [l for l in row.findall('Links/S_ActivityLink')
            if l.get('TargetGuid') == str(guid_value(host))
            and l.get('PositioningDelegate') == str(guid_value(anchor))
            and l.find('Parameters') is not None
            and all(l.find('Parameters').get(k) == v for k, v in
                    [('Priority', match[1]), ('Urgency', match[2]), ('BehaviorName', match[3])])]
        if len(candidates) != 1:
            raise ValueError('Authoring behavior route has no unique compiled activity: ' + label)
