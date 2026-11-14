"""Reference model of a KCD1 quest and its conversations, read from the source tables only.

It answers "what would KCD1 do" for the exhaustive walk: objective order, the
start/complete/cancel effects of each dialogue sequence, hand-in windows,
rewards and the controller's quest rules. It never reads converted XML and does
not share code with the lowerings it is compared against.

KCD1 engine behaviour that the tables do not state is listed in `RULES`; a
walk result is only as good as these readings. Anything outside them raises
Unsupported instead of guessing.
"""
import copy
import re

from . import Unsupported

RULES = {
    'join': 'a transition target starts when every enabled predecessor is Completed and it is Unchanged or Canceled',
    'constant_true': "an objective with condition '1' completes when it is started and its counted tracked assets are satisfied",
    'manual': "an objective with an empty or '0' condition never completes by itself",
    'tracked_item': 'a tracked item asset is satisfied by count items of the class at or above min_health in the player inventory',
    'tracked_npc': 'a tracked NPC asset with count 1 is satisfied when that soul is dead',
    'reward': 'completing an objective pays each of its immediate reward rows once',
    'end': 'a transition into Quest:End completes a started quest',
    'open_inventory': 'OpenInventory completes each listed objective that is Started and whose tracked items the player hands over, and takes exactly the tracked count',
    'effects': 'sequence effects run in order_by order at sequence exit and each condition is read when its effect runs',
    'once': 'a sequence with timeout -1 can be used once',
    'ending': "a sequence goes to its next topic; without one it ends the topic when its flags are 0, otherwise the dialogue",
    'unprompted': 'a topic plays its first eligible sequence without a ui_prompt; prompted sequences are the player choices',
    'controller': 'the quest controller reacts to an objective state message in the same step',
    'cancel_quest': 'CancelQuest ends the quest as Canceled; its objectives are left as they are',
    'dead': 'a dead character cannot be talked to',
    'migration': 'a controller branch guarded by $__version.loaded < <version> migrates an old save and does not run in a new game',
}
STATES = ('Unchanged', 'Started', 'Completed', 'Failed', 'Canceled')
ACTIONS = {'1': 'start', '2': 'complete', '3': 'cancel'}
TOKEN = re.compile(r"\s*(?:(AND\b|OR\b|&&?|\|\|?|!|\(|\))|([A-Za-z_]\w*)\s*\(([^()]*)\)|([A-Za-z_]\w*)|(\d+))")
_NAME = r"'([^'\\]*)'"
LIFECYCLE = re.compile(r"\s*QuestSystem\s*\.\s*(ActivateQuest|StartQuest)\s*\(\s*" + _NAME + r"\s*\)\s*;?\s*")
_OPEN = r"QuestSystem\s*\.\s*OpenInventory\s*\(\s*" + _NAME + r"\s*,\s*dc\s*\[\s*'(\w+)'\s*\]\s*\.\s*this\s*\.\s*id\s*((?:,\s*" + _NAME + r"\s*)+)\)\s*;?"
OPEN = re.compile(r"\s*" + _OPEN + r"\s*")
GUARDED = re.compile(r"\s*if\s+QuestSystem\s*\.\s*IsObjectiveStarted\s*\(\s*" + _NAME + r"\s*,\s*" + _NAME
                     + r"\s*\)\s*then\s+(" + _OPEN + r")\s*else\s+(" + _OPEN + r")\s*end\s*;?\s*")
MIGRATION = re.compile(r"\$__version\.loaded\s*<\s*\$enum:gameVersion\.\w+")
CONTROLLER = re.compile(r"\$(\w+)\.State\s*==\s*\$enum:ObjectiveState\.(\w+)\s*&\s*\$\1\.ObjectiveName\s*==\s*'(\w+)'")


def unquote(value):
    return value[1:-1] if len(value) > 1 and value[0] == value[-1] == '"' else value


def parse_script(script):
    """[('lifecycle', function, quest)] or [('window', quest, role, guard, then objectives, else objectives)]."""
    script = (script or '').replace('\r', ' ')
    if not script.strip(): return []
    calls, offset = [], 0
    while offset < len(script):
        match = LIFECYCLE.match(script, offset)
        if not match: break
        calls.append(('lifecycle', match.group(1), match.group(2))); offset = match.end()
    if calls and offset == len(script): return calls
    names = lambda text: re.findall(_NAME, text)
    single = OPEN.fullmatch(script)
    if single:
        return [('window', single.group(1), single.group(2), None, [], names(single.group(3)))]
    guarded = GUARDED.fullmatch(script)
    if guarded:
        first, second = OPEN.fullmatch(guarded.group(3)), OPEN.fullmatch(guarded.group(8))
        if first and second and guarded.group(1) == first.group(1) == second.group(1) and first.group(2) == second.group(2):
            return [('window', first.group(1), first.group(2), guarded.group(2), names(first.group(3)), names(second.group(3)))]
    raise Unsupported('KCD1 sequence script is not modeled: ' + script.strip())


def controller_rules(model):
    """[(objective, state, quest function)] from 'on objective message: if quest started then SetQuest'."""
    rules = []

    def visit(node, inside=False):
        op, attrs = node.get('op'), node.get('attributes', {})
        if op == 'IfCondition':
            if MIGRATION.fullmatch(unquote(attrs.get('condition', '')).strip()): return
            match = CONTROLLER.fullmatch(unquote(attrs.get('condition', '')).strip())
            children = node.get('children', [])
            guard = children[0] if len(children) == 1 else None
            then = [c for c in (guard or {}).get('children', []) if c.get('op') == 'Then']
            other = [c for c in (guard or {}).get('children', []) if c.get('op') == 'Else']
            actions = then[0].get('children', []) if len(then) == 1 else []
            if (match and guard and guard.get('op') == 'QuestCondition'
                    and unquote(guard['attributes'].get('function', '')) == 'IsQuestStarted'
                    and unquote(guard['attributes'].get('quest', '')) == model['quest']
                    and len(actions) == 1 and actions[0].get('op') == 'SetQuest'
                    and unquote(actions[0]['attributes'].get('questName', '')) == model['quest']
                    and not unquote(actions[0]['attributes'].get('objectiveName', ''))
                    and all(g.get('op') == 'Success' for c in other for g in c.get('children', []))):
                rules.append((match.group(3), match.group(2), unquote(actions[0]['attributes']['function'])))
                return
            raise Unsupported('KCD1 controller condition is not modeled: ' + attrs.get('condition', ''))
        if op in ('SetQuest', 'SetQuestObjective', 'QuestCondition', 'QuestObjectiveCondition', 'ExecuteLua', 'Function'):
            raise Unsupported('KCD1 controller operation is not modeled: ' + str(op))
        for child in node.get('children', []): visit(child)
    for document in (model.get('behavior_documents') or {}).values():
        for tree in document.get('trees', {}).values():
            visit(tree['root'])
    return rules


class Reference:
    def __init__(self, model, dialogues, quests=None):
        """quests: the declared state of every other quest the conditions read, e.g. {'q_huntPtacek': 'Completed'}."""
        self.quest = model['quest']
        self.other = dict(quests or {})
        tables = model['tables']
        rows = [r for r in tables['quest_objective']['rows']]
        self.names = {r['objective_id']: r['objective_name'] for r in rows}
        self.rows = {r['objective_name']: r for r in rows}
        nodes = model['graph']['nodes']
        begin = [i for i, n in nodes.items() if n['attributes'].get('Class') == 'Quest:Begin']
        end = [i for i, n in nodes.items() if n['attributes'].get('Class') == 'Quest:End']
        if len(begin) != 1 or len(end) > 1: raise Unsupported('Expected one KCD1 quest begin and at most one end')
        self.begin, self.end = begin[0], end[0] if end else None
        self.following, self.preceding = {}, {}
        for r in tables['quest_transition']['rows']:
            if r['enabled'] != 'True': continue
            for oid in (r['from_objective_id'], r['to_objective_id']):
                if oid not in self.names and oid not in (self.begin, self.end):
                    raise Unsupported('KCD1 transition names an unknown node: ' + oid)
            self.following.setdefault(r['from_objective_id'], []).append(r['to_objective_id'])
            self.preceding.setdefault(r['to_objective_id'], []).append(r['from_objective_id'])
        if any(r.get('is_exclusive') == 'True' for r in rows):
            raise Unsupported('Exclusive KCD1 objectives are not modeled')
        items = {r['quest_asset_id']: r for r in tables.get('quest_item', {}).get('rows', [])}
        npcs = {r['quest_asset_id']: r for r in tables.get('quest_npc', {}).get('rows', [])}
        self.tracked = {name: [] for name in self.rows}
        for r in tables.get('quest_tracked_asset', {}).get('rows', []):
            if r['count'] == '0' or not r.get('quest_asset_id'): continue      # a map marker, nothing to count
            name, asset = self.names[r['objective_id']], r['quest_asset_id']
            if asset in items and items[asset].get('item_id'):
                health = items[asset].get('min_health')
                self.tracked[name].append(dict(kind='item', item=items[asset]['item_id'].lower(), count=int(r['count']),
                                               minimum_health=float(health) if health not in ('', None) else 0.0))
            elif asset in npcs and npcs[asset].get('soul_id') and r['count'] == '1':
                self.tracked[name].append(dict(kind='npc', soul=npcs[asset]['soul_id'].lower()))
            else:
                raise Unsupported('KCD1 tracked asset is not modeled: ' + name + ' ' + asset)
        for r in rows:
            if (r.get('autocomplete_timeout_str') not in ('', '-1', None) or r.get('expiration_timeout_str') not in ('', '-1', None)
                    or r.get('time', '0') not in ('', '0') or (r.get('condition') or '').strip() not in ('', '0', '1')):
                raise Unsupported('KCD1 objective policy is not modeled: ' + r['objective_name'])
        self.rewards = {name: [] for name in self.rows}
        for table in sorted(t for t in tables if t.startswith('quest_reward')):
            for r in tables[table]['rows']:
                if r.get('is_immediate') != 'True' or r.get('is_exclusive') == 'True' or r.get('objective_id') not in self.names:
                    raise Unsupported('KCD1 reward row is not modeled: ' + table)
                kind = ('money' if table == 'quest_reward_money' else
                        ('soul_reputation' if r.get('soul_id') else 'faction_reputation') if table == 'quest_reward_reputation'
                        else table.removeprefix('quest_reward_'))
                self.rewards[self.names[r['objective_id']]].append(dict(kind=kind, table=table, row={
                    k: v for k, v in r.items() if k not in ('pos', 'quest_id') and v not in ('', None)}))
        self.rules = controller_rules(model)
        self.functions = {}
        self.sequences, self.topics, self.roots = {}, {}, []
        for index, dialogue in enumerate(dialogues):
            self.functions.update(dialogue.get('functions') or {})
            self.roots.append(dialogue['start_topic'])
            for tid, topic in dialogue['topics'].items():
                if tid in self.topics: raise Unsupported('KCD1 topic appears in two conversations: ' + tid)
                self.topics[tid] = [r['source']['sequence_id'] for r in topic['sequences']]
                for record in topic['sequences']:
                    source, sid = record['source'], record['source']['sequence_id']
                    if source.get('timeout', '0') not in ('0', '-1', ''):
                        raise Unsupported('KCD1 sequence cooldown is not modeled: ' + sid)
                    if record['entry'].get('npc_entry_condition'):
                        raise Unsupported('KCD1 NPC entry condition is not modeled: ' + sid)
                    script = parse_script(source.get('script'))
                    effects = sorted(record.get('effects') or [], key=lambda e: int(e['order_by']))
                    if script and effects:
                        raise Unsupported('KCD1 sequence with both a script and effects is not modeled: ' + sid)
                    for effect in effects:
                        if effect['action'] not in ACTIONS or effect['quest_id'] != model['quest_id']:
                            raise Unsupported('KCD1 sequence effect is not modeled: ' + sid)
                    self.sequences[sid] = dict(topic=tid, dialogue=index, once=source.get('timeout') == '-1',
                        prompted=bool(source.get('ui_prompt')), next=source.get('next', '0'), flags=source.get('flags', '0'),
                        condition=record['entry'].get('entry_condition') or '', script=script, effects=effects)
        self.state = dict(activated=False, quest='Unchanged', objectives={n: 'Unchanged' for n in self.rows},
                          used=[], dead=[], items={}, ledger=[], events=[], talk=None)

    # -- conditions

    def call(self, function, arguments):
        s = self.state
        if function.startswith('IsQuest') and len(arguments) == 1:
            wanted = function[len('IsQuest'):]
            if arguments[0] == self.quest:
                return s['activated'] if wanted == 'Activated' else s['quest'] == wanted
            if arguments[0] in self.other and wanted in ('Started', 'Completed', 'Canceled', 'Unchanged'):
                return self.other[arguments[0]] == wanted
        elif function.startswith('IsObjective') and len(arguments) == 2 and arguments[0] == self.quest and arguments[1] in self.rows:
            wanted = function[len('IsObjective'):]
            if wanted == 'TrackedCompleted': return self.tracked_completed(arguments[1])
            if wanted in STATES: return s['objectives'][arguments[1]] == wanted
        raise Unsupported('KCD1 condition is not modeled: ' + function + '(' + ', '.join(arguments) + ')')

    def condition(self, text, depth=0):
        text = (text or '').replace('\r', ' ').replace('\n', ' ').strip()
        if not text: return True
        if depth > 16: raise Unsupported('Recursive KCD1 condition function')
        tokens, offset = [], 0
        while offset < len(text):
            match = TOKEN.match(text, offset)
            if not match:
                if not text[offset:].strip(): break
                raise Unsupported('KCD1 condition is not modeled: ' + text)
            operator, name, arguments, word, number = match.groups()
            if name: tokens.append(('call', name, [a for a in re.findall(_NAME, arguments)]
                                    if re.fullmatch(r"\s*(?:" + _NAME + r"\s*(?:,\s*" + _NAME + r"\s*)*)?", arguments) else None))
            elif operator: tokens.append(({'&': 'AND', '&&': 'AND', '|': 'OR', '||': 'OR'}.get(operator, operator),))
            elif word: tokens.append(('word', word))
            else: tokens.append(('number', number))
            offset = match.end()
        position = 0

        def atom():
            nonlocal position
            if position >= len(tokens): raise Unsupported('KCD1 condition is incomplete: ' + text)
            token = tokens[position]; position += 1
            if token[0] == '!': return not atom()
            if token[0] == '(':
                value = either()
                if position >= len(tokens) or tokens[position][0] != ')': raise Unsupported('KCD1 condition is unbalanced: ' + text)
                position += 1
                return value
            if token[0] == 'call':
                if token[2] is None: raise Unsupported('KCD1 condition arguments are not modeled: ' + text)
                return self.call(token[1], token[2])
            if token[0] == 'word':
                if token[1] in ('true', 'TRUE'): return True
                if token[1] in ('false', 'FALSE'): return False
                if token[1] in self.functions: return self.condition(self.functions[token[1]], depth + 1)
            if token[0] == 'number' and token[1] in ('0', '1'): return token[1] == '1'
            raise Unsupported('KCD1 condition is not modeled: ' + text)

        def both():
            nonlocal position
            value = atom()
            while position < len(tokens) and tokens[position][0] == 'AND':
                position += 1
                right = atom(); value = value and right
            return value

        def either():
            nonlocal position
            value = both()
            while position < len(tokens) and tokens[position][0] == 'OR':
                position += 1
                right = both(); value = value or right
            return value
        value = either()
        if position != len(tokens): raise Unsupported('KCD1 condition is not modeled: ' + text)
        return value

    # -- tracked assets

    def held(self, requirement):
        return sum(s['amount'] for s in self.state['items'].get(requirement['item'], [])
                   if s['health'] >= requirement['minimum_health'])

    def satisfied(self, requirement):
        if requirement['kind'] == 'npc': return requirement['soul'] in self.state['dead']
        return self.held(requirement) >= requirement['count']

    def tracked_completed(self, name):
        if not self.tracked[name]: raise Unsupported('KCD1 objective has nothing tracked: ' + name)
        return all(self.satisfied(r) for r in self.tracked[name])

    # -- objectives

    def automatic(self, name):
        return (self.rows[name].get('condition') or '').strip() == '1'

    def start(self, name):
        s = self.state
        s['objectives'][name] = 'Started'; s['events'].append(('start', name))
        self.recheck(name)

    def recheck(self, name=None):
        for objective in ([name] if name else list(self.rows)):
            if (self.state['objectives'][objective] == 'Started' and self.automatic(objective)
                    and all(self.satisfied(r) for r in self.tracked[objective])):
                self.complete(objective)

    def complete(self, name):
        s = self.state
        s['objectives'][name] = 'Completed'; s['events'].append(('complete', name))
        for reward in self.rewards[name]:
            s['ledger'].append(dict(objective=name, kind=reward['kind'], row=dict(reward['row'])))
        for objective, state, function in self.rules:
            if objective == name and state == 'Completed' and s['quest'] == 'Started':
                if function != 'CancelQuest': raise Unsupported('KCD1 controller action is not modeled: ' + function)
                s['quest'] = 'Canceled'; s['events'].append(('cancel_quest', self.quest))
        oid = next(i for i, n in self.names.items() if n == name)
        self.advance(oid)

    def cancel(self, name):
        self.state['objectives'][name] = 'Canceled'; self.state['events'].append(('cancel', name))

    def advance(self, source):
        s = self.state
        done = lambda oid: s['quest'] == 'Started' if oid == self.begin else s['objectives'][self.names[oid]] == 'Completed'
        for target in self.following.get(source, []):
            if not all(done(p) for p in self.preceding[target]): continue
            if target == self.end:
                if s['quest'] == 'Started':
                    s['quest'] = 'Completed'; s['events'].append(('complete_quest', self.quest))
            elif s['objectives'][self.names[target]] in ('Unchanged', 'Canceled'):
                self.start(self.names[target])

    # -- the world outside conversations

    def set_items(self, items):
        self.state['items'] = copy.deepcopy(items)
        self.recheck()

    def kill(self, soul):
        self.state['dead'].append(soul.lower())
        self.recheck()

    # -- conversations

    def eligible(self, sid):
        sequence = self.sequences[sid]
        return self.condition(sequence['condition']) and not (sequence['once'] and sid in self.state['used'])

    def offered(self, topic=None):
        """(sequence the topic plays by itself or None, the player's choices) at the current or given topic."""
        topic = topic or self.state['talk']['topic']
        eligible = [s for s in self.topics[topic] if self.eligible(s)]
        unprompted = [s for s in eligible if not self.sequences[s]['prompted']]
        return (unprompted[0], []) if unprompted else (None, eligible)

    def begin_talk(self, dialogue):
        self.state['talk'] = dict(dialogue=dialogue, topic=self.roots[dialogue], window=None)

    def leave(self):
        self.state['talk'] = None

    def choose(self, sid):
        s, sequence = self.state, self.sequences[sid]
        talk = s['talk']
        if talk is None or talk['window'] is not None or sequence['topic'] != talk['topic'] or not self.eligible(sid):
            raise ValueError('KCD1 sequence is not available: ' + sid)
        if sid not in s['used']: s['used'].append(sid)
        for effect in sequence['effects']:
            if self.condition(effect['condition']):
                getattr(self, ACTIONS[effect['action']])(self.names[effect['objective_id']])
        for call in sequence['script']:
            if call[1 if call[0] == 'window' else 2] != self.quest:
                raise Unsupported('KCD1 script on another quest: ' + sid)
            if call[0] == 'lifecycle':
                if call[1] == 'ActivateQuest': s['activated'] = True
                else:
                    s['quest'] = 'Started'; s['events'].append(('start_quest', self.quest))
                    self.advance(self.begin)
            else:
                _, _, _, guard, then, otherwise = call
                listed = then if guard is not None and s['objectives'][guard] == 'Started' else otherwise
                # A window with nothing to take is not a player decision.
                if any(s['objectives'][o] == 'Started' for o in listed): talk['window'] = list(listed)
        if sequence['next'] != '0': talk['topic'] = sequence['next']
        elif sequence['flags'] == '0': talk['topic'] = self.roots[talk['dialogue']]
        else: talk['topic'] = None      # the dialogue ends

    def window(self, hand_over):
        s = self.state
        listed, s['talk']['window'] = s['talk']['window'], None
        if not hand_over: return
        for name in listed:
            if s['objectives'][name] != 'Started' or not self.tracked[name]: continue
            if not all(r['kind'] == 'item' and self.satisfied(r) for r in self.tracked[name]): continue
            for requirement in self.tracked[name]:
                wanted, kept = requirement['count'], []
                for stack in s['items'].get(requirement['item'], []):
                    used = min(stack['amount'], wanted) if stack['health'] >= requirement['minimum_health'] else 0
                    wanted -= used
                    if stack['amount'] - used: kept.append(dict(amount=stack['amount'] - used, health=stack['health']))
                if kept: s['items'][requirement['item']] = kept
                else: s['items'].pop(requirement['item'], None)
            self.complete(name)

    def snapshot(self):
        return copy.deepcopy(self.state)

    def restore(self, state):
        self.state = copy.deepcopy(state)
