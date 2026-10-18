"""Compile source boolean quest predicates into validated native dialogue ports.

Only this explicit grammar is accepted. Unsupported gameplay checks are errors,
never evaluated as true or copied as unverified native expressions.
"""
import hashlib
import re

from campaign_quest_graph import objective_identifier


TOKEN = re.compile(r"\s*(?:(AND|OR)\b|([A-Za-z_]\w*)|('(?:[^'\\]|\\.)*')|(-?\d+(?:\.\d+)?)|(==|!=|>=|<=|>|<)|([!(),&|\[\]]))")
QUEST = {'IsQuestStarted': 'started', 'IsQuestCompleted': 'completed',
         'IsQuestActivated': 'available', 'IsQuestUnchanged': 'unchanged'}
OBJECTIVE = {'IsObjectiveStarted': 'Started', 'IsObjectiveCompleted': 'Completed',
             'IsObjectiveCanceled': 'Canceled', 'IsObjectiveUnchanged': 'Unchanged'}

# Native Quests/Final/Barbora/trosecko/zachrana/hibernace/treti_den/ipl_overlay.xml.
ENGINE_PREDICATES = {'IsStreamInstallComplete': dict(
    method='wh::framework::IsStreamInstallComplete', declaring_type='wh::framework', output='IsCompleted')}


def normalize_boolean_literals(expression):
    """Use native Skald literals without modifying quoted names or identifiers."""
    return re.sub(r"'(?:[^'\\]|\\.)*'|\b(?:true|false)\b",
                  lambda m: {'true': '1', 'false': '0'}.get(m.group(), m.group()), expression)


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
    def __init__(self, models, functions=None, registered_items=(), participant_assets=None, sequences=None,
                 area_assets=None, context_entities=None):
        self.quests = {m['quest']: {r['objective_name'] for r in m['tables']['quest_objective']['rows']}
                       for m in models}
        self.bindings = {}
        self.functions = dict(functions or {})
        self.registered_items = {str(i).lower() for i in registered_items}
        self.participant_assets = dict(participant_assets or {})
        self.sequences = dict(sequences or {})
        self.area_assets = dict(area_assets or {})
        self.context_entities = dict(context_entities or {})

    def sequence_condition(self, sid, expression=None, stack=()):
        """Preserve eligibility and source cooldown, including referenced sequences.

        KCD1 cooldown -1 disables a sequence after use; zero has no cooldown.
        Positive cooldowns require an elapsed-time adapter and cannot be dropped.
        Native SequenceUsed accepts the emitted sequence name in this dialogue.
        """
        if sid in stack or len(stack) >= 64:
            raise ValueError('Cyclic dialogue sequence availability: ' + ' -> '.join((*stack, sid)))
        if sid not in self.sequences:
            raise ValueError('Unregistered dialogue sequence availability: ' + sid)
        record = self.sequences[sid]
        source, entry = record['source'], record['entry']
        cooldown = source.get('timeout', '0')
        if cooldown not in ('0', '-1'):
            raise ValueError('Unconverted dialogue sequence cooldown: ' + sid + ':' + cooldown)
        if entry.get('npc_entry_condition'):
            raise ValueError('Unconverted NPC dialogue condition')
        condition = self.compile(entry['entry_condition'] if expression is None else expression, (*stack, sid))
        if cooldown == '-1':
            unused = "!SequenceUsed('seq_" + sid + "')"
            condition = '(' + condition + ') AND ' + unused if condition else unused
        return condition

    def compile(self, expression, sequence_stack=()):
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
            if token == 'IsSeqAvailable':
                take('('); sid = take(); take(')')
                if not re.fullmatch(r'\d+', sid):
                    raise ValueError('Expected literal dialogue sequence identity')
                # Stage nested bindings separately: a failed outer expression
                # must not leave graph ports behind.
                nested = QuestConditions([], self.functions, self.registered_items,
                                         self.participant_assets, self.sequences, self.area_assets, self.context_entities)
                nested.quests = self.quests
                record = self.sequences.get(sid)
                if record and (record['source'].get('type', '0') != '0'
                               or record['source'].get('group', '0') != '0'
                               or record['source'].get('skill_check_difficulty_id', '')
                               or record['source'].get('reputation', '0') != '0'):
                    raise ValueError('Unconverted referenced sequence selection: ' + sid)
                value = nested.sequence_condition(sid, stack=sequence_stack)
                pending.update(nested.bindings)
                return '(' + (value or '1') + ')'
            if token in ENGINE_PREDICATES:
                take('('); take(')')
                name = 'condition_' + hashlib.sha256(('engine:' + token).encode()).hexdigest()[:20]
                pending[name] = dict(kind='engine_function', **ENGINE_PREDICATES[token])
                return "Port('" + name + "')"
            if token in ('IsActor', 'IsActorInside') and token in self.context_entities:
                take('('); argument = take(); take(')')
                if not argument.startswith("'") or argument[1:-1] not in self.context_entities[token]:
                    raise ValueError('Unregistered dialogue context entity: ' + argument)
                mapped = self.context_entities[token][argument[1:-1]]
                if not re.fullmatch(r'[A-Za-z_]\w*', mapped):
                    raise ValueError('Invalid native dialogue context entity')
                selector = ''
                if index < len(tokens) and tokens[index] == '[':
                    take('['); context = take(); take(']')
                    if not re.fullmatch(r'\d+', context) or int(context) > 255:
                        raise ValueError('Unsupported dialogue context index: ' + context)
                    selector = '[' + context + ']'
                # These predicates belong to the native expression evaluator.
                # Preserve its dynamic dialogue context instead of selecting a
                # fixed NPC from role order (which changes for NPC-led dialogue).
                return token + "('" + mapped + "')" + selector
            if token == 'IsActorInside':
                take('('); area = take(); take(')')
                if not area.startswith("'") or area[1:-1] not in self.area_assets:
                    raise ValueError('Unregistered dialogue area: ' + area)
                # Source context indexes are not soul IDs or sorted role indexes.
                # Require the caller's resolved context; never guess the actor.
                take('['); selector = take(); take(']')
                subject = selector[1:-1] if selector.startswith("'") else selector
                if subject not in self.participant_assets:
                    raise ValueError('Unregistered area predicate participant: ' + selector)
                binding = dict(kind='area_check', asset=self.participant_assets[subject],
                               area=self.area_assets[area[1:-1]])
                identity = repr(sorted(binding.items()))
                name = 'condition_' + hashlib.sha256(identity.encode()).hexdigest()[:20]
                pending[name] = binding
                return "Port('" + name + "')"
            if token == 'GetActorMoney':
                take('('); take(')'); take('['); selector = take(); take(']')
                if not re.fullmatch(r'\d+', selector) or int(selector) > 255:
                    raise ValueError('Unsupported money predicate context')
                operator, amount = take(), take()
                if operator not in ('==','!=','>=','<=','>','<') or not re.fullmatch(r'-?\d+(?:\.\d+)?', amount):
                    raise ValueError('Unsupported money predicate comparison')
                # Native shipped dialogues use this same dynamic context ABI.
                return 'GetActorMoney()['+selector+'] '+operator+' '+amount
            if token in ('var', 'gvar', 'GetAmountOfActorItems', 'CountOfActorItems'):
                take('('); argument = take(); take(')')
                if not argument.startswith("'"):
                    raise ValueError('Expected literal dialogue scalar argument')
                value = argument[1:-1]
                if token in ('var','gvar'):
                    if not re.fullmatch(r'[A-Za-z_]\w*', value):
                        raise ValueError('Invalid dialogue variable')
                    native = token
                else:
                    if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value):
                        raise ValueError('Invalid dialogue item identity')
                    if value.lower() not in self.registered_items:
                        raise ValueError('Unregistered dialogue item: ' + value)
                    native = 'CountOfActorItems'
                participant = None
                if index < len(tokens) and tokens[index] == '[':
                    take('['); selector = take(); take(']')
                    if token in ('var','gvar') or not selector.startswith("'") or selector[1:-1] not in self.participant_assets:
                        raise ValueError('Unregistered inventory predicate participant: ' + selector)
                    participant = self.participant_assets[selector[1:-1]]
                operator, number = take(), take()
                if operator not in ('==', '!=', '>=', '<=', '>', '<') or not re.fullmatch(r'-?\d+(?:\.\d+)?', number):
                    raise ValueError('Unconverted dialogue scalar comparison')
                if participant is not None:
                    if not re.fullmatch(r'\d+', number) or int(number) > 2147483646:
                        raise ValueError('Inventory predicate requires a bounded nonnegative integer count')
                    identity = ':'.join((participant, value.lower(), operator, number))
                    name = 'condition_' + hashlib.sha256(identity.encode()).hexdigest()[:20]
                    pending[name] = dict(kind='inventory_comparison', asset=participant,
                                         item=value.lower(), operator=operator, amount=int(number))
                    return "Port('" + name + "')"
                return native + '(' + argument + ') ' + operator + ' ' + number
            # Skald dialogue expressions use numeric boolean literals in native
            # shipped sequences. Lua-style lowercase words are not this ABI.
            if token in ('0', '1'): return token
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
