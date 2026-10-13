"""Refresh emitted dialogue endings and objective timers without replacing world bindings.

The source models select policy. Existing imported scene placement, voices,
quest scope and reward wiring are preserved and validated before replacement.
"""
import copy
import xml.etree.ElementTree as ET

from campaign_quest_graph import emit_quest, xml


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
