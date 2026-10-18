"""Resolve conversations through source soul/role/topic relationships.

The caller selects campaign actors. This module discovers their source branches
and validates the entire connected graph, including unnamed entry points.
"""
from collections import defaultdict
import copy
import re
import xml.etree.ElementTree as ET

from campaign_dialogue import resolve, unique_index, index_tables
from campaign_quest_graph import identifier, xml


def branch_catalog(branches, participants, memberships, roles, metaroles, soul_ids):
    """Inventory every production branch owned by selected source actors.

    Preserve shared event roles and branch kinds instead of turning reactions
    into ordinary conversation choices. A caller must provide an adapter for
    each selected kind; source test branches are recorded separately.
    """
    requested = {s.lower() for s in soul_ids}
    role_index = unique_index(roles, 'role_id')
    meta_index = unique_index(metaroles, 'metarole_id')
    owned = defaultdict(set)
    for row in memberships:
        if row['soul_id'].lower() in requested:
            owned[row['soul_id'].lower()].add(row['role_id'])
    if requested - owned.keys():
        raise ValueError('Missing source dialogue memberships: ' + ', '.join(sorted(requested - owned.keys())))
    by_topic = defaultdict(set)
    for row in participants:
        by_topic[row['topic_id']].add(row['role_id'])
    result = dict(branches=[], excluded_test_branches=[])
    for topic, branch in sorted(unique_index(branches, 'start_topic').items()):
        actors = {}
        for soul in sorted(requested):
            matches = owned[soul] & by_topic[topic]
            if matches:
                records = []
                for rid in sorted(matches):
                    if rid not in role_index or role_index[rid]['metarole_id'] not in meta_index:
                        raise ValueError('Unresolved source dialogue role: ' + rid)
                    role = role_index[rid]
                    records.append(dict(role, metarole_name=meta_index[role['metarole_id']]['metarole_name']))
                actors[soul] = records
        if actors:
            record = dict(source=dict(branch), actors=actors)
            key = 'excluded_test_branches' if branch.get('is_test', '').lower() == 'true' else 'branches'
            result[key].append(record)
    return result


def quest_dependencies(tables, catalog, quests):
    """Follow effects and expanded predicates in every connected actor branch.

    Selecting an actor must retain later-quest gates, not remove a conversation
    because its owner was absent from the opening quest selection.
    """
    from campaign_dialogue_conditions import expand_functions, QUEST, OBJECTIVE
    by_id = unique_index(quests, 'quest_id')
    known = {q['quest_name'] for q in quests}
    functions = {r['function_name']: r['expression'] for r in tables.get('dialogue_functions', [])}
    indexes = index_tables(tables)
    result = {}
    calls = '|'.join(map(re.escape, (*QUEST, *OBJECTIVE)))
    pattern = re.compile(r"'(?:[^'\\]|\\.)*'|\b(?:" + calls + r")\s*\(\s*'([^']+)'")
    for branch in catalog['branches']:
        topic = branch['source']['start_topic']
        model = resolve(tables, start_topic=topic, indexes=indexes)
        names = set()
        for record in model['topics'].values():
            for sequence in record['sequences']:
                for effect in sequence['effects']:
                    identity = effect['quest_id']
                    if identity not in by_id:
                        raise ValueError('Missing dialogue effect quest: ' + identity)
                    names.add(by_id[identity]['quest_name'])
                for field in ('entry_condition', 'npc_entry_condition'):
                    # Conditions belong to topic membership, not the shared
                    # sequence row. Keep the runtime branch eligibility.
                    expression = expand_functions(sequence['entry'].get(field, ''), functions)
                    names.update(m.group(1) for m in pattern.finditer(expression) if m.group(1))
        missing = names - known
        if missing:
            raise ValueError('Missing dialogue predicate quests: ' + ', '.join(sorted(missing)))
        result[topic] = sorted(names)
    return result


def actor_branches(closure, memberships, soul_ids):
    """Restrict an already quest-scoped closure using source soul/role links.

    Names and dialogue labels are not selectors. Connected topics remain part
    of each selected branch's normal dialogue traversal.
    """
    requested = {s.lower() for s in soul_ids}
    owned = defaultdict(set)
    for row in memberships:
        owned[row['soul_id'].lower()].add(row['role_id'])
    if requested - owned.keys():
        raise ValueError('Missing source dialogue memberships: ' + ', '.join(sorted(requested - owned.keys())))
    roles = set().union(*(owned[s] for s in requested))
    return [b for b in closure['branches']
            if roles & {p['role_id'] for p in b['participants']}]


def required_actor_souls(models, memberships, roles, metaroles, eligible_souls=None):
    """Resolve every NPC participant, including silent presentation roles.

    Shared roles need an explicit source population resolver; choosing their
    first member would silently bind the wrong actor.
    """
    from campaign_dialogue import referenced_roles
    role_index = unique_index(roles, 'role_id')
    meta_index = unique_index(metaroles, 'metarole_id')
    members = defaultdict(set)
    for row in memberships: members[row['role_id']].add(row['soul_id'])
    result = {}
    for role in sorted(set().union(*(referenced_roles(m) for m in models))):
        record = role_index[role]
        if meta_index[record['metarole_id']]['metarole_name'] != 'NPC': continue
        candidates = members[role]
        if eligible_souls is not None: candidates = candidates & set(eligible_souls)
        if len(candidates) != 1:
            raise ValueError('Missing or ambiguous dialogue actor for role ' + role)
        result[role] = next(iter(candidates))
    return result


def discover(tables, soul_ids):
    roles = unique_index(tables['role'], 'role_id')
    metaroles = unique_index(tables['metarole'], 'metarole_id')
    memberships = defaultdict(set)
    for row in tables['soul2role']:
        memberships[row['soul_id'].lower()].add(row['role_id'])
    participants = defaultdict(list)
    for row in tables['topictorole']:
        participants[row['topic_id']].append(row)
    branches = unique_index(tables['v_branch'], 'start_topic')
    indexes = index_tables(tables)
    people, conversations = {}, {}
    for soul in sorted(set(s.lower() for s in soul_ids)):
        if soul not in memberships:
            raise ValueError('Missing source dialogue roles for soul: ' + soul)
        owned = memberships[soul]
        for rid in owned:
            if rid not in roles or roles[rid]['metarole_id'] not in metaroles:
                raise ValueError('Unresolved source dialogue role: ' + rid)
        selected = []
        for topic in sorted(branches):
            matches = sorted({r['role_id'] for r in participants[topic]} & owned)
            if not matches:
                continue
            selected.append(dict(start_topic=topic, role_ids=matches))
            if topic not in conversations:
                model = resolve(tables, start_topic=topic, indexes=indexes)
                model['roles'] = roles
                conversations[topic] = model
        people[soul] = dict(roles=[dict(roles[r], metarole_name=metaroles[roles[r]['metarole_id']]['metarole_name'])
                                  for r in sorted(owned)], branches=selected)
    return people, conversations


def role_bindings(people, conversations):
    """Return only source memberships needed by the supplied emitted branches.

An actor may own many bark/service roles. Never assign a role merely because
another actor has it or because their displayed names happen to match.
"""
    result = {}
    for soul, person in people.items():
        needed = set()
        for branch in person['branches']:
            if branch['start_topic'] in conversations:
                needed.update(branch['role_ids'])
        result[soul] = [r for r in person['roles'] if r['role_id'] in needed]
    return result


def register_roles(resources, bindings, soul_names, native_roles, namespace):
    """Register selected source roles and Storm assignments for imported actors.

Namespaced roles isolate imported dialogues from native campaigns. Returned
role-name mappings must also be applied to their dialogue models before emit.
"""
    identifier(namespace)
    files = dict(resources)
    path = 'Libs/Storm/roles/' + namespace + '.xml'
    table_path = 'Libs/Tables/rpg/role__' + namespace + '.xml'
    if path in files or table_path in files:
        raise ValueError('Dialogue role namespace already registered: ' + namespace)
    existing = {r['role_name'] for r in native_roles}
    role_table = ET.Element('database', name='barbora')
    rows = ET.SubElement(role_table, 'roles', version='1')
    storm_rules = ET.Element('storm')
    rules = ET.SubElement(storm_rules, 'rules')
    mapping, definitions = {}, {}
    for soul, roles in sorted(bindings.items()):
        if not roles:
            continue
        if soul not in soul_names:
            raise ValueError('Dialogue actor is not registered: ' + soul)
        rule = ET.SubElement(rules, 'rule', name=namespace + '_' + soul.replace('-', ''))
        ET.SubElement(ET.SubElement(rule, 'selectors'), 'hasName', name=soul_names[soul])
        operations = ET.SubElement(rule, 'operations')
        for role in roles:
            # Additional bark metaroles need corresponding native event adapters.
            if role['metarole_name'] != 'NPC':
                raise ValueError('Unconverted dialogue metarole: ' + role['metarole_name'])
            name = namespace + '_' + role['role_id']
            identifier(name)
            definition = dict(role_name=name, metarole_name='NPC')
            if name in existing:
                raise ValueError('Native role name collision: ' + name)
            if name in definitions and definitions[name] != definition:
                raise ValueError('Conflicting imported role: ' + name)
            if name not in definitions:
                ET.SubElement(rows, 'role', definition)
                definitions[name] = definition
            original = role['role_name']
            if original in mapping and mapping[original] != name:
                raise ValueError('Ambiguous source role name: ' + original)
            mapping[original] = name
            ET.SubElement(operations, 'addRole', name=name)
    storm = ET.fromstring(files['Libs/Storm/storm.xml'])
    task = storm.find("tasks/task[@name='roles']")
    if task is None:
        raise ValueError('Missing native roles task')
    ET.SubElement(task, 'source', path='roles/' + namespace + '.xml')
    files['Libs/Storm/storm.xml'] = xml(storm)
    files[path], files[table_path] = xml(storm_rules), xml(role_table)
    return files, mapping


def remap_roles(model, mapping):
    from campaign_script_import import translate
    result = copy.deepcopy(model)
    for role in result['roles'].values():
        role['role_name'] = mapping.get(role['role_name'], role['role_name'])
    for topic in result['topics'].values():
        for record in topic['sequences']:
            source = record['source']
            if source.get('script'):
                source['script'] = translate(source['script'], mapping)
    return result
