"""Lower objective conditions that name a source predicate function.

Call after quest emission. A source objective condition can be a bare name
such as `q_example_playerStoleSomething`. The name is a row of the source
`dialogue_functions` table (function_name -> expression), the same table the
dialogue converter already expands. The emitter compiles objective conditions
without that table, so such an objective is left as a `completion_policy`
record.

This adapter expands the names and hands the expanded expression to the same
binder the emitter uses (campaign_objective_conditions.bind), so the native
shape, the Started guard and the deferred boundary are identical to an
objective whose condition was written out in full. Nothing new is emitted for
an expression that binder rejects.

    bindings['condition_functions'] = {function_name: expression}

A bare name that is not in the table stays pending as an undefined name: the
source data gives it no meaning, and none is invented. Not runtime-verified.
"""
import copy
import re
import xml.etree.ElementTree as ET

from campaign_dialogue_conditions import expand_functions
from campaign_objective_conditions import bind as bind_conditions, counted_asset
from campaign_quest_graph import xml

UNSET = ('', '-1', None)
NAME = re.compile(r'[A-Za-z_]\w*')
STEM = 'source_condition_'


def plan(model, bindings):
    functions = dict(bindings.get('condition_functions') or {})
    tracked = model['tables'].get('quest_tracked_asset', {}).get('rows', [])
    candidates, pending = [], []
    for row in model['tables']['quest_objective']['rows']:
        expression = (row.get('condition') or '').strip()
        if expression in ('', '0', '1'):
            continue
        record = dict(objective_id=row['objective_id'], objective=row['objective_name'], source=expression)
        try:
            expanded = expand_functions(expression, functions)
        except ValueError as error:
            pending.append(dict(record, reason='function expansion failed: ' + str(error))); continue
        if expanded == expression:
            if NAME.fullmatch(expression):
                pending.append(dict(record, reason='undefined condition name: ' + expression))
            continue
        if (row.get('autocomplete_timeout_str') not in UNSET or row.get('expiration_timeout_str') not in UNSET
                or row.get('time', '0') not in ('', '0')):
            pending.append(dict(record, reason='function condition with a timeout')); continue
        if any(t['objective_id'] == row['objective_id'] and counted_asset(t) for t in tracked):
            pending.append(dict(record, reason='function condition on a tracked objective')); continue
        candidates.append(dict(record, expanded=expanded,
                               functions=sorted(n for n in set(NAME.findall(expression)) if n in functions)))
    return dict(candidates=candidates, pending=pending)


def bind(blob, model, bindings):
    planned = plan(model, bindings)
    report = dict(converted=[], pending=planned['pending'], runtime_verified=False)
    if not planned['candidates']:
        return blob, report
    root = ET.fromstring(blob)
    quest = root.find('./Skald/Quest')
    if quest is None or quest.get('Name') != model['quest']:
        raise ValueError('Destination quest identity mismatch')
    nodes = quest.find('Nodes')
    wanted = {c['objective_id']: c for c in planned['candidates']}
    for oid in wanted:
        if nodes.find("Timer[@Name='" + STEM + oid + "']") is not None:
            raise ValueError('Function condition already lowered: ' + oid)
    # Only the candidate rows keep a condition, so the shared binder cannot
    # touch an objective this adapter does not own.
    expanded = copy.deepcopy(model)
    for row in expanded['tables']['quest_objective']['rows']:
        row['condition'] = wanted[row['objective_id']]['expanded'] if row['objective_id'] in wanted else ''
    bound = set(bind_conditions(nodes, expanded))
    for candidate in planned['candidates']:
        if candidate['objective'] in bound:
            report['converted'].append(dict(candidate, native=STEM + candidate['objective_id']))
        else:
            report['pending'].append(dict(objective_id=candidate['objective_id'], objective=candidate['objective'],
                                          source=candidate['source'],
                                          reason='expanded condition is not bound by the local binder'))
    return (xml(root) if report['converted'] else blob), report
