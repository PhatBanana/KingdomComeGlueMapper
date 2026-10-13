"""Compile source boolean quest predicates into validated native dialogue ports.

Only this explicit grammar is accepted. Unsupported gameplay checks are errors,
never evaluated as true or copied as unverified native expressions.
"""
import hashlib
import re

from campaign_quest_graph import objective_identifier


TOKEN = re.compile(r"\s*(?:(AND|OR)\b|([A-Za-z_]\w*)|('(?:[^'\\]|\\.)*')|(-?\d+(?:\.\d+)?)|(==|!=|>=|<=|>|<)|([!(),&|]))")
QUEST = {'IsQuestStarted': 'started', 'IsQuestCompleted': 'completed',
         'IsQuestActivated': 'available', 'IsQuestUnchanged': 'unchanged'}
OBJECTIVE = {'IsObjectiveStarted': 'Started', 'IsObjectiveCompleted': 'Completed',
             'IsObjectiveCanceled': 'Canceled', 'IsObjectiveUnchanged': 'Unchanged'}


def expand_functions(expression, functions, stack=()):
    """Expand source database predicates; never replace identifiers in literals."""
    if len(stack) > 64:
        raise ValueError('Dialogue function expansion depth exceeded')
    parts = []
    for match in re.finditer(r"'(?:[^'\\]|\\.)*'|[A-Za-z_]\w*|[^A-Za-z_']+|'", expression):
        token = match.group()
        if token not in functions:
            parts.append(token)
            continue
        if token in stack:
            raise ValueError('Cyclic dialogue function: ' + ' -> '.join((*stack, token)))
        parts.append('(' + expand_functions(functions[token], functions, (*stack, token)) + ')')
        if sum(map(len, parts)) > 1_000_000:
            raise ValueError('Dialogue function expansion size exceeded')
    return ''.join(parts)


class QuestConditions:
    def __init__(self, models, functions=None, registered_items=()):
        self.quests = {m['quest']: {r['objective_name'] for r in m['tables']['quest_objective']['rows']}
                       for m in models}
        self.bindings = {}
        self.functions = dict(functions or {})
        self.registered_items = {str(i).lower() for i in registered_items}

    def compile(self, expression):
        source = expand_functions(expression, self.functions).strip()
        if not source or source == '1': return ''
        tokens, offset = [], 0
        while offset < len(source):
            match = TOKEN.match(source, offset)
            if not match: raise ValueError('Unconverted dialogue condition: ' + source)
            token = next(v for v in match.groups() if v is not None)
            tokens.append({'&': 'AND', '|': 'OR', 'TRUE': '1', 'FALSE': '0',
                           'true': '1', 'false': '0'}.get(token, token))
            offset = match.end()
        index = 0
        pending = {}

        def take(expected=None):
            nonlocal index
            if index >= len(tokens) or (expected is not None and tokens[index] != expected):
                raise ValueError('Malformed dialogue condition: ' + source)
            token = tokens[index]; index += 1
            return token

        def atom():
            token = take()
            if token == '!': return '!(' + atom() + ')'
            if token == '(':
                value = disjunction(); take(')'); return '(' + value + ')'
            if token in ('var', 'GetAmountOfActorItems'):
                take('('); argument = take(); take(')')
                if not argument.startswith("'"):
                    raise ValueError('Expected literal dialogue scalar argument')
                value = argument[1:-1]
                if token == 'var':
                    if not re.fullmatch(r'[A-Za-z_]\w*', value):
                        raise ValueError('Invalid dialogue variable')
                    native = 'var'
                else:
                    if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value):
                        raise ValueError('Invalid dialogue item identity')
                    if value.lower() not in self.registered_items:
                        raise ValueError('Unregistered dialogue item: ' + value)
                    native = 'CountOfActorItems'
                operator, number = take(), take()
                if operator not in ('==', '!=', '>=', '<=', '>', '<') or not re.fullmatch(r'-?\d+(?:\.\d+)?', number):
                    raise ValueError('Unconverted dialogue scalar comparison')
                return native + '(' + argument + ') ' + operator + ' ' + number
            if token in ('0', '1'): return 'false' if token == '0' else 'true'
            if token not in QUEST and token not in OBJECTIVE:
                raise ValueError('Unconverted dialogue predicate: ' + token)
            take('('); quest = take()
            if not re.fullmatch(r"'[A-Za-z_]\w*'", quest):
                raise ValueError('Expected literal quest identity')
            quest = quest[1:-1]
            if quest not in self.quests: raise ValueError('Unregistered dialogue quest: ' + quest)
            if token in OBJECTIVE:
                take(','); objective = take()
                if not objective.startswith("'") or objective[1:-1] not in self.quests[quest]:
                    raise ValueError('Unregistered dialogue objective: ' + objective)
                port = objective_identifier(objective[1:-1]) + '_' + OBJECTIVE[token]
            else:
                port = QUEST[token]
            take(')')
            name = 'condition_' + hashlib.sha256((quest + ':' + port).encode()).hexdigest()[:20]
            pending[name] = dict(quest=quest, output=port)
            return "Port('" + name + "')"

        def conjunction():
            nonlocal index
            value = atom()
            while index < len(tokens) and tokens[index] == 'AND':
                index += 1; value += ' AND ' + atom()
            return value

        def disjunction():
            nonlocal index
            value = conjunction()
            while index < len(tokens) and tokens[index] == 'OR':
                index += 1; value += ' OR ' + conjunction()
            return value

        value = disjunction()
        if index != len(tokens): raise ValueError('Trailing dialogue condition tokens: ' + source)
        self.bindings.update(pending)
        return value
