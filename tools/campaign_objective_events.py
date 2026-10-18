"""Import bounded local objective-update handlers from source behavior trees.

Only entire branches of guarded objective mutations are accepted. Unknown
operations or contextual guards remain unsupported, never partially executed.
"""
import re
from campaign_quest_graph import edge
from campaign_dialogue_effects import wire_program


def literal(value):
    return value.strip('"')


def bind(nodes, model):
    document = model.get('behavior_documents', {}).get(model.get('behavior_entry'), {})
    root = document.get('trees', {}).get('onUpdate', {}).get('root')
    if not root:
        return []
    states = {r['objective_name']: 'objective_' + r['objective_id']
              for r in model['tables']['quest_objective']['rows']}
    report = []
    wrappers = {'Root', 'Behavior', 'FuseBox', 'Child', 'Parallel', 'Loop', 'Switch'}

    def local(attrs):
        if literal(attrs.get('quest', '')) not in ('', model['quest']):
            raise ValueError('External quest')
        name = literal(attrs.get('objective', ''))
        if name not in states:
            raise ValueError('Unknown objective')
        return name

    def actions(node, guard, bindings):
        op, attrs, children = node['op'], node['attributes'], node.get('children', [])
        if op in ('Sequence', 'Then'):
            return [a for c in children for a in actions(c, guard, bindings)]
        if op == 'QuestObjectiveCondition':
            name = local(attrs)
            status = literal(attrs.get('function', '')).removeprefix('IsObjective')
            if status not in ('Started', 'Completed', 'Canceled', 'Failed', 'Unchanged'):
                raise ValueError('Unsupported objective guard')
            if len(children) != 1 or children[0]['op'] != 'Then':
                raise ValueError('Unsupported conditional branch')
            port = states[name] + '_' + status
            bindings[port] = states[name] + '.' + status
            condition = dict(op='and', children=[guard, dict(op='port', name=port)])
            return actions(children[0], condition, bindings)
        if op == 'SetQuestObjective' and not children:
            name = local(attrs)
            verb = literal(attrs.get('function', ''))
            status = {'CompleteObjective':'Completed', 'CancelObjective':'Canceled',
                      'StartObjective':'Started', 'FailObjective':'Failed'}.get(verb)
            if not status:
                raise ValueError('Unsupported objective mutation')
            return [dict(predicate=guard, quest=name, input='Set' + status)]
        raise ValueError('Unsupported handler operation: ' + op)

    def walk(node, context=True, variable=None):
        op, attrs = node['op'], node['attributes']
        if op == 'ProcessMessage':
            context = context and literal(attrs.get('inbox','')) == 'QuestMailbox' and not literal(attrs.get('condition',''))
            variable = literal(attrs.get('variable',''))
        elif op == 'ExternalLock':
            context = context and literal(attrs.get('SemaphoreName','')) == 'assetsLoaded'
        elif op == 'IfCondition' and context and variable:
            expression = literal(attrs.get('condition',''))
            pattern = (r"\(\$" + re.escape(variable) + r"\.ObjectiveName\s*==\s*'([^']+)'\)\s*&\s*"
                       r"\(\$" + re.escape(variable) + r"\.State\s*==\s*\$enum:ObjectiveState\.(Completed|Started|Canceled|Failed)\)")
            match = re.fullmatch(pattern, expression)
            if match and match[1] in states:
                bindings = {}
                try:
                    program = [a for c in node.get('children', [])
                               for a in actions(c, dict(op='constant', value='true'), bindings)]
                except ValueError:
                    program = []
                stem = 'source_event_' + states[match[1]] + '_' + match[2]
                if program:
                    if any(n.get('Name') == stem + '_0' for n in nodes):
                        return
                    wire_program(nodes, stem, states[match[1]] + '.On' + match[2], program,
                                 bindings, lambda name, *args: nodes.find("State[@Name='" + states[name] + "']"))
                    report.append(dict(objective=match[1], event=match[2], actions=len(program)))
            return
        elif op not in wrappers:
            context = False
        for child in node.get('children', []):
            walk(child, context, variable)
    walk(root)
    return report
