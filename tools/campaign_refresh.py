"""Refresh emitted dialogue endings and objective timers without replacing world bindings.

The source models select policy. Existing imported scene placement, voices,
quest scope and reward wiring are preserved and validated before replacement.
"""
import copy
import xml.etree.ElementTree as ET

from campaign_quest_graph import emit_quest, xml


def dialogue_cameras(blob, model, camera_aliases, role_mapping=None):
    """Refresh source camera commands while retaining converted voices/actions.

    Camera assets must already be registered in an ancestor graph. Other
    presentation commands are left to their respective conversion adapters.
    """
    from campaign_dialogue import presentation_command
    root = ET.fromstring(blob)
    sequences = {s.get('Name'): s for s in root.iter('Sequence')}
    changes = []
    for topic in model['topics'].values():
        for record in topic['sequences']:
            sid = record['source']['sequence_id']
            target = sequences.get('seq_' + sid)
            if target is None:
                raise ValueError('Missing source sequence: ' + sid)
            responses = iter(target.findall('./Elements/Response'))
            pending = []
            for line in record['lines']:
                typ = line['source']['sequence_line_type']
                if typ == '5':
                    pending.extend(c for c in line['commands'] if c['dialogue_command_type'] == '2')
                elif typ == '1':
                    response = next(responses, None)
                    if response is None or response.find('Text').get('StringName') != line['response']['string_name']:
                        raise ValueError('Installed response order differs from source: ' + sid)
                    if not pending:
                        continue
                    commands = response.find('Commands')
                    if commands is None: commands = ET.SubElement(response, 'Commands')
                    for old in list(commands):
                        if old.tag == 'CameraCommand': commands.remove(old)
                    for command in pending:
                        native = presentation_command(command, model)
                        if native.get('CustomCamera') not in camera_aliases:
                            raise ValueError('Unregistered source camera: ' + str(native.get('CustomCamera')))
                        role = native.get('Role')
                        if role_mapping is not None:
                            if role not in role_mapping: raise ValueError('Unregistered camera role: ' + role)
                            native.set('Role', role_mapping[role])
                        commands.append(native)
                        changes.append(dict(sequence=sid, response=line['source']['sequence_line_id'],
                                            camera=native.get('CustomCamera'), role=native.get('Role')))
                    pending = []
            if pending:
                raise ValueError('Source camera has no following response: ' + sid)
            if next(responses, None) is not None:
                raise ValueError('Extra installed responses in source sequence: ' + sid)
    return xml(root), changes


def dialogue_endings(blob, model):
    root = ET.fromstring(blob)
    changes = []
    sequences = {s.get('Name'): s for s in root.iter('Sequence')}
    for topic in model['topics'].values():
        for record in topic['sequences']:
            source = record['source']
            name = 'seq_' + source['sequence_id']
            if name not in sequences:
                raise ValueError('Installed dialogue lacks source sequence: ' + name)
            target = sequences[name]
            if source['flags'] == '0' and source['next'] == '0':
                if target.get('EndType') not in (None, 'EndDialogue'):
                    raise ValueError('Unexpected terminal sequence policy: ' + name)
                if target.get('EndType') == 'EndDialogue':
                    del target.attrib['EndType']
                    changes.append(dict(sequence=source['sequence_id'], native_end='EndTopic'))
    return xml(root), changes


def objective_timers(blob, model):
    root = ET.fromstring(blob)
    host = root.find('./Skald/Quest')
    if host is None or host.get('Name') != model['quest']:
        raise ValueError('Source quest does not match installed definition')
    nodes = host.find('Nodes')
    states = {n.get('Name'): n for n in nodes if n.tag == 'State'}
    types = {n.get('TypeT') for name, n in states.items() if name.startswith('objective_')}
    if len(types) != 1:
        raise ValueError('Ambiguous installed objective state type')
    canonical, report = emit_quest(model, types.pop())
    compiled = ET.fromstring(canonical).find('./Skald/Quest/Nodes')
    by_name = {n.get('Name'): n for n in nodes}
    changes = []
    for timer in compiled.findall('Timer'):
        name = timer.get('Name', '')
        if not name.startswith('complete_') or not name.endswith('_queued'):
            continue
        identity = name[len('complete_'):-len('_queued')]
        state_name = 'objective_' + identity
        gate_name = 'complete_' + identity + '_if_started'
        if state_name not in states:
            raise ValueError('Missing installed objective state: ' + identity)
        gate = compiled.find("If[@Name='" + gate_name + "']")
        if gate is None:
            raise ValueError('Generated timer has no completion guard')
        for node in (timer, gate):
            old = by_name.get(node.get('Name'))
            if old is not None:
                if old.tag != node.tag:
                    raise ValueError('Generated timer name collides with an installed node')
                nodes.remove(old)
            nodes.append(copy.deepcopy(node))
        completion = dict(From=gate_name + '.True', To='SetCompleted')
        if not any(e.attrib == completion for e in states[state_name].findall('Edge')):
            ET.SubElement(states[state_name], 'Edge', completion)
        changes.append(dict(objective=identity, duration=timer.find("Constant[@Name='Duration']").get('Value')))
    return xml(root), dict(timers=changes, unsupported=report['unsupported'])
