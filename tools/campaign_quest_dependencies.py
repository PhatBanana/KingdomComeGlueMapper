"""Discover quest references in source predicates without executing them.

Discovery is deliberately independent of predicate lowering: an unsupported
combat/inventory check must not hide a sibling quest dependency. Quoted text is
tokenized as one unit so names that merely resemble calls are never followed.
"""
import re

from campaign_dialogue_conditions import QUEST, OBJECTIVE, expand_functions


TOKENS = re.compile(r"'(?:[^'\\]|\\.)*'|[A-Za-z_]\w*|\s+|.", re.DOTALL)


def predicate_references(expression, functions=None):
    expanded = expand_functions(expression, functions or {})
    tokens = [t for t in TOKENS.findall(expanded) if not t.isspace()]
    for index, token in enumerate(tokens):
        if token not in QUEST and token not in OBJECTIVE:
            continue
        if tokens[index + 1:index + 2] != ['(']:
            continue
        argument = tokens[index + 2:index + 3]
        if not argument:
            raise ValueError('Missing quest argument in predicate: ' + expression)
        value = argument[0]
        literal = re.fullmatch(r"'([A-Za-z_]\w*)'", value)
        yield dict(quest=literal[1] if literal else value, dynamic=literal is None,
                   operation=token)


def objective_dependencies(model):
    for row in model['tables']['quest_objective']['rows']:
        expression = row.get('condition', '')
        for reference in predicate_references(expression):
            if reference['quest'] == model['quest']:
                continue
            yield dict(quest=reference['quest'], dynamic=reference['dynamic'],
                       site=dict(table='quest_objective', objective_id=row['objective_id'],
                                 objective=row['objective_name'], expression=expression,
                                 operation=reference['operation']))
