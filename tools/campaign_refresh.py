"""Refresh emitted dialogue endings and objective timers without replacing world bindings.

The source models select policy. Existing imported scene placement, voices,
quest scope and reward wiring are preserved and validated before replacement.
"""
import copy
import xml.etree.ElementTree as ET

from campaign_quest_graph import emit_quest, xml


def dialogue_camera_selection(blob, model, camera_aliases=(), *, scene_bound=False):
    """Refresh only camera commands from source responses and authored cuts.

    Infer role renaming from validated installed response identities. Preserve
    voices, actions, other presentation commands, and in-world monologues.
    """
    from campaign_dialogue import presentation_command, response_camera_command
    root = ET.fromstring(blob)
    host = list(root.find('Skald'))[0]
    if host.tag not in ('FaderDialog', 'ForcedDialog'):
        raise ValueError('Camera refresh requires a cinematic dialogue')
    sequences = {s.get('Name'): s for s in root.iter('Sequence')}
    mapping, pairs = {}, []
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
                    source_role = model['roles'][line['response']['role_id']]['role_name']
                    role = response.get('Role')
                    if not role or (source_role in mapping and mapping[source_role] != role):
                        raise ValueError('Ambiguous installed speaker role: ' + source_role)
                    mapping[source_role] = role
                    pairs.append((response, line['response'], pending))
                    pending = []
            if pending or next(responses, None) is not None:
                raise ValueError('Unmatched source presentation/response: ' + sid)
    report = dict(responses=len(pairs), automatic=0, authored=0, scene_bound=scene_bound,
                  world_cameras_to_actor=0)
    for response, source, pending in pairs:
        cameras = []
        initial = response_camera_command(source, pending, model)
        if initial is not None:
            cameras.append(initial)
        cameras.extend(presentation_command(c, model, scene_bound=scene_bound) for c in pending)
        report['world_cameras_to_actor'] += sum(c.get('int_param') == '5' and bool(c.get('char_param'))
                                                for c in pending) if not scene_bound else 0
        commands = response.find('Commands')
        if commands is None:
            commands = ET.SubElement(response, 'Commands')
        for old in list(commands):
            if old.tag == 'CameraCommand':
                commands.remove(old)
        for camera in cameras:
            role = camera.get('Role')
            if role not in mapping:
                raise ValueError('Unresolved camera target role: ' + str(role))
            camera.set('Role', mapping[role])
            if camera.get('CustomCamera') and camera.get('CustomCamera') not in camera_aliases:
                raise ValueError('Unregistered custom camera: ' + camera.get('CustomCamera'))
            commands.append(camera)
            report['authored' if camera.get('CustomCamera') or camera.get('CameraType') else 'automatic'] += 1
    return xml(root), report


def dialogue_cameras(blob, model, camera_aliases, role_mapping=None, *, scene_bound=False):
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
                        native = presentation_command(command, model, scene_bound=scene_bound)
                        if native.get('CustomCamera') and native.get('CustomCamera') not in camera_aliases:
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
