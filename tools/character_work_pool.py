"""Add native work choices without replacing an actor's existing routine.

The clock is inherited from a verified importer-owned source arrival. Resource
leaves are shared, and deterministic identities make upgrades repeatable. This
does not claim to reproduce a source controller's phase ordering.
"""
import copy
import hashlib
import xml.etree.ElementTree as E

from campaign_entity_links import guid_value, native_guid
from character_city_benches import signature
from character_person import unique


def identity(key):
    return native_guid(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], 'little'))


def source_job(mission, scheduler, person, entry):
    actor = unique((e for e in mission if e.get('Name') == person), 'work-pool actor')
    guid = identity('schedule-arrival/'+actor.get('EntityGuid')+'/'+entry['arrival']['EntityGuid'])
    job = unique((e for e in mission if e.get('Name') ==
        'gm_schedule_'+person+'_'+entry['arrival']['EntityId']), 'work-pool source job')
    if job.get('EntityGuid') != guid or actor.get('EntityClass') not in ('NPC', 'NPC_Female'):
        raise ValueError('Work extension requires an owned source job')
    owner = unique((r for r in scheduler.find('Schedulers') if r.get('EntityGuid') ==
        str(guid_value(actor.get('EntityGuid')))), 'work-pool owner')
    incoming = [l for l in owner.findall('Links/S_ActivityLink') if l.get('TargetGuid') == str(guid_value(guid))]
    if not incoming or any(l.find('Parameters') is None or
        l.find('Parameters').get('Priority') != '0' or
        l.find('Parameters').get('Privileged', 'false') != 'false' or
        any(k in l.find('Parameters').attrib for k in ('RequiredRole', 'RequiredContext', 'LinkTag', 'BuffTag'))
        for l in incoming):
        raise ValueError('Work extension cannot replace quest or conditional activities')
    return actor, owner, incoming


def bind(mission, scheduler, person, entry, phase, resources, activity, *, template=None):
    """Resources are (existing entity, validated native leaf) pairs.

    A template makes the pool a native activity override (e.g. embroidery).
    Otherwise it is a transparent SchedulerHub dispatching to resource leaves.
    Validate the entire proposed graph before mutating either XML document.
    """
    actor, owner, incoming = source_job(mission, scheduler, person, entry)
    if not resources:
        raise ValueError('Empty native work pool')
    if len({e.get('EntityGuid') for e, _ in resources}) != len(resources):
        raise ValueError('Duplicate native work resource')
    rows = scheduler.find('Schedulers')
    guid = identity('work-phase/'+actor.get('EntityGuid')+'/'+entry['arrival']['EntityGuid']+'/'+phase)
    number = str(guid_value(guid))
    name = 'gm_schedule_phase_'+person+'_'+entry['arrival']['EntityId']+'_'+phase
    existing = [e for e in mission if e.get('EntityGuid') == guid or e.get('Name') == name]
    existing_rows = [r for r in rows if r.get('EntityGuid') == number]
    source_edges = [l for l in owner.findall('Links/S_ActivityLink') if l.get('TargetGuid') == number]
    target_class = 'SmartObjectHolder' if template else 'SchedulerHub'
    params = activity.find('Parameters')
    if params is None:
        raise ValueError('Missing native work activity parameters')
    clock = sorted({(int(l.find('Parameters').get('TimeOfDayStart')),
                     int(l.find('Parameters').get('TimeOfDayEnd'))) for l in incoming})
    if any(not 0 <= start < end <= 1440 for start, end in clock):
        raise ValueError('Invalid source work clock')
    planned_in = []
    for start, end in clock:
        edge = copy.deepcopy(activity if template else incoming[0]); edge.set('TargetGuid', number)
        p = edge.find('Parameters')
        if not template:
            for key in ('BehaviorName', 'ProvidedRole', 'BehaviorOverride'):
                p.attrib.pop(key, None)
            p.set('BehaviorOverride', 'false')
        p.set('TimeOfDayStart', str(start)); p.set('TimeOfDayEnd', str(end))
        p.set('HaltOnInvalid', 'true')
        planned_in.append(edge)
    planned_out = []
    pending_leaves = []
    for entity, native_leaf in resources:
        resource_id = str(guid_value(entity.get('EntityGuid')))
        leaf = copy.deepcopy(native_leaf); leaf.set('EntityGuid', resource_id)
        if leaf.tag != 'C_SmartHub' or leaf.find('Links') is not None:
            raise ValueError('Native work resource must be a terminal hub')
        found = [r for r in rows if r.get('EntityGuid') == resource_id]
        if found and (len(found) != 1 or signature(found[0]) != signature(leaf)):
            raise ValueError('Native work resource has conflicting scheduler dependencies')
        if not found: pending_leaves.append(leaf)
        edge = copy.deepcopy(activity); edge.set('TargetGuid', resource_id)
        p = edge.find('Parameters'); p.set('TimeOfDayStart', '0'); p.set('TimeOfDayEnd', '1440')
        if template:
            p.set('BehaviorName', 'use'); p.set('BehaviorOverride', 'false'); p.set('AllowedGenders', '0')
            p.attrib.pop('ProvidedRole', None)
        planned_out.append(edge)
    definition = '_,'+params.get('BehaviorName') if template else '_'
    static_out = '_,use' if template else '_,'+params.get('BehaviorName')
    if existing or existing_rows or source_edges:
        if (len(existing) != 1 or len(existing_rows) != 1 or not source_edges
                or existing[0].get('EntityGuid') != guid or existing[0].get('Name') != name
                or existing[0].get('EntityClass') != target_class
                or existing[0].find('Properties') is None
                or existing[0].find('Properties').get('guidSmartObjectType') != template
                or existing_rows[0].tag != 'C_SmartHub' or [n.tag for n in existing_rows[0]] != ['Links']
                or len(source_edges) != len(planned_in)
                or len(existing_rows[0].find('Links')) != len(planned_out)
                or {signature(l) for l in source_edges} != {signature(l) for l in planned_in}
                or {signature(l) for l in existing_rows[0].findall('Links/S_ActivityLink')} != {signature(l) for l in planned_out}
                or sorted((l.get('Name'), l.get('TargetGuid'), l.get('TargetId')) for l in existing[0].findall('EntityLinks/Link')) !=
                   sorted((static_out, e.get('EntityGuid'), e.get('EntityId')) for e, _ in resources)
                or [(l.get('Name'), l.get('TargetId')) for l in actor.findall('EntityLinks/Link') if l.get('TargetGuid') == guid] !=
                   [(definition, existing[0].get('EntityId'))]):
            raise ValueError('Existing work phase differs from source/native contract; rebuild required')
        if pending_leaves:
            raise ValueError('Existing work phase has missing resource registrations')
        return existing[0], [], clock
    if any(l.get('TargetGuid') == number for r in rows for l in r.findall('Links/S_ActivityLink')):
        raise ValueError('Work phase identity already referenced by another actor')
    next_id = str(max(int(e.get('EntityId', '0')) for e in mission.iter('Entity'))+1)
    pool = E.SubElement(mission, 'Entity', Name=name, EntityGuid=guid, EntityId=next_id,
                        EntityClass=target_class, Pos=entry['arrival']['Pos'])
    E.SubElement(pool, 'Properties', **({'guidSmartObjectType': template} if template else {'bSaved_by_game': '0'}))
    hub = E.SubElement(rows, 'C_SmartHub', EntityGuid=number, IgnoreDeadEnds='false', StupidHub='false')
    if not template: hub.set('Position', pool.get('Pos'))
    E.SubElement(hub, 'Links').extend(planned_out)
    rows.extend(pending_leaves)
    owner.find('Links').extend(planned_in)
    actor_links = actor.find('EntityLinks')
    if actor_links is None: actor_links = E.SubElement(actor, 'EntityLinks')
    E.SubElement(actor_links, 'Link', Name=definition, TargetId=next_id, TargetGuid=guid)
    edges = E.SubElement(pool, 'EntityLinks')
    waiting = [(actor.get('EntityGuid'), guid, definition)]
    for entity, _ in resources:
        E.SubElement(edges, 'Link', Name=static_out, TargetId=entity.get('EntityId'), TargetGuid=entity.get('EntityGuid'))
        waiting.append((guid, entity.get('EntityGuid'), static_out))
    return pool, waiting, clock
