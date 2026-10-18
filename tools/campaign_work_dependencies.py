"""Follow placed job dependencies independently of conversion success.

A work-area template is not its tools, helpers or route. Follow authored
edges iteratively, retaining cycles for the final world-link assembly. Actors
and quest controllers are references at this boundary, not permission to
activate another population or recursively import an unrelated quest.
"""
from collections import deque
from campaign_entity_links import native_guid


def discover(world, roots, *, actor_roots=()):
    actor_roots = {guid.lower() for guid in actor_roots}
    by_guid = {}
    for key, entity in world['entities'].items():
        guid = entity['attributes'].get('EntityGuid')
        if guid:
            by_guid.setdefault(guid.lower(), []).append(key)
    outgoing = {}
    for edge in world['links']:
        outgoing.setdefault(edge['from'], []).append(edge)
    by_id = {}
    for key, entity in world['entities'].items():
        eid = entity['attributes'].get('EntityId')
        if eid:
            by_id.setdefault(eid, []).append(key)
    pending, queue = [], deque()
    for guid in sorted(set(roots)):
        matches = by_guid.get(guid.lower(), [])
        if len(matches) != 1:
            pending.append(dict(source=guid, reason='Missing or ambiguous work dependency root'))
        else:
            queue.append(matches[0])
    seen, entities, edges = set(), [], []
    while queue:
        key = queue.popleft()
        if key in seen:
            continue
        seen.add(key)
        source = world['entities'].get(key)
        if source is None:
            pending.append(dict(source=key, reason='Missing source work graph endpoint'))
            continue
        attrs = source['attributes']
        try:
            identity = native_guid(int(attrs.get('EntityGuid', ''), 16))
        except ValueError:
            pending.append(dict(source=key, reason='Invalid source work dependency GUID'))
            continue
        entities.append(dict(source=key, guid=identity, attributes=attrs,
                             entity=source['entity']))
        if attrs.get('EntityClass') == 'QuestObject' or (
                attrs.get('EntityClass') in ('NPC', 'NPC_Female') and
                attrs.get('EntityGuid', '').lower() not in actor_roots):
            continue
        authored = []
        has_authored_links = False
        for container in source['entity']['children']:
            if container['op'] != 'EntityLinks':
                continue
            has_authored_links = True
            for link in container['children']:
                attrs = link['attributes']
                guid, eid = attrs.get('TargetGuid'), attrs.get('TargetId')
                candidates = by_guid.get(guid.lower(), []) if guid not in (None, '', '0') else by_id.get(eid, [])
                if len(candidates) != 1:
                    pending.append(dict(source=key, source_link=attrs,
                        reason='Missing or ambiguous work graph endpoint', candidates=candidates))
                    continue
                dest = world['entities'][candidates[0]]['attributes']
                if eid not in (None, '', '0') and dest.get('EntityId') != eid:
                    pending.append(dict(source=key, source_link=attrs, reason='Work graph GUID and entity ID disagree'))
                    continue
                authored.append(dict(**{'from':key, 'to':candidates[0]}, source_link=attrs))
        # AST links are authoritative when present; callers may also supply a
        # previously resolved graph (including records without an AST link list).
        for edge in authored if has_authored_links else outgoing.get(key, []):
            edges.append(edge)
            queue.append(edge['to'])
    return dict(entities=entities, edges=edges, unresolved=pending)


def for_models(models, world):
    result = {}
    for model in models:
        roots = set()
        actors = set()
        for population in model.get('profile_work_dependencies', []):
            for resident in population['actors']:
                # Homes, owned containers and other explicit person links are
                # dependencies even when an activity has no direct Work edge.
                # Follow only these selected actors, not every NPC encountered
                # through their shared work area.
                if resident.get('source_links'):
                    actors.add(resident['actor']['entity_guid'])
                for activity in (resident.get('schedule') or {}).get('resolved', []):
                    roots.add(activity['area']['EntityGuid'])
        result[model['quest']] = discover(world, roots | actors, actor_roots=actors)
    return result


def merge_world(world, complete_entities, closures):
    """Expose discovered placements and their edges to normal link assembly."""
    entities = dict(world['entities'])
    edges = list(world['links'])
    seen = {(e['from'], e['to'], tuple(sorted(e['source_link'].items()))) for e in edges}
    unresolved = list(world.get('unresolved', []))
    for closure in closures.values():
        for entry in closure['entities']:
            entities[entry['source']] = complete_entities[entry['source']]
        for edge in closure['edges']:
            key = (edge['from'], edge['to'], tuple(sorted(edge['source_link'].items())))
            if key not in seen:
                edges.append(edge)
                seen.add(key)
        unresolved.extend(closure['unresolved'])
    return dict(world, entities=entities, links=edges, unresolved=unresolved)


def templates(closures, entity_class, property_name):
    bindings = {}
    for owner, closure in closures.items():
        for entry in closure['entities']:
            if entry['attributes'].get('EntityClass') != entity_class:
                continue
            props = [c for c in entry['entity']['children'] if c['op'] == 'Properties']
            if len(props) != 1 or not props[0]['attributes'].get(property_name):
                continue
            identity = owner + '|' + props[0]['attributes'][property_name].lower()
            if identity not in bindings.setdefault(entry['guid'], []):
                bindings[entry['guid']].append(identity)
    return bindings


def import_all(closures, importer):
    report = []
    for owner, closure in closures.items():
        for entry in closure['entities']:
            site = dict(quest=owner, kind='resident_work_graph', source=entry['source'])
            target = importer.ensure('entities', entry['guid'], site)
            report.append(dict(**site, guid=entry['guid'], target=target))
    return report
