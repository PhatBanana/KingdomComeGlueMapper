"""Resolve conversations through source soul/role/topic relationships.

The caller selects campaign actors. This module discovers their source branches
and validates the entire connected graph, including unnamed entry points.
"""
from collections import defaultdict
import copy
import xml.etree.ElementTree as ET

from campaign_dialogue import resolve, unique_index, index_tables
from campaign_quest_graph import identifier, xml


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
    result = dict(model, roles=copy.deepcopy(model['roles']))
    for role in result['roles'].values():
        role['role_name'] = mapping.get(role['role_name'], role['role_name'])
    return result
