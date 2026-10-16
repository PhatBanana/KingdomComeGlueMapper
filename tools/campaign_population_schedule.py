"""Connect converted profile residents to executable native work activities.

Dependency discovery alone does not create a scheduler. Only bind a job after
its placed host AND its complete smart-entity behavior have been emitted.
Never substitute an arrival/idle action for an unresolved work program.
"""
import copy
import hashlib
import xml.etree.ElementTree as E

from campaign_entity_links import append_links, guid_value, native_guid
from character_person_activity import validate_scheduler_targets
from upgrade_map import xml


PREFIX = 'world/registration/'


def behavior_catalog(files):
    result = {}
    for path, blob in files.items():
        if not path.lower().startswith('libs/tables/ai/smartentity/'):
            continue
        if hasattr(blob, 'read_bytes'):
            blob = blob.read_bytes()
        for template in E.fromstring(blob).iter('SmartEntityTemplate'):
            key = template.get('DatabaseId', '').lower()
            if not key or key in result:
                raise ValueError('Missing or duplicate work-template identity: ' + key)
            result[key] = {b.get('Name'): b for b in template.findall('BehaviorTemplates/SmartBehaviorTemplate')}
    return result


def bind(objects, scheduler, actor, activities, registered, catalog, native_activity):
    """Bind one whole daycycle transactionally, preserving quest overrides.

    Caller provides a private XML copy. Validate every destination before any
    mutation, so a missing evening job cannot leave a misleading daytime-only
    schedule. Existing native activities and quest positioning delegates stay.
    """
    rows = scheduler.find('Schedulers')
    if rows is None:
        raise ValueError('Missing native scheduler container')
    entities = {e.get('EntityGuid'): e for e in objects}
    actor_guid = actor.get('EntityGuid')
    prepared = []
    for entry in activities:
        start, end = entry['start_minute'], entry['end_minute']
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= 1440:
            raise ValueError('Invalid source schedule interval')
        source_guid = native_guid(int(entry['area']['EntityGuid'], 16))
        target_guid = registered.get('entities', {}).get(source_guid.lower())
        if target_guid not in entities:
            raise ValueError('Work host has not been placed: ' + source_guid)
        host = entities[target_guid]
        props = host.find('Properties')
        template = '' if props is None else (props.get('guidSmartAreaTemplate') or props.get('guidSmartObjectType', ''))
        name_key = 'so_behaviour_tag_name' if entry['target_kind'] == 'quest_controller' else 'sa_behaviour_tag_name'
        name = entry['behavior'][name_key]
        behavior = catalog.get(template.lower(), {}).get(name)
        if behavior is None or behavior.find('TreeLocation') is None:
            raise ValueError('Complete native work behavior has not been emitted: ' + name)
        if behavior.get('InitialState') != 'Enabled':
            raise ValueError('Ordinary work requires authored enable/disable lifecycle: ' + name)
        activity = copy.deepcopy(native_activity)
        activity.set('TargetGuid', str(guid_value(target_guid)))
        activity.set('PositioningDelegate', '0')
        parameters = activity.find('Parameters')
        if parameters is None:
            raise ValueError('Missing native activity parameters')
        parameters.set('BehaviorName', name)
        parameters.set('TimeOfDayStart', str(start))
        parameters.set('TimeOfDayEnd', str(end))
        # Native templates can include a time variation; source daycycle times
        # are exact. Do not randomly shift a resident's authored transitions.
        parameters.set('TimeVariation', '0')
        prepared.append((host, name, activity))
    if not prepared:
        raise ValueError('No resolved ordinary work activities')
    actor_rows = [r for r in rows if r.get('EntityGuid') == str(guid_value(actor_guid))]
    if len(actor_rows) > 1:
        raise ValueError('Duplicate resident scheduler')
    row = actor_rows[0] if actor_rows else E.SubElement(rows, 'C_SmartHub',
        EntityGuid=str(guid_value(actor_guid)), IgnoreDeadEnds='false', StupidHub='false')
    links = row.find('Links')
    if links is None:
        links = E.SubElement(row, 'Links')
    authoring = actor.find('EntityLinks')
    if authoring is None:
        authoring = E.SubElement(actor, 'EntityLinks')
    additions, removed = [], []
    # Retire only the baseline created by register_person_world. Leaving it
    # alongside priority-zero work gives the scheduler two competing choices.
    # The deterministic GUID verifies ownership independently of display names.
    idle_guid = native_guid(int.from_bytes(hashlib.sha256(
        ('person-idle/' + str(guid_value(actor_guid))).encode()).digest()[:8], 'little'))
    idle = entities.get(idle_guid)
    if idle is not None and idle.get('EntityClass') == 'TagPoint':
        delegates = idle.findall("EntityLinks/Link[@Name='^delegate']")
        if len(delegates) == 1:
            target = str(guid_value(delegates[0].get('TargetGuid')))
            for old in list(links):
                p = old.find('Parameters')
                if (old.get('PositioningDelegate') == str(guid_value(idle_guid))
                        and old.get('TargetGuid') == target and p is not None
                        and p.get('BehaviorName') == 'schedulerWait' and p.get('Priority') == '0'):
                    links.remove(old)
                    removed.append((actor_guid, idle_guid, '_,schedulerWait'))
            if removed:
                for edge in list(authoring):
                    if edge.get('TargetGuid') == idle_guid and edge.get('Name') == '_,schedulerWait':
                        authoring.remove(edge)
    for host, name, activity in prepared:
        # Repeated references from different quest closures must not create
        # competing copies of the very same activity.
        if not any(E.tostring(old) == E.tostring(activity) for old in links):
            links.append(activity)
        host_guid = host.get('EntityGuid')
        label = '_,' + name
        if not any(l.get('TargetGuid') == host_guid and l.get('Name') == label for l in authoring):
            E.SubElement(authoring, 'Link', Name=label, TargetGuid=host_guid, TargetId=host.get('EntityId'))
        additions.append((actor_guid, host_guid, label))
        if not any(r.get('EntityGuid') == str(guid_value(host_guid)) for r in rows):
            E.SubElement(rows, 'C_SmartHub', EntityGuid=str(guid_value(host_guid)),
                         IgnoreDeadEnds='false', StupidHub='false')
    return additions, removed


def remove_edges(data, edges):
    if not data or not edges:
        return data
    root = E.fromstring(data)
    waiting = root.find('WaitingLinks')
    if waiting is not None:
        for record in list(waiting):
            for definition in list(record):
                if (record.get('SourceId'), record.get('TargetId'), definition.text) in edges:
                    record.remove(definition)
            if not len(record):
                waiting.remove(record)
    return xml(root)


def assemble(models, registration, registered, resources, native_activity):
    result = dict(registration)
    objects = E.fromstring(result[PREFIX + 'objects_mission0.xml'])
    scheduler = E.fromstring(result.get(PREFIX + 'tables/ai/scheduler.xml',
        b'<database name="barbora"><Schedulers version="1"/></database>'))
    catalog = behavior_catalog(resources)
    report = dict(converted=[], unresolved=[], runtime_verified=False)
    seen = set()
    for model in models:
        for population in model.get('profile_work_dependencies', []):
            for record in population['actors']:
                identity = record['actor']['entity_guid']
                if identity in seen:
                    continue
                seen.add(identity)
                site = dict(actor=identity, name=record['actor']['name'], profiles=record['actor']['profiles'])
                try:
                    plan = record.get('schedule')
                    if not plan or plan.get('pending') or record.get('unresolved'):
                        raise ValueError('Source daycycle still has unresolved activities')
                    guid = registered.get('entities', {}).get(native_guid(int(identity, 16)).lower())
                    working_objects, working_scheduler = copy.deepcopy(objects), copy.deepcopy(scheduler)
                    matches = [e for e in working_objects if e.get('EntityGuid') == guid]
                    if len(matches) != 1:
                        raise ValueError('Resident placement is missing or ambiguous')
                    edges, removed = bind(working_objects, working_scheduler, matches[0], plan['resolved'],
                                 registered, catalog, native_activity)
                    validate_scheduler_targets(working_scheduler)
                    waiting = append_links(remove_edges(result.get(PREFIX + 'waitinglinks.xml'), removed), edges)
                except (ValueError, KeyError) as error:
                    report['unresolved'].append(dict(**site, reason=str(error)))
                    continue
                objects, scheduler = working_objects, working_scheduler
                result[PREFIX + 'waitinglinks.xml'] = waiting
                report['converted'].append(dict(**site, intervals=len(plan['resolved'])))
    result[PREFIX + 'objects_mission0.xml'] = xml(objects)
    result[PREFIX + 'tables/ai/scheduler.xml'] = xml(scheduler)
    return result, report
