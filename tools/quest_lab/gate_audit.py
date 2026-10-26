"""Audit every FilterInput gate in a package: filters, release and engagement.

Probes are isolated stimuli, not a playthrough. A clean result means the modeled
gate engages, blocks the listed input actions and releases within a bounded
GameTime window. It never establishes the native unknowns in ``filters.py``.
"""
import copy

from . import Unsupported
from .audit import definitions, probe
from .filters import ENGINE_EVENTS, KIND, LEAK_BOUND_HOURS, NATIVE_UNKNOWNS
from .graph import Graph
from . import collections as collection_nodes


def cone(host):
    """Names of the nodes that can influence a FilterInput, following every incoming edge."""
    nodes = {n.get('Name'): n for n in host.findall('Nodes/*') if n.tag != 'Output'}
    keep, todo = set(), [name for name, node in nodes.items() if node.tag == KIND]
    while todo:
        name = todo.pop()
        if name in keep: continue
        keep.add(name)
        todo.extend(e.get('From', '').partition('.')[0] for e in nodes[name].findall('Edge')
                    if e.get('From', '').partition('.')[0] in nodes)
    return keep


def isolated(source, path, host, keep):
    """The same package with this definition reduced to its gate's cone of influence.

    Unrelated native nodes cannot stop a probe before the gate is reached, while any
    unsupported node that can influence the gate stays in the slice and stays visible.
    """
    slim = copy.deepcopy(host)
    nodes = slim.find('Nodes')
    for node in list(nodes):
        if node.tag == 'Output' or node.get('Name') not in keep: nodes.remove(node)
    includes = slim.find('Definitions')
    if includes is not None and not any(n.tag in source.definitions for n in nodes):
        slim.remove(includes)
    clone = copy.copy(source)
    clone.definitions = {name: [(p, slim if d is host else d) for p, d in rows] for name, rows in source.definitions.items()}
    return clone, len(keep)


def timer_driven(graph, name):
    """The Timer a gate's IsActive follows, when it is wired straight to Timer.Running."""
    ref = graph.nodes[name]['values'].get('IsActive', '')
    owner, _, port = graph.aliases.get(ref, ref).rpartition('.')
    return owner if port == 'Running' and owner in graph.nodes and graph.nodes[owner]['kind'] == 'Timer' else None


def static_checks(graph, findings):
    gates = {}
    for name in graph.filter_nodes:
        node = graph.nodes[name]
        info = dict(filters=None, timer=timer_driven(graph, name), is_active_constant=node['constants'].get('IsActive'))
        gates[name] = info
        try:
            filters = graph._args(name)['Filters']
            collection_nodes.array(filters)
            info['filters'] = list(filters)
        except Unsupported as exc:
            findings.append(dict(kind='filters_unresolved', node=name, reason=str(exc)))
            continue
        if graph.actions is not None:
            unknown = [f for f in filters if f not in graph.actions.filters]
            if unknown: findings.append(dict(kind='unknown_filter', node=name, filters=unknown,
                                             reason='Filter is not defined in the supplied input profile'))
        if info['is_active_constant'] is True:
            findings.append(dict(kind='filter_leak', node=name, reason='IsActive is a constant true; the gate can never release'))
        elif info['is_active_constant'] is False:
            findings.append(dict(kind='gate_never_active', node=name, reason='IsActive is a constant false'))
        if info['timer']:
            timer = graph.nodes[info['timer']]['constants']
            info['timer_duration'] = timer.get('Duration')
    return gates


def gate_audit(source, path, host, actions=None, required=()):
    name = host.get('Name')
    result = dict(name=name, file=path, status='LOAD_BLOCKED', findings=[], gates={}, probes=[],
                  native_runtime_verified=False, leak_bound_hours=LEAK_BOUND_HOURS,
                  native_contracts=[dict(id=k, status='UNSUPPORTED', detail=v) for k, v in NATIVE_UNKNOWNS.items()],
                  action_profile_sha256=actions.sha256 if actions else None)
    keep = cone(host)
    total = sum(1 for n in host.findall('Nodes/*') if n.tag != 'Output')
    result['isolation'] = dict(kind='cone_of_influence', nodes=len(keep), of=total)
    try: graph = Graph(isolated(source, path, host, keep)[0], name, entry_file=path, actions=actions)
    except (Unsupported, ValueError) as exc:
        result['error'] = str(exc)
        return result
    findings = result['findings']
    result['gates'] = static_checks(graph, findings)
    result['gate_unsupported'] = graph.unsupported
    initial = graph.snapshot()
    stimuli = sorted(p for p in graph.event_ports if '.' not in p)
    engaged = {}
    for stimulus in stimuli:
        entry = probe(graph, initial, 'stimulus: ' + stimulus, [stimulus], LEAK_BOUND_HOURS)
        records = [r for r in graph.trace if r['kind'] == 'filters']
        peak_nodes = sorted({n for r in records for n in r['nodes']})
        peak_filters = sorted({f for r in records for f in r['active']})
        final = None
        if entry['status'] == 'EXECUTED':
            try: final = graph.active_gates()[1]
            except Unsupported as exc: entry.update(status='UNSUPPORTED', error=str(exc))
        entry.update(engages=peak_nodes, peak_filters=peak_filters, active_after_bound=final)
        if graph.actions is not None and peak_filters:
            try: entry['peak_blocked_actions'] = sorted(graph.actions.resolve(peak_filters))
            except Unsupported: pass
        entry.pop('trace_tail', None)
        result['probes'].append(entry)
        engaged[stimulus] = set(peak_nodes)
        if final:
            findings.append(dict(kind='filter_active_after_bound', stimulus=stimulus, filters=final,
                                 reason='Filters are still active ' + str(LEAK_BOUND_HOURS) + ' GameTime hours after this stimulus'))
    # A timer-driven hold in a Level must engage on every entry event the Level can receive.
    for name_, info in result['gates'].items():
        if not info['timer']: continue
        for event in sorted(graph.engine_events):
            if name_ not in engaged.get(event, set()):
                findings.append(dict(kind='not_engaged_by_entry_event', node=name_, stimulus=event,
                                     reason='The timer-driven gate does not engage on ' + event))
    if graph.actions is not None:
        entry_events = [e for e in ENGINE_EVENTS if e in engaged]
        sets = [set(p['peak_blocked_actions']) for p in result['probes']
                if p['name'][len('stimulus: '):] in entry_events and p.get('peak_blocked_actions')]
        blocked = set.intersection(*sets) if sets else set()
        result['apse_actions_blocked'] = {a: a in blocked for a in graph.actions.apse_actions()}
        for action in required:
            if action not in graph.actions.actions:
                findings.append(dict(kind='unknown_action', action=action, reason='Action is not in the supplied input profile'))
            elif action not in blocked:
                findings.append(dict(kind='required_action_not_blocked', action=action,
                    reason='Not blocked at the peak of every entry-event probe'))
    if not graph.filter_nodes: result['status'] = 'NO_FILTER_INPUT'
    elif findings: result['status'] = 'FINDINGS'
    elif graph.actions is None or any(p['status'] != 'EXECUTED' for p in result['probes']) or result['gate_unsupported']:
        result['status'] = 'PARTIAL_UNSUPPORTED'
    else:
        result['status'] = 'STATIC_CHECKS_PASSED'
    return result


def audit_gates(source, actions=None, required=()):
    seen, results = set(), []
    for path, host in definitions(source):
        if host.find('Nodes/FilterInput') is None or (path, host.get('Name')) in seen: continue
        seen.add((path, host.get('Name')))
        results.append(gate_audit(source, path, host, actions, required))
    return results
