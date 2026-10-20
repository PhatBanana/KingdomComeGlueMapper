"""Bind explicitly mapped instruction scenes to native tutorial phases.

Source dialogue identities must be resolved by the dialogue importer. Phase
numbers are taken from an inspected native contract, never source tree order.
"""
import xml.etree.ElementTree as E

from campaign_quest_graph import edge, constant, all_of, identifier


def native_phases(blob):
    root = E.fromstring(blob)
    result = []
    for nodes in root.findall('.//Nodes'):
        for tutorial in nodes.findall('CombatTutorialNode'):
            name = tutorial.get('Name')
            switches = [n for n in nodes.findall('Switch')
                        if n.find("Edge[@From='" + name + ".Phase'][@To='Switch']") is not None]
            if len(switches) != 1: continue
            switch = switches[0]
            states = [n for n in nodes.findall('State') if n.find(
                "Edge[@From='" + switch.get('Name') + ".Value1'][@To='Value']") is not None]
            if len(states) != 1: continue
            state = states[0]
            barriers = {e.get('From') for e in tutorial.findall("Edge[@To='CustomStepEvent']")}
            for index, phase in enumerate(switch.get('SwitchValues', '').split()):
                c = switch.find("Constant[@Name='" + str(index) + "Value1']")
                if c is None or not c.get('Value', '').endswith('_starting'):
                    raise ValueError('Unrecognized native tutorial phase state')
                active = 'Set' + c.get('Value').removesuffix('_starting') + '_active'
                acknowledgements = [e.get('From') for e in state.findall("Edge[@To='" + active + "']")]
                if len(acknowledgements) != 1: raise ValueError('Ambiguous native phase acknowledgement')
                result.append(dict(phase=int(phase), state=c.get('Value'),
                    native_scene_event=acknowledgements[0],
                    custom_step=acknowledgements[0] in barriers))
    if not result or len({r['phase'] for r in result}) != len(result):
        raise ValueError('Expected one unambiguous native tutorial phase contract')
    return result


def bind(nodes, lifecycle, scenes, phases, cancel_events):
    """Wire imported scene nodes; only their released scenes acknowledge phases.

    scenes maps native phase -> {node, play_port}. Each scene must be dedicated
    to this invocation by the caller. Cancellation invalidates pending releases.
    """
    name = identifier(lifecycle.get('Name'))
    if set(scenes) != {p['phase'] for p in phases}:
        raise ValueError('Every native phase requires an explicit imported dialogue mapping')
    if len({s['node'].get('Name') for s in scenes.values()}) != len(scenes):
        raise ValueError('Training phases cannot share an unscoped scene invocation')
    if any(e.get('To') == 'ack_phase' for e in lifecycle.findall('Edge')):
        raise ValueError('Training acknowledgement phase already bound')
    edge(lifecycle, name + '.phase', 'ack_phase')
    for phase in phases:
        number = phase['phase']; scene = scenes[number]
        prefix = name + '_instruction_' + str(number)
        if any(n.get('Name', '').startswith(prefix + '_') for n in nodes):
            raise ValueError('Training dialogue phase already bound')
        pending = E.SubElement(nodes, 'State', Name=prefix+'_pending', TypeT='bool')
        constant(pending, 'DefaultValue', 'false')
        # Internal failures also stop the lifecycle. They need not arrive via
        # one of the caller's cancel events; do not retain a pending scene lock
        # into the next invocation after readiness/preparation failure.
        for event in dict.fromkeys((*cancel_events, name+'.stop_workers')):
            edge(pending, event, 'SetFalse')
        def compare(suffix, event):
            test = E.SubElement(nodes, 'IfFunction', Name=prefix+suffix, TypeT='int',
                MethodName='Control::Compare', DeclaringType='Control')
            constant(test, 'Op', 'Equals'); constant(test, 'ValueB', str(number))
            edge(test, name+'.phase', 'ValueA'); edge(test, event, 'Exec')
            return test.get('Name')+'.True'
        start = E.SubElement(nodes, 'If', Name=prefix+'_start')
        edge(start, compare('_phase', name+'.phase_started'), 'Exec')
        idle = E.SubElement(nodes, 'Function', Name=prefix+'_not_pending',
            MethodName='math::boolean::Not', DeclaringType='math::boolean')
        edge(idle, pending.get('Name')+'.State', 'Value')
        edge(start, all_of(nodes, prefix+'_can_play', [name+'.training_active', idle.get('Name')+'.bool']), 'Condition')
        order = E.SubElement(nodes, 'TriggerSequence', Name=prefix+'_launch')
        edge(order, start.get('Name')+'.True', 'Exec')
        edge(pending, order.get('Name')+'.A', 'SetTrue')
        edge(scene['node'], order.get('Name')+'.B', scene['play_port'])
        waiter = E.SubElement(nodes, 'SceneFinishedWaiter', Name=prefix+'_released')
        edge(waiter, scene['node'].get('Name')+'.AfterPlay', 'Enqueue')
        valid = E.SubElement(nodes, 'If', Name=prefix+'_valid')
        edge(valid, compare('_release_phase', waiter.get('Name')+'.OnFinished'), 'Exec')
        edge(valid, all_of(nodes, prefix+'_live', [pending.get('Name')+'.State', name+'.training_active']), 'Condition')
        finish = E.SubElement(nodes, 'TriggerSequence', Name=prefix+'_finish')
        edge(finish, valid.get('Name')+'.True', 'Exec')
        edge(pending, finish.get('Name')+'.A', 'SetFalse')
        edge(lifecycle, finish.get('Name')+'.B', 'dialogue_finished')
        if phase['custom_step']: edge(lifecycle, finish.get('Name')+'.C', 'instruction_ack')
    return dict(mapped_phases=sorted(scenes), runtime_validated=False,
                requires_invocation_scoped_scenes=True)
