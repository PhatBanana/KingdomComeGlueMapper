"""Expose executed dialogue sequences to native gameplay handoff consumers."""
import xml.etree.ElementTree as E

ACTIVITY_PORT = 'gm_sequence_active'


def bind_scene_release(nodes, state, instance, activity_port=ACTIVITY_PORT):
    """Release occupancy even when this definition is borrowed by another scene.

    AfterPlay belongs to the initiating dialogue holder. A root menu can run
    sequences from a different holder without ever firing its AfterPlay.
    Queue the native scene callback on the first executed sequence as well.
    A separate latch prevents repeated topic choices from queuing callbacks.
    """
    from campaign_quest_graph import edge, constant
    name = state.get('Name')
    waiter = nodes.find("SceneFinishedWaiter[@Name='" + name + "_released']")
    if waiter is None:
        raise ValueError('Missing dialogue scene-release waiter: ' + name)
    if nodes.find("State[@Name='" + name + "_release_queued']") is not None:
        return
    queued = E.SubElement(nodes, 'State', Name=name + '_release_queued', TypeT='bool')
    constant(queued, 'DefaultValue', 'false')
    inverse = E.SubElement(nodes, 'Function', Name=name + '_release_available',
        MethodName='math::boolean::Not', DeclaringType='math::boolean')
    edge(inverse, queued.get('Name') + '.State', 'Value')
    gate = E.SubElement(nodes, 'If', Name=name + '_queue_release')
    edge(gate, instance + '.' + activity_port, 'Exec')
    edge(gate, instance + '.AfterPlay', 'Exec')
    edge(gate, inverse.get('Name') + '.bool', 'Condition')
    order = E.SubElement(nodes, 'TriggerSequence', Name=name + '_enqueue_release')
    edge(order, gate.get('Name') + '.True', 'Exec')
    edge(queued, order.get('Name') + '.A', 'SetTrue')
    for old in list(waiter.findall('Edge')):
        if old.get('To') == 'Enqueue':
            waiter.remove(old)
    edge(waiter, order.get('Name') + '.B', 'Enqueue')
    edge(queued, name + '_finished.A', 'SetFalse')


def expose(host):
    if host.tag not in ('FaderDialog', 'ForcedDialog'):
        return None
    ports = host.find('Ports')
    if ports is None:
        ports = E.SubElement(host, 'Ports')
    existing = ports.find("Port[@Name='" + ACTIVITY_PORT + "']")
    if existing is None:
        E.SubElement(ports, 'Port', Name=ACTIVITY_PORT, Direction='Out', Type='trigger')
    elif existing.get('Direction') != 'Out' or existing.get('Type') != 'trigger':
        raise ValueError('Dialogue activity port collision')
    for sequence in host.findall('.//Dialogue//Sequence'):
        triggers = sequence.find('Triggers')
        if triggers is None:
            triggers = E.Element('Triggers'); sequence.insert(0, triggers)
        if triggers.find("Port[@Name='" + ACTIVITY_PORT + "']") is None:
            # Establish occupancy before this sequence's quest effects execute.
            triggers.insert(0, E.Element('Port', Name=ACTIVITY_PORT))
    return ACTIVITY_PORT
