"""Ordered dialogue objective effects over converted, live quest predicates.

Conditions are evaluated when each effect fires, not cached when a response is
selected. Dialogue-local Lua variables cannot be read by the owning Skald graph
and therefore require a separate adapter rather than an assumed true value.
"""
import re
import xml.etree.ElementTree as ET
from campaign_quest_graph import constant, edge


def predicate(expression):
    tokens = re.findall(r"Port\('[A-Za-z_]\w*'\)|AND\b|OR\b|true\b|false\b|[01]\b|[!()]", expression)
    if ''.join(tokens) != re.sub(r'\s+', '', expression):
        raise ValueError('Dialogue effect requires a graph-readable predicate: ' + expression)
    position = 0

    def atom():
        nonlocal position
        if position >= len(tokens):
            raise ValueError('Incomplete dialogue effect predicate')
        token = tokens[position]; position += 1
        if token == '!': return dict(op='not', children=[atom()])
        if token == '(':
            result = disjunction()
            if position >= len(tokens) or tokens[position] != ')':
                raise ValueError('Unclosed dialogue effect predicate')
            position += 1
            return result
        if token in ('true', 'false', '0', '1'):
            return dict(op='constant', value='true' if token in ('true', '1') else 'false')
        if token.startswith('Port('): return dict(op='port', name=token[6:-2])
        raise ValueError('Invalid dialogue effect predicate token: ' + token)

    def conjunction():
        nonlocal position
        result = atom()
        while position < len(tokens) and tokens[position] == 'AND':
            position += 1
            result = dict(op='and', children=[result, atom()])
        return result

    def disjunction():
        nonlocal position
        result = conjunction()
        while position < len(tokens) and tokens[position] == 'OR':
            position += 1
            result = dict(op='or', children=[result, conjunction()])
        return result

    if not expression: return dict(op='constant', value='true')
    result = disjunction()
    if position != len(tokens): raise ValueError('Trailing dialogue effect predicate')
    return result


def wire_program(nodes, stem, event, actions, condition_outputs, destination):
    """Emit ordered A/B trigger chains; resolve conditions afresh at every step."""
    for index, action in enumerate(actions):
        name = stem + '_' + str(index)
        sequence = ET.SubElement(nodes, 'TriggerSequence', Name=name)
        edge(sequence, event, 'Exec')
        gate = ET.SubElement(nodes, 'If', Name=name + '_gate')
        edge(gate, name + '.A', 'Exec')

        def connect(tree, target, port, suffix):
            op = tree['op']
            if op == 'constant':
                if tree['value'] not in ('true', 'false'): raise ValueError('Invalid effect boolean')
                constant(target, port, tree['value'])
            elif op == 'port':
                if tree['name'] not in condition_outputs:
                    raise ValueError('Undeclared dialogue effect condition: ' + tree['name'])
                edge(target, condition_outputs[tree['name']], port)
            elif op in ('and', 'or', 'not'):
                children = tree['children']
                if len(children) != (1 if op == 'not' else 2): raise ValueError('Invalid effect boolean arity')
                node = ET.SubElement(nodes, 'Function', Name=suffix,
                    MethodName='math::boolean::' + op.title(), DeclaringType='math::boolean')
                for child_index, child in enumerate(children):
                    connect(child, node, 'Value' if op == 'not' else 'AB'[child_index], suffix + '_' + str(child_index))
                edge(target, suffix + '.bool', port)
            else:
                raise ValueError('Unsupported effect predicate: ' + op)

        connect(action['predicate'], gate, 'Condition', name + '_condition')
        edge(destination(action['quest'], action['input'], 'In', 'trigger'), name + '_gate.True', action['input'])
        # B runs after A and its effects; the next condition can observe a state
        # changed by the previous action. No timer or response-entry snapshot.
        event = name + '.B'
