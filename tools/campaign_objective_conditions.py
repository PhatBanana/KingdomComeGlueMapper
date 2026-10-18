"""Compile local source objective predicates into persistent native states.

Map-only tracking is presentation. Counted tracking and external predicates
require their own adapters and must never be treated as unconditional success.
"""
import xml.etree.ElementTree as ET


def bind(nodes, model):
    from campaign_dialogue_conditions import QuestConditions
    from campaign_dialogue_effects import predicate, wire_program
    from campaign_quest_graph import constant, edge, objective_identifier
    rows = model['tables']['quest_objective']['rows']
    outputs = {objective_identifier(r['objective_name']) + '_' + status:
               'objective_' + r['objective_id'] + '.' + status
               for r in rows for status in ('Started', 'Completed', 'Canceled', 'Unchanged')}
    functions = {r['function_name']: r['expression']
                 for r in model['tables'].get('quest_function', {}).get('rows', [])}
    tracked = model['tables'].get('quest_tracked_asset', {}).get('rows', [])
    converted = []
    for row in rows:
        expression = row.get('condition', '').strip()
        if not expression or expression == '1':
            continue
        if (row.get('autocomplete_timeout_str') not in ('', '-1', None)
                or row.get('expiration_timeout_str') not in ('', '-1', None)
                or row.get('time', '0') not in ('', '0')
                or any(t['objective_id'] == row['objective_id'] and t['count'] != '0' for t in tracked)):
            continue
        compiler = QuestConditions([model], functions)
        try:
            tree = predicate(compiler.compile(expression))
        except ValueError:
            continue
        if any(b.get('quest') != model['quest'] or b.get('output') not in outputs
               for b in compiler.bindings.values()):
            continue
        stem = 'source_condition_' + row['objective_id']
        state = nodes.find("State[@Name='objective_" + row['objective_id'] + "']")
        if state is None:
            raise ValueError('Missing objective state ' + row['objective_id'])
        if nodes.find("Timer[@Name='" + stem + "']") is not None:
            continue
        timer = ET.SubElement(nodes, 'Timer', Name=stem)
        constant(timer, 'Duration', '0s'); constant(timer, 'TimeType', 'GameTime')
        edge(timer, state.get('Name') + '.OnStarted', 'SetRunning')
        bindings = {name: outputs[b['output']] for name, b in compiler.bindings.items()}
        for dependency in sorted(set(v.rsplit('.', 1)[0] for v in bindings.values())):
            edge(timer, dependency + '.OnExec', 'SetRunning')
        bindings['own_started'] = state.get('Name') + '.Started'
        guarded = dict(op='and', children=[dict(op='port', name='own_started'), tree])
        wire_program(nodes, stem + '_apply', stem + '.OnFinished',
                     [dict(predicate=guarded, quest=model['quest'], input='SetCompleted')],
                     bindings, lambda *args: state)
        converted.append(row['objective_name'])
    return converted
