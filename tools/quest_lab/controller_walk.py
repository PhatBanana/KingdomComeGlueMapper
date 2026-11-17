"""Exhaustive walk of converted controller trees together with their quest graph (layer 2 of converter C2).

Two models take the same moves in lockstep:

    SpecReference   what KCD1 does to the objectives: the source quest tables as
                    `quest_conversion_ledger.walk_spec` states them, plus the quest
                    operations of the *source* controller tree
    graph.Graph     the emitted Skald quest with the controller bridge wired in, and
    behavior.Behavior  the emitted behaviour trees, sending AI concept signals into
                    that bridge and reading its game contexts

There are two kinds of run. `objectives` walks the quest graph alone over the
closure of the main path. `tree` runs one emitted tree with the quest graph: every
engine outcome the tree waits for (a move that succeeds or fails, a gate that opens
or closes, a search that finds something or nothing, a Lua gate, a message that is
processed or not) is a move, and so is every objective outcome the rest of the
game supplies.

Checked while walking:
  * every signal an emitted tree sends is, at the same place in the source tree, a
    quest operation; the reference applies that source operation, the lowered graph
    receives the signal through the bridge, and the objective states must agree;
  * every game context an emitted tree reads has, at the same place in the source
    tree, a quest condition; its value on the reference must equal the context;
  * after every move, all objective states and the quest state.

Engine outcomes are never chosen for the engine: each is a named move in the path
(`Move@<node>: fail`). What the lab assumes about nodes between outcomes is the
`behavior.*` assumptions it declares; the report lists the ones a run used. The
readings of KCD1 it relies on are `RULES`. Nothing here is native-runtime evidence.
"""
from collections import Counter
import copy
import hashlib
import json
import re

from . import BudgetExceeded, Unsupported
from .behavior import Behavior
from .engine_nodes import outputs
from .expressions import duration
from .graph import Graph
from .objects import INVENTORY, SOUL

RULES = {
    'join_all': 'an objective whose incoming transitions come from non-exclusive objectives starts when all of them are '
                'Completed and it is Unchanged or Canceled',
    'join_any': 'an objective whose incoming transitions come from exclusive objectives starts when one of them '
                'completes; that completion cancels the exclusive siblings that are Unchanged or Started',
    'constant': "an objective with condition '1' completes when it starts",
    'expression': 'an objective with a condition completes when it is Started and the condition holds; conditions are '
                  'read again after every change',
    'timed': 'a timed objective completes when its duration has passed since it started',
    'supplied': 'external, tracked and unestablished objectives complete only when the walk supplies the outcome '
                '(a controller tree that is not emitted, a dialogue or the tracked items)',
    'end': 'the quest completes when the join into Quest:End is satisfied',
    'set': 'a controller SetQuestObjective sets the objective state whatever it was, and the controller sees the '
           'result in the same step',
    'engine_variable': 'a variable a tree reads and nothing in it declares belongs to the engine (the NPC brain); '
                       'the walk starts it false and may set it true',
    'engine_lock': 'a lock a tree waits on and no emitted tree writes is written by the engine; the walk may open it',
    'reduction': 'in a tree run, the objectives the tree neither reads nor writes advance in one fixed order and in one '
                 'move (`rest of the quest advances`), which stops as soon as an objective the tree touches changes '
                 'state or gets a new outcome to supply; the tree runs between those moves',
    'scope': 'a run moves only the objectives in its scope: the main path closure, or what the tree touches with '
             'everything that leads there; the others stay Unchanged',
}
STATES = ('Unchanged', 'Started', 'Completed', 'Failed', 'Canceled')
SUPPLIED = ('external', 'tracked_manual', 'tracked_auto', 'unestablished')
ASSUMED = {
    'behavior.gate.run_logic': 'halt_restarts', 'behavior.gate.engine_state': 'scenario',
    'behavior.external_lock.open_when': 'unlocked', 'behavior.external_lock.unset': 'locked',
    'behavior.lock.scope': 'controller_npc_global', 'behavior.synchronize': 'opens_at_count',
    'behavior.semaphore': 'counted_holders', 'behavior.atomic': 'not_interrupted',
    'behavior.fusebox': 'cleanup_by_result', 'behavior.fusebox.interrupted': 'on_fail',
    'behavior.loop_until': 'reached_succeeds_exhausted_fails', 'behavior.loop.body_failure': 'fails',
    'behavior.for.end_index': 'inclusive', 'behavior.record.unset_member': 'assignable', 'behavior.loop.instant_body': 'next_tick', 'behavior.area_listener': 'keeps_listening',
    'behavior.message.bare_word': 'string', 'behavior.context_check.missing_branch': 'succeeds',
    'rewards.load_does_not_replay': True, 'soul_death.inactive_trigger': 'missed', 'area.inactive_trigger': 'missed',
}
ACTIONS = {'StartObjective': 'start', 'CompleteObjective': 'complete', 'CancelObjective': 'cancel', 'FailObjective': 'fail'}
FUNCTIONS = {'IsObjectiveStarted': 'Started', 'IsObjectiveCompleted': 'Completed', 'IsObjectiveCanceled': 'Canceled',
             'IsObjectiveFailed': 'Failed', 'IsObjectiveUnchanged': 'Unchanged'}
CONDITION = re.compile(r"\s*(IsObjective\w+)\s*\(\s*'([^']*)'\s*,\s*'([^']*)'\s*\)\s*")
QUEST_CONDITION = re.compile(r"\s*IsQuest(Completed|Started)\s*\(\s*'([^']*)'\s*\)\s*")
PLAYER, BAG = 'player', 'player-bag'


class Mismatch(Exception):
    pass


class SpecReference:
    """The KCD1 objective graph of one quest, from the walk spec only."""

    def __init__(self, spec, other=None):
        self.quest = spec['quest']
        self.rows = {o['objective']: o for o in spec['main_path'] + spec['off_path']}
        self.main = [o['objective'] for o in spec['main_path']]
        self.end = spec.get('end_join')
        self.other = dict(other or {})
        self.successors = {}
        for name, row in self.rows.items():
            if isinstance(row['started_by'], dict):
                if row['started_by']['join'] not in ('all', 'any'):
                    continue                              # a mixed join is converter residue; it never starts here
                for predecessor in row['started_by']['after']:
                    self.successors.setdefault(predecessor, []).append(name)
        self.state = dict(quest='Unchanged', objectives={n: 'Unchanged' for n in self.rows}, deadlines={}, now=0,
                          events=[], other=dict(self.other))
        self.unmodelled = set()

    def snapshot(self):
        return copy.deepcopy(self.state)

    def restore(self, state):
        self.state = copy.deepcopy(state)

    # -- conditions

    def holds(self, text):
        match = CONDITION.fullmatch(text)
        if match and match[1] in FUNCTIONS and match[2] == self.quest and match[3] in self.rows:
            return self.state['objectives'][match[3]] == FUNCTIONS[match[1]]
        match = QUEST_CONDITION.fullmatch(text)
        if match and match[2] in self.state['other']:
            return self.state['other'][match[2]] == match[1]
        return None                                        # not a reading this reference has

    def read(self, operation):
        """Value of a source quest condition (`operation` from `source_operations`)."""
        if operation['quest'] != self.quest or operation['objective'] not in self.rows:
            raise Unsupported('Condition on a quest or objective outside the spec: %(quest)s.%(objective)s' % operation)
        return self.state['objectives'][operation['objective']] == operation['state']

    # -- transitions

    def begin(self):
        s = self.state
        s['quest'] = 'Started'; s['events'].append(('start_quest', self.quest))
        for name in self.successors.get('Quest:Begin', []):
            self.join(name)
        self.recheck()

    def join(self, name):
        s, row = self.state, self.rows[name]
        if s['objectives'][name] not in ('Unchanged', 'Canceled'): return
        done = [p == 'Quest:Begin' and s['quest'] == 'Started' or s['objectives'].get(p) == 'Completed'
                for p in row['started_by']['after']]
        if all(done) if row['started_by']['join'] == 'all' else any(done): self.start(name)

    def start(self, name):
        s, row = self.state, self.rows[name]
        s['objectives'][name] = 'Started'; s['events'].append(('start', name))
        s['deadlines'].pop(name, None)
        if row['completion'] == 'constant': self.complete(name)
        elif row['completion'] == 'timed':
            if row.get('clock') != 'GameTime': raise Unsupported('Timed objective on another clock: ' + name)
            s['deadlines'][name] = s['now'] + duration(row['duration'])
        self.recheck()

    def complete(self, name):
        s = self.state
        s['objectives'][name] = 'Completed'; s['events'].append(('complete', name))
        s['deadlines'].pop(name, None)
        for target in self.successors.get(name, []):
            join = self.rows[target]['started_by']
            if join['join'] == 'any':
                for sibling in join['after']:
                    if sibling != name and s['objectives'].get(sibling) in ('Unchanged', 'Started'):
                        self.set(sibling, 'Canceled', 'cancel')
        for target in self.successors.get(name, []): self.join(target)
        if self.end and name in self.end['after'] and s['quest'] == 'Started':
            done = [s['objectives'][p] == 'Completed' for p in self.end['after']]
            if all(done) if self.end['join'] == 'all' else any(done):
                s['quest'] = 'Completed'; s['events'].append(('complete_quest', self.quest))
        self.recheck()

    def set(self, name, state, verb):
        s = self.state
        s['objectives'][name] = state; s['events'].append((verb, name))
        s['deadlines'].pop(name, None)

    def apply(self, action, name):
        """A controller SetQuestObjective, or an outcome the walk supplies."""
        if name not in self.rows: raise Unsupported('Operation on an objective outside the spec: ' + name)
        if action == 'start': self.start(name)
        elif action == 'complete': self.complete(name)
        elif action == 'cancel': self.set(name, 'Canceled', 'cancel'); self.recheck()
        elif action == 'fail': self.set(name, 'Failed', 'fail'); self.recheck()
        else: raise Unsupported('Unknown objective action: ' + action)

    def recheck(self):
        changed = True
        while changed:
            changed = False
            for name, row in self.rows.items():
                if self.state['objectives'][name] != 'Started' or row['completion'] != 'expression': continue
                value = self.holds(row['condition'])
                if value is None: self.unmodelled.add(name)
                elif value:
                    self.complete(name); changed = True

    def set_other(self, quest, state):
        self.state['other'][quest] = state; self.state['events'].append((state.lower() + '_quest', quest))
        self.recheck()

    def next_deadline(self):
        return min(self.state['deadlines'].values(), default=None)

    def advance_to(self, now):
        s = self.state
        while s['deadlines'] and min(s['deadlines'].values()) <= now:
            name = min(s['deadlines'], key=lambda n: (s['deadlines'][n], n))
            s['now'] = s['deadlines'][name]
            self.complete(name)
        s['now'] = now

    # -- scope

    def closure(self, names):
        """The objectives and everything that can lead to them: join predecessors and condition operands."""
        found, queue = set(), [n for n in names if n in self.rows]
        while queue:
            name = queue.pop()
            if name in found: continue
            found.add(name)
            row = self.rows[name]
            if isinstance(row['started_by'], dict):
                queue += [p for p in row['started_by']['after'] if p in self.rows]
            match = CONDITION.fullmatch(row.get('condition', '') or '')
            if match and match[3] in self.rows: queue.append(match[3])
        return found

    def other_quests(self, scope):
        found = set()
        for name in scope:
            match = QUEST_CONDITION.fullmatch(self.rows[name].get('condition', '') or '')
            if match: found.add(match[2])
        return sorted(found)


def source_operations(root, quest):
    """{path below Root: operation} for the quest operations of a source tree (quest_import IR).

    Paths are child indexes joined by '/', '' for the Root itself; an emitted tree
    that passed the converter's shape check has the same paths.
    """
    found = {}

    def text(value):
        return value[1:-1] if len(value) > 1 and value[:1] == value[-1:] == '"' else value

    def own(value):
        value = text(value or '')
        return quest if value in ('', '$__object.name', '__object.name') else value

    def visit(node, path):
        a, op = node.get('attributes', {}), node['op']
        if op == 'SetQuestObjective':
            found[path] = dict(kind='set', quest=own(a.get('quest')), objective=text(a.get('objective', '')),
                               action=ACTIONS.get(text(a.get('function', '')), text(a.get('function', ''))))
        elif op == 'QuestObjectiveCondition':
            found[path] = dict(kind='condition', quest=own(a.get('quest')), objective=text(a.get('objective', '')),
                               state=FUNCTIONS.get(text(a.get('function', '')), text(a.get('function', ''))))
        elif op == 'QuestObjectiveGate':
            state = text(a.get('objectiveState', ''))
            found[path] = dict(kind='gate', quest=own(a.get('questName')), objective=text(a.get('objectiveName', '')),
                               # KCD1 gate state AfterReset pairs with the condition state Unchanged (converter rule).
                               state='Unchanged' if state == 'AfterReset' else state,
                               negate=text(a.get('NegateTo', 'false')) == 'true')
        elif op in ('SetQuest', 'QuestCondition'):
            found[path] = dict(kind='quest', operation=op, attributes={k: text(v) for k, v in a.items()})
        for index, child in enumerate(node.get('children', [])):
            visit(child, (path + '/' if path else '') + str(index))
    visit(root, '')
    return found


class ControllerWalk:
    def __init__(self, source, entry, quest, spec, behavior=None, tree=None, operations=None, wiring=None,
                 identifier=lambda name: name, other=None, assumptions=None, limit=200, states=200000, budget=200000,
                 this=None, lua=None, aliases=None, scope=None):
        """behavior: (file name, XML bytes) holding `tree`; operations: `source_operations` of that tree.

        wiring: the converter's bridge rows, used only to name what a signal reached in a mismatch.
        other: {quest: state} for the other quests the spec's conditions read.
        """
        self.quest, self.spec, self.tree, self.identifier = quest, spec, tree, identifier
        self.reference = SpecReference(spec, other)
        self.assumptions = dict(ASSUMED, **(assumptions or {}))
        objects = {PLAYER: {SOUL: {'properties': {'Inventory': BAG}}},
                   BAG: {INVENTORY: {'queries': [dict(method='Items', arguments={}, result={})]}}}
        self.graph = Graph(source, entry, budget=budget, assets=dict(aliases or {}), objects=objects,
                           assumptions=self.assumptions)
        self.operations = dict(operations or {})
        self.wiring = {w['bridge_port']: w for w in (wiring or [])}
        self.limit, self.state_limit = limit, states
        self.behavior, self.engine_variables, self.engine_locks, self.structure = None, [], [], []
        if tree is not None:
            name, blob = behavior
            self.behavior = Behavior(name, blob, self.graph, lua=lua)
            if tree not in self.behavior.trees: raise ValueError('No emitted tree named ' + tree)
            self.this = dict(this or dict(id='npc:' + tree, name='npc:' + tree))
            self.structure = self.check_structure()
            self.engine_variables = self.find_engine_variables()
            self.behavior.set_variables(dict({'this': self.this, '__player': PLAYER, '__object': dict(id='controller', name=quest)},
                                             **{v: False for v in self.engine_variables}))
        touched = {o['objective'] for o in self.operations.values() if o.get('objective') in self.reference.rows}
        self.visible = touched
        self.scope = self.reference.closure(scope if scope is not None else touched if tree is not None
                                            else self.reference.main)
        self.other_quests = self.reference.other_quests(self.scope)
        for name in self.other_quests: self.reference.state['other'].setdefault(name, 'Unchanged')
        self.order = {n: i for i, n in enumerate(self.reference.main + sorted(set(self.reference.rows) - set(self.reference.main)))}
        self.memo, self.stack = {}, set()
        self.mismatches, self.blocked, self.ends = [], [], {}
        self.transitions = self.truncated = self.loops = 0
        self.mark = 0
        self.task = None

    # -- structure

    def node(self, path):
        return self.behavior.nodes.get(self.tree + ('/' + path if path else ''))

    def check_structure(self):
        """Each source quest operation has the emitted form at its place, and no other node has one."""
        found = []
        want = {'set': 'SendAIConceptSignal_', 'condition': 'GameContextCheck', 'gate': 'GameContextBarrier'}
        for path, operation in sorted(self.operations.items()):
            node = self.node(path)
            if operation['kind'] == 'quest':
                found.append(dict(node=path, problem='quest-level operation is not modelled by the walk', source=operation))
            elif node is None or not node.tag.startswith(want[operation['kind']]):
                found.append(dict(node=path, problem='source %s has no %s here' % (operation['kind'], want[operation['kind']]),
                                  emitted=None if node is None else node.tag, source=operation))
            elif operation['kind'] == 'set' and operation['action'] not in ('start', 'complete', 'cancel', 'fail'):
                found.append(dict(node=path, problem='source objective function is not modelled', source=operation))
        prefix = self.tree + '/'
        for path, node in self.behavior.nodes.items():
            if path != self.tree and not path.startswith(prefix): continue
            if node.tag.startswith('SendAIConceptSignal_') or node.tag in ('GameContextCheck', 'GameContextBarrier'):
                if path[len(prefix):] not in self.operations:
                    found.append(dict(node=path[len(prefix):], problem='emitted quest access without a source operation',
                                      emitted=node.tag))
        return found

    def find_engine_variables(self):
        prefix = self.tree + '/'
        declared = {n.get('name') for n in self.behavior.declarations[self.tree]}
        written, read = set(), set()
        for path, node in self.behavior.nodes.items():
            if path != self.tree and not path.startswith(prefix): continue
            written.update(outputs(node) if node.tag == 'GraphSearch' else ())
            for attribute in ('condition', 'expressions'):
                if node.tag in ('IfGate', 'IfCondition', 'IfElseCondition', 'While') and node.get(attribute):
                    read.update(re.findall(r'\$([A-Za-z_]\w*)', re.sub(r"'[^']*'", '', node.get(attribute))))
        return sorted(v for v in read - declared - written - {'this', '__player', '__object'}
                      if not v.startswith(('__link_', 'enum')))

    # -- the lowered side

    def port(self, name):
        return self.quest + '.' + name

    def settle(self):
        g = self.graph
        for _ in range(64):
            g.drain(); g.advance_to(g.now)
            if self.behavior is None: return
            before = (json.dumps(g.states, sort_keys=True, default=str), self.behavior.state_key())
            self.behavior.pump()
            g.drain(); g.advance_to(g.now)
            if before == (json.dumps(g.states, sort_keys=True, default=str), self.behavior.state_key()): return
        raise BudgetExceeded('The graph and the tree did not settle')

    def lowered(self):
        g = self.graph
        objectives = {}
        for name in self.reference.rows:
            states = [s for s in STATES if g.value(self.port(self.identifier(name) + '_' + s))]
            objectives[name] = states[0] if len(states) == 1 else states
        return dict(objectives=objectives, started=bool(g.value(self.port('started'))),
                    completed=bool(g.value(self.port('completed'))))

    def begin(self):
        self.graph.fire(self.port('activate')); self.graph.fire(self.port('start'))
        self.reference.begin()
        self.settle()
        self.observe()

    def observe(self):
        """Replay what the tree did since the last move on the reference, in order, and compare."""
        found, g = [], self.graph
        records, self.mark = g.trace[self.mark:], len(g.trace)
        prefix = (self.tree or '') + '/'
        for record in records:
            kind = record.get('kind')
            if kind not in ('behavior_signal', 'game_context_check', 'game_context_gate'): continue
            path = record['node'][len(prefix):] if record['node'].startswith(prefix) else ''
            operation = self.operations.get(path)
            if kind == 'behavior_signal':
                reached = self.wiring.get(record['notification'], {})
                if not operation or operation['kind'] != 'set':
                    found.append(dict(field='signal at ' + path, kcd1='no quest operation', lowered=reached.get('quest_port')))
                    continue
                if operation['quest'] != self.quest:
                    raise Unsupported('Operation on another quest: %(quest)s.%(objective)s' % operation)
                self.reference.apply(operation['action'], operation['objective'])
            else:
                if not operation or operation['kind'] not in ('condition', 'gate'):
                    found.append(dict(field='context read at ' + path, kcd1='no quest condition', lowered=record['context']))
                    continue
                want = self.reference.read(operation)
                got = record['result']
                if kind == 'game_context_gate':
                    if operation['kind'] != 'gate' or record['negation'] != operation['negate']:
                        found.append(dict(field='gate at ' + path, kcd1=operation, lowered=dict(negation=record['negation'])))
                        continue
                if want != got:
                    found.append(dict(field='condition at ' + path,
                                      kcd1='%s.%s is %s: %s' % (operation['quest'], operation['objective'], operation['state'], want),
                                      lowered='%s: %s' % (self.wiring.get(record['context'], {}).get('quest_port', record['context']), got)))
        want, got = self.reference.state, self.lowered()
        for name, state in want['objectives'].items():
            if got['objectives'][name] != state:
                found.append(dict(field='objective ' + name, kcd1=state, lowered=got['objectives'][name]))
        for field, value in (('started', want['quest'] == 'Started'), ('completed', want['quest'] == 'Completed')):
            if got[field] != value:
                found.append(dict(field='quest ' + field, kcd1='%s (quest %s)' % (value, want['quest']), lowered=got[field]))
        return found

    # -- joint state

    def snapshot(self):
        return (self.reference.snapshot(), self.graph.snapshot(),
                self.behavior.snapshot() if self.behavior is not None else None, self.mark)

    def restore(self, saved):
        self.reference.restore(saved[0]); self.graph.stack.clear(); self.graph.restore(saved[1])
        if self.behavior is not None:
            self.behavior.restore(saved[2])
            self.task = next(iter(self.behavior.tasks), None)
        self.mark = len(self.graph.trace)

    def key(self):
        r, g = self.reference.state, self.graph
        left = dict(quest=r['quest'], objectives=r['objectives'], other=r['other'],
                    deadlines={n: d - r['now'] for n, d in r['deadlines'].items()})
        right = dict(states=g.states, timers=sorted((t[0] - g.now, t[2]) for t in g.timers
                                                    if g.generations.get(t[2]) == t[3]),
                     tree=self.behavior.state_key() if self.behavior is not None else None)
        return hashlib.sha256(json.dumps([left, right], sort_keys=True, default=str).encode()).hexdigest()

    # -- moves

    def quest_moves(self):
        r = self.reference
        if r.state['quest'] != 'Started': return []
        found = []
        for name in sorted(self.scope, key=self.order.get):
            row, state = r.rows[name], r.state['objectives'][name]
            if state == 'Started' and row['completion'] in SUPPLIED: found.append(('complete', name))
            elif state == 'Unchanged' and row['started_by'] == 'external': found.append(('start', name))
        for quest in self.other_quests:
            if r.state['other'].get(quest) != 'Completed': found.append(('other quest', quest))
        if self.behavior is None: return found
        seen, hidden = self.split(found)
        return seen + ([('rest of the quest advances',)] if hidden else [])      # RULES['reduction']

    def split(self, moves):
        seen = [m for m in moves if m[0] in ('complete', 'start') and m[1] in self.visible]
        return seen, [m for m in moves if m not in seen]

    def all_quest_moves(self):
        behavior, self.behavior = self.behavior, None
        try: return self.quest_moves()
        finally: self.behavior = behavior

    def advance_rest(self):
        """Hidden outcomes in their fixed order until the tree could notice a difference."""
        def view():
            seen, hidden = self.split(self.all_quest_moves())
            return seen, {n: self.reference.state['objectives'][n] for n in self.visible}, hidden
        before = view()
        for _ in range(len(self.reference.rows) * 2 + 8):
            now = view()
            if not now[2] or now[:2] != before[:2]: return
            self.apply(now[2][0])
            found = self.observe()
            if found: raise Mismatch(found)
        raise BudgetExceeded('The rest of the quest did not come to rest')

    def deadlines(self):
        found = [self.graph.next_deadline(), self.reference.next_deadline(),
                 self.behavior.next_deadline() if self.behavior is not None else None]
        return [d for d in found if d is not None]

    def tree_moves(self):
        b = self.behavior
        if b is None: return []
        if self.task is None: return [('tree starts',)]      # the NPC can get the tree in any quest state
        found = []
        order = {n: i for i, n in enumerate(b.tasks)}
        for name, boundary in b.boundaries():
            for outcome in boundary['outcomes']:
                found.append(('engine', order[name], boundary['node'], boundary['operation'], outcome))
        for name, path, operation, logic in b.open_gates():
            if logic == 'Halt': found.append(('engine closes', order[name], path, operation))
        for variable in self.engine_variables:
            if b.variables.get(variable) is False and self.waits_on_variable(variable):
                found.append(('engine sets', variable))
        for key in self.waiting_locks():
            found.append(('engine opens lock', key))
        if any(t['status'] == 'tick' for t in b.tasks.values()): found.append(('engine ticks',))
        return found

    def waits_on_variable(self, variable):
        b = self.behavior
        return any(t['status'] == 'gate' and '$' + variable in b.nodes[t['frames'][-1]['path']].get('condition', '')
                   for t in b.tasks.values())

    def waiting_locks(self):
        b, found = self.behavior, []
        written = {n.get('LockName') for n in b.nodes.values() if n.tag == 'SetExternalLock'}
        for name, task in b.tasks.items():
            if task['status'] != 'gate': continue
            node = b.nodes[task['frames'][-1]['path']]
            if node.tag != 'ExternalLock' or node.get('SemaphoreName') in written: continue
            variables, _ = b._environment(name, task['frames'][-1])
            key = b._lock_key(name, task, node, 'SemaphoreName', variables)
            if key not in found: found.append(key)
        return found

    def moves(self):
        found = self.quest_moves() + self.tree_moves()
        if self.deadlines(): found.append(('time',))
        return found

    def apply(self, move):
        r, g, b = self.reference, self.graph, self.behavior
        kind = move[0]
        g.steps = 0                                        # the budget is per move
        if kind in ('complete', 'start'):
            g.fire(self.port(kind + '_' + self.identifier(move[1])))
            r.apply(kind, move[1])
        elif kind == 'other quest':
            for port in ('activate', 'start', 'complete'):
                if move[1] + '.' + port in g.event_ports: g.fire(move[1] + '.' + port)
            r.set_other(move[1], 'Completed')
        elif kind == 'rest of the quest advances':
            self.advance_rest()
            return
        elif kind == 'tree starts':
            self.task = b.start(self.tree)
        elif kind == 'engine ticks': b.tick()
        elif kind == 'time':
            target = min(self.deadlines())
            g.advance_to(target); r.advance_to(target)
        elif kind == 'engine':
            name = list(b.tasks)[move[1]]
            values = None
            boundary = b.tasks[name]['boundary']
            if move[4] == 'match': values = {v: 'found:' + v for v in boundary['writes']}
            answer = b.nodes[boundary['node']].get('answer', '').removeprefix('$')
            if move[4] == 'processed' and answer: values = {answer: {}}
            b.resolve(name, move[4], values)
        elif kind == 'engine closes':
            b.close_gate(list(b.tasks)[move[1]], move[2])
        elif kind == 'engine sets':
            b.set_variables({move[1]: True}); b.pump()
        elif kind == 'engine opens lock':
            b.locks[move[1]] = self.assumptions['behavior.external_lock.open_when'] == 'locked'
            b.record('behavior_engine_lock', lock=move[1]); b.pump()
        self.settle()

    def describe(self, path):
        def one(move):
            if move[0] == 'engine': return '%s@%s: %s' % (move[3], move[2], move[4])
            if move[0] == 'engine closes': return '%s@%s: closes' % (move[3], move[2])
            return ' '.join(map(str, move))
        return [one(m) for m in path]

    def label(self):
        s = self.reference.state
        text = 'quest ' + s['quest']
        if self.behavior is not None and self.task is not None:
            text += '; tree ' + self.behavior.tasks[self.task]['status']
        return text

    def explore(self, path=()):
        if len(self.memo) >= self.state_limit:
            self.truncated += 1
            return 0
        key = self.key()
        if key in self.memo: return self.memo[key]
        if key in self.stack:
            self.loops += 1
            return 0
        if len(path) >= self.limit:
            self.truncated += 1
            return 0
        saved, moves = self.snapshot(), self.moves()
        self.stack.add(key)
        paths, productive = 0, False
        for move in moves:
            self.restore(saved)
            self.transitions += 1
            trail = (*path, move)
            try:
                self.apply(move)
                found = self.observe()
            except Mismatch as error:
                found = error.args[0]
            except (Unsupported, BudgetExceeded) as error:
                self.blocked.append(dict(path=self.describe(trail), side='unsupported', error=str(error)))
                continue
            except (ValueError, KeyError) as error:
                self.blocked.append(dict(path=self.describe(trail), side='error', error=type(error).__name__ + ': ' + str(error)))
                continue
            if found:
                self.mismatches.append(dict(path=self.describe(trail), move=self.describe([move])[0], differences=found,
                                            kcd1_events=self.events()))
                continue
            if move[0] != 'time' or self.key() != key: productive = True
            paths += self.explore(trail)
        self.stack.discard(key)
        self.restore(saved)
        if not productive:
            label = self.label()
            self.ends.setdefault(label, dict(paths=0, witness=self.describe(path), kcd1_events=self.events()))
            self.ends[label]['paths'] += 1
            paths += 1
        self.memo[key] = paths
        return paths

    def events(self):
        return [verb + ' ' + name for verb, name in self.reference.state['events']]

    def run(self):
        paths, start = 0, []
        try:
            self.begin()
        except (Unsupported, BudgetExceeded, ValueError, KeyError) as error:
            self.blocked.append(dict(path=['begin'], side='unsupported' if isinstance(error, (Unsupported, BudgetExceeded)) else 'error',
                                     error=type(error).__name__ + ': ' + str(error)))
        else:
            start = self.observe()
            if start:
                self.mismatches.append(dict(path=['begin'], move='begin', differences=start, kcd1_events=self.events()))
            else:
                paths = self.explore()
        unsupported = [u for u in self.graph.unsupported if u['node'].startswith(self.quest + '.')]
        prefix = (self.tree or '') + '/'
        tree_unsupported = ([u for u in self.behavior.unsupported if u['node'] == self.tree or u['node'].startswith(prefix)]
                            if self.behavior is not None else [])
        classes = Counter((m['move'].split('@')[0].split(' ')[0], tuple(sorted(d['field'].split(' at ')[0].split(' ')[0]
                                                                              for d in m['differences']))) for m in self.mismatches)
        problems = self.mismatches or self.structure
        review = self.blocked or self.truncated or unsupported or tree_unsupported
        reached = sorted(l for l in self.ends if l.startswith('quest Completed'))
        used = {k: v for k, v in self.graph.world.report()['assumptions'].items() if v['used']}
        return dict(kind='tree' if self.tree else 'objectives', quest=self.quest, tree=self.tree,
                    status='FAIL' if problems else 'UNSUPPORTED' if review else 'PASS',
                    paths=paths, states=len(self.memo), transitions=self.transitions, loops_cut=self.loops,
                    truncated=self.truncated, depth_limit=self.limit,
                    ends=[dict(state=k, **v) for k, v in sorted(self.ends.items())],
                    reaches_quest_end=bool(reached),
                    mismatch_count=len(self.mismatches),
                    mismatch_classes=[dict(move=k[0], fields=list(k[1]), count=n) for k, n in classes.most_common()],
                    mismatches=self.mismatches[:100], blocked=self.blocked[:100], blocked_count=len(self.blocked),
                    structure=self.structure, unsupported_nodes=unsupported + tree_unsupported,
                    unsupported_outside_quest=len(self.graph.unsupported) - len(unsupported),
                    scope=sorted(self.scope, key=self.order.get), visible=sorted(self.visible),
                    other_quests=self.other_quests, engine_variables=self.engine_variables,
                    reference_unmodelled=sorted(self.reference.unmodelled),
                    quest_operations=len(self.operations), assumptions_used=used,
                    native_runtime_verified=False)


def expected_end(spec, result):
    """An objectives run must reach Quest:End with the spec's end states completed."""
    problems = []
    if not result['reaches_quest_end']: problems.append('no path reaches Quest:End')
    for end in result['ends']:
        if not end['state'].startswith('quest Completed'): continue
        done = {e.split(' ', 1)[1] for e in end['kcd1_events'] if e.startswith('complete ')}
        missing = sorted(set(spec['expected_end_states']) - done)
        if missing: problems.append('Quest:End reached without ' + ', '.join(missing))
    return problems


def table(results):
    lines = ['| run | status | paths | joint states | moves checked | end states | mismatches | blocked | truncated |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in results:
        lines.append('| %s | %s | %d | %d | %d | %d | %d | %d | %d |' % (
            r['tree'] or 'objectives (quest graph alone)', r['status'], r['paths'], r['states'], r['transitions'],
            len(r['ends']), r['mismatch_count'], r['blocked_count'], r['truncated']))
    for r in results:
        lines += ['', '## ' + (r['tree'] or 'objectives'), '']
        lines.append('Scope (%d objectives): %s' % (len(r['scope']), ', '.join(r['scope']) or 'none'))
        if r['engine_variables']: lines.append('Engine variables: ' + ', '.join(r['engine_variables']))
        for end in r['ends']:
            lines.append('- end `%s` (%d joint states): %s' % (end['state'], end['paths'],
                                                               ' > '.join(end['witness'][-12:]) or 'at the start'))
        for problem in r.get('end_problems', []): lines.append('- end check: ' + problem)
        for c in r['mismatch_classes']:
            first = next(m for m in r['mismatches'])
            lines.append('- %d x mismatch after %s (%s)' % (c['count'], c['move'], ', '.join(c['fields'])))
        for m in r['mismatches'][:3]:
            lines.append('  - ' + '; '.join('%s: KCD1 %s, lowered %s' % (d['field'], d['kcd1'], d['lowered'])
                                           for d in m['differences'][:4]))
            lines.append('    path: ' + ' > '.join(m['path'][-10:]))
        for item in r['structure']: lines.append('- structure: ' + json.dumps(item, default=str))
        reasons = Counter(b['error'] for b in r['blocked'])
        for reason, count in reasons.most_common(6): lines.append('- blocked x%d: %s' % (count, reason))
        for item in r['unsupported_nodes'][:8]: lines.append('- unsupported node: ' + json.dumps(item))
        if r['reference_unmodelled']:
            lines.append('- KCD1 conditions the reference does not read (those objectives never complete by themselves): '
                         + ', '.join(r['reference_unmodelled']))
        if r['assumptions_used']:
            lines.append('- assumptions used: ' + ', '.join('%s=%s' % (k, v['value']) for k, v in sorted(r['assumptions_used'].items())))
    return '\n'.join(lines) + '\n'


def summary(results):
    return dict(runs=len(results), status=dict(Counter(r['status'] for r in results)),
                paths=sum(r['paths'] for r in results), states=sum(r['states'] for r in results),
                transitions=sum(r['transitions'] for r in results),
                ends=sum(len(r['ends']) for r in results), mismatches=sum(r['mismatch_count'] for r in results),
                blocked=sum(r['blocked_count'] for r in results), truncated=sum(r['truncated'] for r in results))


def run_retail(kcd1, kcd2, quest, spec, work, with_quests=(), output=None, progress=lambda *a: None, **options):
    """Convert `quest` with C1 (quest graph) and C2 (controller), then walk the graph alone and every emitted tree."""
    from pathlib import Path
    from campaign_compile import wire_bridge
    from campaign_quest_graph import objective_identifier
    import quest_controller_conversion as c2
    import quest_conversion_ledger as c1
    from .source import Source
    progress('convert', 'objectives')
    graph = c1.convert(kcd1, kcd2, [quest], list(with_quests))
    progress('convert', 'controller')
    run = c2.convert(kcd1, kcd2, quest, Path(work) / 'c2', with_quests)
    files = dict(graph['files'])
    wire_bridge(files, graph['project'], run['bridges'], run['conversion'])
    files.update({n.removeprefix('Quests/'): b for n, b in run['bridges'].items() if n.startswith('Quests/')})
    for path in sorted((Path(work) / 'c2' / 'types').glob('*.xml')): files['AI/' + path.name] = path.read_bytes()
    own = 'libs/ai/quests/' + quest.lower() + '.xml'
    document = next((name, blob) for name, blob in run['behaviors'].items()
                    if name.lower().endswith('/quests/' + quest.lower() + '.xml'))
    files[document[0]] = document[1]
    source = Source.blobs(files)
    emitted = [t['tree'] for t in run['conversion']['trees']
               if t['document'] == own and t['native_emitted'] and t['owner'] == quest]
    common = dict(identifier=objective_identifier, wiring=run['conversion']['wiring'],
                  aliases=options.pop('aliases', None) or player_aliases(files), **options)
    results = []
    progress('walk', 'objectives')
    result = ControllerWalk(source, graph['project'], quest, spec, **common).run()
    result['end_problems'] = expected_end(spec, result)
    if result['end_problems'] and result['status'] == 'PASS': result['status'] = 'FAIL'
    results.append(result)
    trees = run['model']['behavior_documents'][own]['trees']
    for tree in emitted:
        progress('walk', tree)
        results.append(ControllerWalk(source, graph['project'], quest, spec, behavior=document, tree=tree,
                                      operations=source_operations(trees[tree]['root'], quest), **common).run())
    report = dict(schema=1, quest=quest, summary=summary(results), runs=results, rules=RULES,
                  trees_not_emitted=sorted(set(trees) - set(emitted)), native_runtime_verified=False,
                  scope='C1 quest graph and C2 emitted controller trees, built in memory from retail sources; KCD1 reference '
                        'from the walk spec and the source controller trees')
    if output is not None:
        output = Path(output); output.mkdir(parents=True, exist_ok=True)
        (output / 'controller-walk.json').write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
        (output / 'controller-walk.md').write_text(table(results), encoding='utf-8')
    return report


def player_aliases(files):
    """Every asset alias the quest files name is bound to the walk's player (the only soul it has)."""
    import xml.etree.ElementTree as ET
    found = {}
    for blob in files.values():
        try: root = ET.fromstring(blob)
        except ET.ParseError: continue
        for asset in root.iter('Asset'):
            if asset.get('Alias'): found.setdefault(asset.get('Alias'), PLAYER)
    return found
