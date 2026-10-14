"""Reconcile source speaker and presentation roles with installed dialogue XML."""
import copy
import xml.etree.ElementTree as ET

from campaign_actor_dialogues import remap_roles
from campaign_dialogue import presentation_command, response_camera_command
from upgrade_map import xml


def upgrade(blob, model):
    root = ET.fromstring(blob)
    native = {}
    for response in root.findall('.//Response'):
        text = response.find('Text')
        if text is not None:
            native.setdefault(text.get('StringName'), []).append(response)
    mapping, authored = {}, []
    for topic in model['topics'].values():
        for sequence in topic['sequences']:
            pending = []
            for line in sequence['lines']:
                if line['source']['sequence_line_type'] == '5':
                    pending.extend(line['commands'])
                elif line.get('response'):
                    source = line['response']
                    matches = native.get(source['string_name'], [])
                    if not matches:
                        raise ValueError('Missing installed response: ' + source['string_name'])
                    roles = {r.get('Role') for r in matches}
                    if len(roles) != 1 or None in roles:
                        raise ValueError('Ambiguous installed speaker: ' + source['string_name'])
                    name = model['roles'][source['role_id']]['role_name']
                    target = roles.pop()
                    if name in mapping and mapping[name] != target:
                        raise ValueError('Conflicting source speaker mapping: ' + name)
                    mapping[name] = target
                    authored.append((source, pending, matches))
                    pending = []
            if pending:
                raise ValueError('Orphaned source presentation commands')
    mapped = remap_roles(model, mapping)
    declared = {r.get('Role') for r in root.findall('.//SelectedSoul')} | set(mapping.values())
    report = dict(speakers=mapping, responses=len(authored), added=[], outside_targeting_scope=[])
    for source, commands, matches in authored:
        converted = []
        camera = response_camera_command(source, commands, mapped,
            in_world=root.find('./Skald/Dialog') is not None)
        if camera is not None:
            converted.append(camera)
        for command in commands:
            # Unsupported semantics remain explicit; never reinterpret command IDs
            # as KCD2 enums (the source and target numbering differs).
            if command['dialogue_command_type'] not in ('2', '4'):
                report['outside_targeting_scope'].append(dict(response=source['string_name'], source=command))
                continue
            node = presentation_command(command, mapped)
            for attr in ('Role', 'LookAtRole'):
                if node.get(attr) and node.get(attr) not in declared:
                    raise ValueError('Presentation role is not registered: ' + node.get(attr))
            converted.append(node)
        for response in matches:
            container = response.find('Commands')
            existing = [] if container is None else [(n.tag, dict(n.attrib)) for n in container]
            # Compare as an ordered multiset so repeated authored commands survive.
            cursor = 0
            for node in converted:
                signature = (node.tag, dict(node.attrib))
                if signature in existing[cursor:]:
                    cursor = existing.index(signature, cursor) + 1
                    continue
                if container is None:
                    container = ET.SubElement(response, 'Commands')
                container.insert(cursor, copy.deepcopy(node))
                existing.insert(cursor, signature)
                cursor += 1
                report['added'].append(dict(response=source['string_name'], command=node.tag, attributes=node.attrib))
    return xml(root), report
