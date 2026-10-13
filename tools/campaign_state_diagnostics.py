"""Attach read-only native traces to imported objective and timer states.

These diagnostics observe the installed graph. They never start objectives,
complete timers, alter dialogue eligibility or replay the New Game initializer.
"""
import xml.etree.ElementTree as ET

from campaign_quest_graph import identifier, xml


def observe(blob, objective_names):
    root = ET.fromstring(blob)
    quest = root.find('./Skald/Quest')
    if quest is None:
        raise ValueError('Expected one installed quest definition')
    nodes = quest.find('Nodes')
    output = nodes.find("Output[@Name='Output']")
    if output is None:
        raise ValueError('Quest has no objective output bindings')
    names = {n.get('Name'): n for n in nodes}
    receipts = []
    for objective in sorted(set(objective_names)):
        identifier(objective)
        matches = [e.get('From') for e in output.findall('Edge')
                   if e.get('To') == objective + '_Started']
        if len(matches) != 1 or not matches[0].endswith('.Started'):
            raise ValueError('Missing or ambiguous objective binding: ' + objective)
        state_name = matches[0].removesuffix('.Started')
        state = names.get(state_name)
        if state is None or state.tag != 'State' or not state.get('TypeT'):
            raise ValueError('Objective binding is not a typed state: ' + objective)
        observed = [(state_name, state.get('TypeT'))]
        timers = [n for n in nodes if n.tag == 'Timer' and any(
            e.get('From') == state_name + '.OnStarted' and e.get('To') == 'SetRunning'
            for e in n.findall('Edge'))]
        observed.extend((n.get('Name'), 'wh::rpgmodule::TimerState') for n in timers)
        for name, typ in observed:
            trace_name = 'gm_observe_' + objective + '_' + name
            identifier(trace_name)
            expected = ET.Element('Trace', Name=trace_name, TypeT=typ)
            ET.SubElement(expected, 'Edge', From=name + '.State', To='Value')
            ET.SubElement(expected, 'Edge', From=name + '.OnExec', To='Exec')
            old = names.get(trace_name)
            if old is not None:
                if old.tag != 'Trace' or old.attrib != expected.attrib or [e.attrib for e in old] != [e.attrib for e in expected]:
                    raise ValueError('Diagnostic node name collision: ' + trace_name)
            else:
                nodes.append(expected)
                names[trace_name] = expected
        receipts.append(dict(objective=objective, state=state_name,
                             timers=[n.get('Name') for n in timers]))
    return xml(root), receipts
