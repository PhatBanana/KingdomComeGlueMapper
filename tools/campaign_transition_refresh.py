"""Refresh source-derived transitions while preserving other installed quest logic."""
import copy
import xml.etree.ElementTree as E

from campaign_quest_graph import emit_quest, xml

PREFIXES = ('advance_', 'ready_', 'exclusive_cancel_', 'exclusive_ready_', 'quest_end_')


def refresh(blob, model):
    root = E.fromstring(blob)
    host = root.find('./Skald/Quest')
    if host is None or host.get('Name') != model['quest']:
        raise ValueError('Wrong installed quest')
    nodes = host.find('Nodes')
    installed = {n.get('Name'): n for n in nodes}
    types = {n.get('TypeT') for n in nodes if n.tag == 'State' and n.get('Name', '').startswith('objective_')}
    if len(types) != 1: raise ValueError('Ambiguous installed objective state type')
    source, conversion = emit_quest(model, next(iter(types)))
    generated = E.fromstring(source).find('./Skald/Quest/Nodes')
    managed = {n.get('Name'): n for n in generated if n.get('Name', '').startswith(PREFIXES)}
    old = {name for name in installed if name and name.startswith(PREFIXES)}
    remaining = set(installed) - old
    for node in managed.values():
        for edge in node.findall('Edge'):
            dep = edge.get('From', '').split('.')[0]
            if dep not in managed and dep not in remaining:
                raise ValueError('Unresolved transition prerequisite: ' + dep)
    bindings = []
    for state in generated.findall('State'):
        for edge in state.findall('Edge'):
            if edge.get('From', '').split('.')[0] in managed:
                if state.get('Name') not in remaining:
                    raise ValueError('Missing transition target: ' + state.get('Name'))
                bindings.append((state.get('Name'), edge))
    for node in list(nodes):
        if node.get('Name') in old: nodes.remove(node)
        else:
            for edge in list(node.findall('Edge')):
                if edge.get('From', '').split('.')[0] in old | set(managed): node.remove(edge)
    for node in managed.values(): nodes.append(copy.deepcopy(node))
    for state, edge in bindings: installed[state].append(copy.deepcopy(edge))
    return xml(root), dict(transitions=[n for n in managed if n.startswith('advance_')],
        exclusive_cancellations=conversion['exclusive_cancellations'],
        unsupported=conversion['unsupported'], runtime_verified=False)
