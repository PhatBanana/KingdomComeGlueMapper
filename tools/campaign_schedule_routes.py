"""Bind source controller jobs to native actor activities, transactionally.

The containing source branches own requests. With a ScheduleAdapter, assembly
also registers the request consumer, worker wrappers and native release hook.
Cold routes stay disabled until the original source branch requests them.
"""
import copy
import xml.etree.ElementTree as E
from pathlib import Path

from campaign_behavior_schedule import connect, validate_compiled
from campaign_entity_links import guid_value
from campaign_quest_graph import identifier
from campaign_schedule_requests import dependencies
from campaign_sources import key
from quest_import import behavior_path
from campaign_schedule_lifecycle import route_name


def compile_program(model, actor_bindings, objects, scheduler, controller_guid,
                    template, activity_template, native_policies, namespace,
                    catalog, native, resources, registered=None, importer=None,
                    profile_streaming=None, faction_adapter=None):
    """Compile requests and their consumer as one controller transaction.

    No result is returned if any registered controller entry or scheduled
    callback was withheld. Callers must package the returned world, scheduler,
    template, waiting links and files together. Engine lifecycle/priority
    semantics still require runtime acceptance; this is not a setup shortcut.
    """
    from campaign_behavior import convert_behaviors
    from campaign_schedule_lifecycle import ScheduleAdapter, validate_generated
    prepared = plan(model, actor_bindings)
    if not prepared['leases']:
        raise ValueError('Controller contains no bound schedule requests')
    adapter = ScheduleAdapter(prepared, controller_guid, namespace)
    files, bridges, report = convert_behaviors([model], namespace, catalog,
        registered, importer, profile_streaming, schedule_adapter=adapter, faction_adapter=faction_adapter)
    emitted = {(r['document'], r['tree']) for r in report['trees']
               if r['owner'] == model['quest'] and r['native_emitted']}
    definition = model.get('controller_registration') or {}
    entries = definition.get('entry_points', [])
    if not entries or not any(e['kind'] != 'behavior_callback' for e in entries):
        raise ValueError('Source controller has no registered entry program')
    missing = [(key(behavior_path(e['file'])), e['tree']) for e in entries
               if (key(behavior_path(e['file'])), e['tree']) not in emitted]
    if missing:
        raise ValueError('Controller entry programs remain unconverted: ' + repr(missing))
    combined = dict(resources)
    # Dependencies may have been materialized while compiling the source tree.
    if importer is not None:
        combined.update(importer.files)
    for path, data in {**files, **bridges}.items():
        old = combined.get(path)
        if isinstance(old, Path):
            old = old.read_bytes()
        if old is not None and old != data:
            raise ValueError('Conflicting compiled controller resource: ' + path)
        combined[path] = data
    result = assemble(prepared, objects, scheduler, controller_guid, template,
        activity_template, report, combined, native_policies, namespace,
        lifecycle=adapter, native=native)
    validate_generated(adapter, result[-1]['files'], catalog)
    result[-1]['compiler'] = report
    result[-1]['bridge_files'] = sorted(bridges)
    return result


def plan(model, actor_bindings, trees=None):
    """Resolve each expression in its original tree scope to an imported actor.

    actor_bindings keys are (document, tree, source_expression). In particular,
    a callback's this.id must not resolve to its controller's this.id. An
    external world binder, not a name/coordinate heuristic, supplies the GUID.
    """
    selected = set(trees) if trees is not None else None
    callbacks = {(key(behavior_path(e['file'])), e['tree']) for e in
                 (model.get('controller_registration') or {}).get('entry_points', [])
                 if e.get('kind') == 'behavior_callback'}
    if selected is None:
        # Imported libraries can contain other quests' entire programs. They
        # are not this controller's entry points or actor scope.
        own = 'libs/ai/quests/' + model['quest'].lower() + '.xml'
        selected = {(own, t) for t in model['behavior_documents'].get(own, {}).get('trees', {})} | callbacks
        if not selected:
            raise ValueError('Controller has no source trees to bind')
    seen, leases = set(), {}
    for document, payload in model['behavior_documents'].items():
        for tree, body in payload['trees'].items():
            if selected is not None and (document, tree) not in selected:
                continue
            seen.add((document, tree))
            for record in dependencies(model, body['root']):
                if 'error' in record:
                    raise ValueError('Unresolved schedule request: ' + record['error'])
                scope = (document, tree, record['actor'])
                actor = actor_bindings.get(scope)
                if actor is None:
                    raise ValueError('Schedule actor requires a scoped world binding: ' + repr(scope))
                # Normalise native compact GUIDs before comparing identities.
                actor = str(guid_value(actor))
                identity = (actor, record['handle'])
                lease = leases.setdefault(identity, dict(actor=actor, handle=record['handle'], sites=[], policy=None))
                lease['sites'].append(dict(document=document, tree=tree, path=record['path'],
                    ancestors=copy.deepcopy(record['ancestors']), add=record['add'], expression=record['actor'],
                    operation=record['operation'], attributes=copy.deepcopy(record['attributes'])))
                if record['add']:
                    if ((document, tree) in callbacks and
                            record['source'].lstrip('$') == 'this.id'):
                        raise ValueError('Callback this.id is the actor, not the owning controller')
                    policy = {k: copy.deepcopy(record[k]) for k in
                              ('behavior', 'source', 'priority', 'immediate', 'once', 'callback')}
                    if lease['policy'] is not None and lease['policy'] != policy:
                        raise ValueError('Schedule handle changes policy; replacement conversion required: ' + record['handle'])
                    lease['policy'] = policy
    if seen != selected:
        raise ValueError('Requested controller tree was not imported')
    for lease in leases.values():
        if lease['policy'] is None:
            raise ValueError('Schedule removal has no resolved addition: ' + lease['handle'])
    return dict(owner=model['quest'], leases=sorted(leases.values(), key=lambda x: (x['actor'], x['handle'])),
                publication_ready=False, runtime_validated=False)


def assemble(plan, objects, scheduler, controller_guid, template, activity_template,
             compiler_report, behavior_files, native_policies, namespace, *, lifecycle=None, native=None):
    """Return isolated candidate world/registry copies; never mutate inputs.

    native_policies is keyed by (actor numeric GUID, handle), with priority,
    urgency and nonempty evidence supplied by the policy adapter. Source
    immediate is NOT automatically translated to native Instant urgency.
    The existing controller owns every callback, so __object and its persistent
    variables keep their identity. Each actor/handle gets independent native
    availability even when several requests share a source callback.
    """
    identifier(namespace)
    world, schedule, host_template = map(copy.deepcopy, (objects, scheduler, template))
    entities = {}
    for entity in world:
        if entity.get('EntityGuid'):
            key = str(guid_value(entity.get('EntityGuid')))
            if key in entities:
                raise ValueError('Ambiguous exported entity GUID: ' + key)
            entities[key] = entity
    host = entities.get(str(guid_value(controller_guid)))
    if host is None or host.get('EntityClass') != 'SmartObjectHolder':
        raise ValueError('Schedule controller must be an imported SmartObjectHolder')
    props = host.find('Properties')
    if (props is None or not host_template.get('DatabaseId') or
            props.get('guidSmartObjectType') != host_template.get('DatabaseId')):
        raise ValueError('Schedule controller/template identity mismatch')
    behaviors = host_template.find('BehaviorTemplates')
    if behaviors is None:
        raise ValueError('Schedule controller has no converted callbacks')
    records = {}
    for r in compiler_report['trees']:
        identity = (r['owner'], r['document'], r['tree'])
        if identity in records:
            raise ValueError('Ambiguous compiled callback identity')
        records[identity] = r
    additions, result = [], []
    for lease in plan['leases']:
        policy = lease['policy']
        identity = (lease['actor'], lease['handle'])
        actor = entities.get(lease['actor'])
        if actor is None or actor is host:
            raise ValueError('Schedule actor is missing or resolves to the controller')
        mapped = native_policies.get(identity)
        if (not mapped or set(mapped) != {'priority', 'urgency', 'evidence'} or
                not isinstance(mapped['evidence'], str) or not mapped['evidence'].strip()):
            raise ValueError('Native schedule priority/urgency needs an evidenced mapping: ' + lease['handle'])
        callback = policy['callback']
        record = records.get((plan['owner'], callback['document'], callback['tree']))
        if not record or not record.get('native_emitted') or record.get('unresolved') or record.get('blocked_includes'):
            raise ValueError('Scheduled callback is not fully converted: ' + policy['behavior'])
        candidates = [b for b in behaviors if b.get('Name') == policy['behavior']]
        if len(candidates) != 1:
            raise ValueError('Scheduled callback has no unique native registration: ' + policy['behavior'])
        original = candidates[0]
        locations = original.findall('TreeLocation')
        expected = (compiler_report['namespace'].lower() + '/' + plan['owner'].lower() + '/' +
                    callback['document'].removeprefix('libs/ai/'))
        if (len(locations) != 1 or locations[0].get('FileName') != expected or
                locations[0].get('TreeName') != callback['tree']):
            raise ValueError('Native registration points to a different callback')
        blob = behavior_files.get('AI/' + expected)
        if isinstance(blob, Path):
            blob = blob.read_bytes()
        if blob is None or len([t for t in E.fromstring(blob).findall('BehaviorTree')
                                if t.get('name') == callback['tree'] and t.find('Root') is not None]) != 1:
            raise ValueError('Converted callback file/tree is missing or ambiguous')
        name = route_name(plan['owner'], controller_guid, *identity, namespace)
        if any(b.get('Name') == name for b in behaviors):
            raise ValueError('Schedule lease already exists; rebuild from the pre-assembly candidate')
        registration = copy.deepcopy(original)
        registration.set('Name', name)
        registration.set('InitialState', 'Disabled')
        # Do not add PreventsMonsterLod or change the controller brain. Original
        # callback inboxes, instance limits and source behavior remain intact.
        behaviors.append(registration)
        anchor = connect(world, additions, actor, host, name, mapped['priority'], mapped['urgency'], name,
                         schedule, activity_template)
        result.append(dict(lease=copy.deepcopy(lease), behavior=name, actor_guid=actor.get('EntityGuid'),
            controller_guid=controller_guid, anchor_guid=anchor.get('EntityGuid'), native_policy=dict(mapped)))
    validate_compiled(world, schedule, additions)
    if lifecycle is not None:
        if (native is None or lifecycle.plan != plan or lifecycle.namespace != namespace
                or guid_value(lifecycle.controller) != guid_value(controller_guid)):
            raise ValueError('Schedule lifecycle does not match the assembled plan')
        files, host_template, evidence = lifecycle.install(behavior_files, host_template, native)
        return world, schedule, host_template, additions, dict(routes=result, files=files,
            lifecycle=evidence, publication_ready=False, ready_for_controller_integration=True,
            runtime_validated=False, remaining=['complete source controller and package validation',
                                                'retail execution and save/load'])
    return world, schedule, host_template, additions, dict(routes=result, publication_ready=False,
        runtime_validated=False, remaining=['source request delivery and replacement/once policy',
            'worker stop acknowledgement before cleanup and reactivation', 'retail execution and save/load'])
