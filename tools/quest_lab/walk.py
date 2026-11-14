"""Exhaustive walk: every reachable player path through a ported quest, checked against KCD1.

Two models take the same moves in lockstep:

    kcd1.Reference   what KCD1 does, from the source quest and dialogue tables
    graph.Graph      the lowered KCD2 container (quest, dialogues, delivery handlers)

After every move the walk compares objective states, quest state, the reward
ledger, the player's items, the conversation position and what the next
decision offers. A difference ends that branch and is reported with the path
that reached it; it is never retried or averaged away.

Moves: talk through one of the quest's conversations with a chosen stock of
the items the started objectives track (none, fresh, stale, one short, twice as
many, and each objective alone when several are started), every prompted choice,
hand over or close an open delivery window, leave at the root decision, and the
death of the quest giver. Player-side rules the walk itself assumes are `RULES`;
engine guesses are the scenario assumptions in `ASSUMED`.
"""
from collections import Counter
import copy
import hashlib
import json
import posixpath
import xml.etree.ElementTree as ET

from . import BudgetExceeded, Unsupported
from .graph import Graph
from .kcd1 import Reference, RULES as KCD1_RULES, STATES
from .objects import INVENTORY, SOUL
from .source import Source

RULES = {
    'leave': 'the player can leave a conversation only at its root decision or when a sequence ends it',
    'one_conversation': 'each talk runs one of the quest conversations; a topic that ends returns to that conversation',
    'stock': 'the player arrives with a chosen stock and puts leftovers away after the talk',
    'window': "in a delivery window the player hands over everything it asks for, or closes it (result 'Canceled')",
    'dead': 'a dead quest giver cannot be talked to',
    'observation': 'state is compared whenever the player can act; while the conversation plays a sequence by itself '
                   'only its position and the sequence it plays are compared (KCD1 completes a hand-in when the window '
                   'closes, the port when the next sequence accepts it)',
}
# The design's guesses (QUESTS-1-DESIGN.md 3.5), declared rather than defaulted.
ASSUMED = {
    'delivery.window_blocks_dialogue': True, 'delivery.result_after_close': 'persists',
    'delivery.unset_result': 'not_success', 'delivery.exactly_from_larger_stack': True,
    'delivery.amount_with_minimum_health': True, 'delivery.transfer': 'on_accept',
    'rewards.load_does_not_replay': True, 'soul_death.inactive_trigger': 'missed',
    'dialogue.nested_end_topic': 'root', 'dialogue.unprompted_sequence': 'first_eligible',
}
REWARD_KINDS = {'MoneyReward': 'money', 'SoulReputationReward': 'soul_reputation',
                'FactionReputationReward': 'faction_reputation'}
PLAYER, BAG, NPC_BAG = 'player', 'player-bag', 'giver-bag'


def canonical(path):
    return posixpath.normpath(path.replace('\\', '/')).lower()


QUEST_PORTS = {'available': None, 'started': 'Started', 'completed': 'Completed', 'failed': 'Failed', 'unchanged': 'Unchanged'}


def external_contracts(externals, states):
    """Graph contracts for the other quests the container reads, each in a declared state."""
    contracts = {}
    for name, ports in externals.items():
        if name not in states: raise ValueError('The walk world does not declare the state of ' + name)
        unknown = sorted(set(ports) - set(QUEST_PORTS))
        if unknown: raise Unsupported('Unmodeled output of external quest ' + name + ': ' + ', '.join(unknown))
        contracts[name] = dict(reason='Another quest, outside this walk; its state is declared by the walk world: ' + states[name],
                               inputs={}, outputs={p: 'bool' for p in ports},
                               values={p: states[name] != 'Unchanged' if p == 'available' else QUEST_PORTS[p] == states[name]
                                       for p in ports})
    return contracts


def slice_container(resources, entry, seeds):
    """The container reduced to the named instances, what they read and what they drive.

    A built Level holds every other quest of the campaign; the walk needs only this
    quest's closure. Another Quest the closure reads is cut off as an external: its
    inputs are dropped and its definition is left out, so the caller must declare its
    state. Returns ({path: bytes} for Source.blobs, kept node names, {external: ports read}).
    """
    files = {canonical(p): (p, b) for p, b in resources.items()}
    root = ET.fromstring(files[canonical(entry)][1])
    hosts = list(root.find('Skald'))
    if len(hosts) != 1 or hosts[0].tag not in ('Level', 'Project'):
        raise ValueError('Expected one Level or Project container')
    host = hosts[0]
    nodes = {n.get('Name'): n for n in host.findall('Nodes/*') if n.tag != 'Output'}
    missing = [s for s in seeds if s not in nodes]
    if missing: raise ValueError('Container has no instance ' + ', '.join(missing))
    sources = {name: {e.get('From', '').partition('.')[0] for e in n.findall('Edge')} & set(nodes) for name, n in nodes.items()}
    forward, queue = set(seeds), list(seeds)
    while queue:                                    # what the instances drive
        current = queue.pop()
        for name, read in sources.items():
            if current in read and name not in forward:
                forward.add(name); queue.append(name)
    kept, queue = set(forward), list(forward)
    while queue:                                    # what all of that reads
        for name in sources[queue.pop()]:
            if name not in kept:
                kept.add(name); queue.append(name)
    definitions = host.find('Definitions')
    defined = {}
    for definition in list(definitions if definitions is not None else ()):
        path = canonical(posixpath.join(posixpath.dirname(canonical(entry)), definition.get('File', '')))
        for found in (ET.fromstring(files[path][1]).iterfind('./Skald/*') if path in files else ()):
            defined[found.get('Name')] = (path, found.tag)
    # Reached only by reading: another quest (or an instance with no definition here) is not walked.
    externals = {name for name in kept - forward if nodes[name].tag not in defined and nodes[name].tag == name
                 or defined.get(nodes[name].tag, ('', ''))[1] == 'Quest'}
    changed = True
    while changed:                                  # drop what only the cut-off quests needed
        needed, queue = set(forward), list(forward)
        while queue:
            current = queue.pop()
            if current in externals: continue
            for name in sources[current]:
                if name not in needed:
                    needed.add(name); queue.append(name)
        changed, kept = needed != kept, needed
    externals &= kept
    container = host.find('Nodes')
    for node in list(container):
        if node.get('Name') not in kept: container.remove(node)
        elif node.get('Name') in externals:
            for child in list(node): node.remove(child)
    read = {name: sorted({e.get('From').partition('.')[2] for n in container for e in n.findall('Edge')
                          if e.get('From', '').partition('.')[0] == name}) for name in sorted(externals)}
    for child in [c for c in host if c.tag == 'Ports']: host.remove(child)
    tags, out = {nodes[n].tag for n in kept - externals}, {}

    def include(path):
        if path in out or path not in files: return
        out[path] = files[path][1]
        for dependency in ET.fromstring(files[path][1]).iterfind('./Skald/*/Definitions/Definition'):
            include(canonical(posixpath.join(posixpath.dirname(path), dependency.get('File', ''))))
    for definition in list(definitions if definitions is not None else ()):
        path = canonical(posixpath.join(posixpath.dirname(canonical(entry)), definition.get('File', '')))
        names = ({d.get('Name') for d in ET.fromstring(files[path][1]).iterfind('./Skald/*')} if path in files else set())
        if names & tags: include(path)
        else: definitions.remove(definition)
    out[canonical(entry)] = ET.tostring(root, encoding='utf-8')
    return out, sorted(kept), read


def stock_options(reference):
    """{label: items} for the item objectives that are started."""
    started = [n for n, s in reference.state['objectives'].items() if s == 'Started'
               and reference.tracked[n] and all(r['kind'] == 'item' for r in reference.tracked[n])]
    options = {'nothing': {}}
    if not started: return options

    def stock(objectives, scale=1, health=1.0, short=False):
        items = {}
        for index, requirement in enumerate(r for o in objectives for r in reference.tracked[o]):
            amount = requirement['count'] * scale - (1 if short and index == 0 else 0)
            level = health if health is not None else requirement['minimum_health'] / 2
            if amount > 0: items.setdefault(requirement['item'], []).append(dict(amount=amount, health=level))
        return {k: [dict(amount=sum(s['amount'] for s in v), health=v[0]['health'])] for k, v in items.items()}
    options['fresh'] = stock(started)
    if any(r['minimum_health'] > 0 for o in started for r in reference.tracked[o]):
        options['stale'] = stock(started, health=None)
    options['short'] = stock(started, short=True)
    options['surplus'] = stock(started, scale=2)
    if len(started) > 1:
        for objective in started: options['only ' + objective] = stock([objective])
    return options


class Walk:
    def __init__(self, source, container, quest, dialogues, model, source_dialogues, npc, aliases, other_quests=None,
                 waived=None, money=None, assumptions=None, limit=120, kill=True, identifier=lambda name: name,
                 contracts=None):
        """dialogues: instance names in the order of source_dialogues. aliases: {asset alias: 'player' or the npc soul}.

        waived: {(objective, reward kind): rows per completion the port is declared not to pay}.
        money: {KCD1 money_change_id: the Amount name the port must use}.
        """
        self.quest, self.dialogues, self.npc = quest, list(dialogues), npc.lower()
        self.reference = Reference(model, source_dialogues, other_quests)
        self.assumptions = dict(ASSUMED, **(assumptions or {}), **{'delivery.player_inventory': BAG})
        self.waived, self.money, self.limit, self.allow_kill = dict(waived or {}), money, limit, kill
        self.identifier = identifier
        objects = {PLAYER: {SOUL: {'properties': {'Inventory': BAG}}}, BAG: self.bag({}),
                   self.npc: {SOUL: {'properties': {'Inventory': NPC_BAG}}}, NPC_BAG: self.bag({})}
        self.graph = Graph(source, container, contracts, budget=10 ** 9, assets=dict(aliases), objects=objects,
                           assumptions=self.assumptions)
        missing = [d for d in self.dialogues if d not in self.graph.dialogues]
        if missing: raise ValueError('Container has no dialogue ' + ', '.join(missing))
        self.history = {d: sorted({name for tree in self.graph.dialogues[d].conditions.values()
                                   for name in self.sequence_references(tree)}) for d in self.dialogues}
        self.memo, self.stack = {}, set()
        self.mismatches, self.blocked, self.ends = [], [], {}
        self.transitions = self.truncated = self.loops = 0
        self.structure = self.check_structure()

    @staticmethod
    def bag(items):
        return {INVENTORY: {'queries': [dict(method='Items', arguments={}, result=copy.deepcopy(items))]}}

    @staticmethod
    def sequence_references(tree):
        import ast
        return [n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call) and n.func.id == 'SequenceUsed']

    def check_structure(self):
        """The lowered decisions must be the source topics: same sequences, order and prompts."""
        found, r = [], self.reference
        for index, name in enumerate(self.dialogues):
            dialogue = self.graph.dialogues[name]
            if dialogue.root != 'topic_' + r.roots[index]:
                found.append(dict(dialogue=name, field='root', kcd1=r.roots[index], lowered=dialogue.root))
            for topic, sequences in r.topics.items():
                if r.sequences[sequences[0]]['dialogue'] != index: continue
                decision = dialogue.decisions.get('topic_' + topic)
                lowered = None if decision is None else [s.get('Name') for s in decision.findall('Sequences/Sequence')]
                if lowered != ['seq_' + s for s in sequences]:
                    found.append(dict(dialogue=name, field='topic ' + topic, kcd1=sequences, lowered=lowered))
                    continue
                for sid in sequences:
                    if dialogue.prompted('seq_' + sid) != r.sequences[sid]['prompted']:
                        found.append(dict(dialogue=name, field='prompt of ' + sid, kcd1=r.sequences[sid]['prompted'],
                                          lowered=dialogue.prompted('seq_' + sid)))
        return found

    # -- the lowered side

    def settle(self):
        g = self.graph
        g.drain(); g.advance_to(g.now)

    def emu_items(self, items):
        self.graph.objects.replace(BAG, self.bag(items))

    def lowered(self):
        g, q = self.graph, self.quest
        objectives = {}
        for name in self.reference.rows:
            states = [s for s in STATES if g.value(q + '.' + self.identifier(name) + '_' + s)]
            objectives[name] = states[0] if len(states) == 1 else states
        ledger = Counter()
        amounts = set()
        for entry in g.world.state['ledger']:
            oid = entry['node'].rpartition('lowered_reward_')[2].removesuffix('_deferred')
            objective = self.reference.names.get(oid, entry['node'])
            for reward in entry['rewards']:
                ledger[(objective, REWARD_KINDS.get(reward['kind'], reward['kind']))] += 1
                if reward['kind'] == 'MoneyReward': amounts.add(reward.get('Amount'))
        active = [d for d in self.dialogues if g.dialogues[d].state['active']]
        talk = None
        if active:
            state = g.dialogues[active[0]].state
            talk = dict(dialogue=self.dialogues.index(active[0]),
                        topic=None if state['closing'] else state['decision'].removeprefix('topic_'),
                        window=g.world.state['window'] is not None)
        items = g.world.items(BAG)[1]
        return dict(objectives=objectives, activated=g.value(q + '.available'), started=g.value(q + '.started'),
                    completed=g.value(q + '.completed'), ledger=ledger, amounts=amounts, talk=talk,
                    items={k: sorted((s['amount'], s['health']) for s in v) for k, v in items.items()})

    def expected(self):
        s = self.reference.state
        ledger = Counter((e['objective'], e['kind']) for e in s['ledger'])
        completions = Counter(name for verb, name in s['events'] if verb == 'complete')
        for (objective, kind), rows in self.waived.items():
            ledger[(objective, kind)] -= rows * completions[objective]
        amounts = ({self.money[e['row']['money_change_id']] for e in s['ledger'] if e['kind'] == 'money'}
                   if self.money is not None else None)
        talk = s['talk'] and dict(dialogue=s['talk']['dialogue'], topic=s['talk']['topic'], window=s['talk']['window'] is not None)
        return dict(objectives=dict(s['objectives']), activated=s['activated'], started=s['quest'] == 'Started',
                    completed=s['quest'] == 'Completed', ledger=+ledger, amounts=amounts, talk=talk,
                    items={k: sorted((x['amount'], x['health']) for x in v) for k, v in s['items'].items()})

    def compare(self):
        want, got, found = self.expected(), self.lowered(), []
        moves = self.moves()
        if len(moves) == 1 and moves[0][0] == 'plays':      # not an observation point: see RULES['observation']
            for field in ('objectives', 'activated', 'started', 'completed', 'items', 'ledger', 'amounts'):
                got[field] = want[field]
        for name in want['objectives']:
            if want['objectives'][name] != got['objectives'][name]:
                found.append(dict(field='objective ' + name, kcd1=want['objectives'][name], lowered=got['objectives'][name]))
        for field in ('activated', 'started', 'completed', 'talk', 'items'):
            if want[field] != got[field]:
                kcd1 = want[field] if field != 'started' else str(want[field]) + ' (quest ' + self.reference.state['quest'] + ')'
                found.append(dict(field='quest ' + field if field in ('activated', 'started', 'completed') else field,
                                  kcd1=kcd1, lowered=got[field]))
        if +want['ledger'] != +got['ledger']:
            keys = sorted(set(want['ledger']) | set(got['ledger']))
            found.append(dict(field='rewards paid', kcd1={' '.join(k): want['ledger'][k] for k in keys if want['ledger'][k] != got['ledger'][k]},
                              lowered={' '.join(k): got['ledger'][k] for k in keys if want['ledger'][k] != got['ledger'][k]}))
        if want['amounts'] is not None and want['amounts'] != got['amounts']:
            found.append(dict(field='money rows', kcd1=sorted(want['amounts']), lowered=sorted(map(str, got['amounts']))))
        if not found and want['talk'] and want['talk']['topic'] and not want['talk']['window']:
            auto, choices = self.reference.offered()
            lowered_auto, lowered_choices = self.graph.dialogues[self.dialogues[want['talk']['dialogue']]].offered()
            offer = (auto and 'seq_' + auto, ['seq_' + c for c in choices])
            if offer != (lowered_auto, lowered_choices):
                found.append(dict(field='offered at topic ' + want['talk']['topic'], kcd1=offer, lowered=(lowered_auto, lowered_choices)))
        return found

    # -- joint state

    def snapshot(self):
        return self.reference.snapshot(), self.graph.snapshot()

    def restore(self, saved):
        self.reference.restore(saved[0]); self.graph.stack.clear(); self.graph.restore(saved[1])

    def key(self):
        r, g = self.reference.state, self.graph
        once = sorted(s for s in r['used'] if self.reference.sequences[s]['once'])
        left = dict(activated=r['activated'], quest=r['quest'], objectives=r['objectives'], used=once, dead=r['dead'],
                    items=r['items'], talk=r['talk'], paid=sorted(Counter(e['objective'] for e in r['ledger']).items()))
        world = copy.deepcopy(g.world.state)
        for entry in world['ledger']: entry.pop('time_us', None)
        right = dict(states=g.states, world=world, objects=g.objects.records, timers=sorted(t[2] for t in g.timers),
                     dialogues={d: dict(active=g.dialogues[d].state['active'], decision=g.dialogues[d].state['decision'],
                                        closing=g.dialogues[d].state['closing'],
                                        used=sorted(set(g.dialogues[d].state['used']) & set(self.history[d])))
                                for d in self.dialogues})
        return hashlib.sha256(json.dumps([left, right], sort_keys=True, default=str).encode()).hexdigest()

    # -- moves

    def moves(self):
        r = self.reference
        talk = r.state['talk']
        if talk is None:
            if self.npc in r.state['dead']: return []
            found = [('talk', label, index) for label in stock_options(r) for index in range(len(self.dialogues))]
            return found + ([('death',)] if self.allow_kill else [])
        if talk['window'] is not None: return [('hand over',), ('close window',)]
        if talk['topic'] is None: return [('leave',)]
        auto, choices = r.offered()
        if auto: return [('plays', auto)]
        found = [('choose', c) for c in choices]
        if talk['topic'] == r.roots[talk['dialogue']] or not found: found.append(('leave',))
        return found

    def apply(self, move):
        """Take the move in both models. Returns False when it changed nothing (nothing to say)."""
        r, g = self.reference, self.graph
        kind = move[0]
        if kind == 'talk':
            items = stock_options(r)[move[1]]
            r.set_items(items); self.emu_items(items); self.settle()
            r.begin_talk(move[2]); g.dialogues[self.dialogues[move[2]]].start()
            self.settle()
        elif kind in ('plays', 'choose'):
            dialogue = g.dialogues[self.dialogues[r.state['talk']['dialogue']]]
            r.choose(move[1]); dialogue.choose('seq_' + move[1])
            self.settle()
        elif kind in ('hand over', 'close window'):
            handler = g.world.state['window']
            if handler is None:
                raise Mismatch([dict(field='delivery window', kcd1='open for ' + ', '.join(r.state['talk']['window']), lowered=None)])
            r.window(kind == 'hand over')
            if kind == 'hand over' and g.world.can_hand_over(handler): g.world.resolve(handler, 'hand_over')
            else: g.world.resolve(handler, 'close', 'Canceled')
            self.settle()
        elif kind == 'leave':
            dialogue = g.dialogues[self.dialogues[r.state['talk']['dialogue']]]
            r.leave(); dialogue.end(); self.settle()
        elif kind == 'death':
            r.kill(self.npc); g.world.kill(self.npc); self.settle()
        return True

    def explore(self, path=()):
        key = self.key()
        if key in self.memo: return self.memo[key]
        if key in self.stack:
            self.loops += 1
            return 0
        saved, moves = self.snapshot(), self.moves()
        outside = self.reference.state['talk'] is None
        if len(path) >= self.limit:
            self.truncated += 1
            return 0
        self.stack.add(key)
        paths, productive = 0, False
        for move in moves:
            self.restore(saved)
            self.transitions += 1
            trail = (*path, move)
            try:
                self.apply(move)
                found = self.compare()
                if not found and move[0] == 'talk':
                    auto, choices = self.reference.offered()
                    if not auto and not choices:                 # nothing to say with this stock: not a path
                        continue
                if not found and move[0] == 'leave':
                    self.reference.set_items({}); self.emu_items({}); self.settle()
                    found = self.compare()
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
            if move[0] != 'death': productive = True
            paths += self.explore(trail)
        self.stack.discard(key)
        self.restore(saved)
        if outside and not productive:
            label = self.label()
            self.ends.setdefault(label, dict(paths=0, witness=self.describe(path), kcd1_events=self.events()))
            self.ends[label]['paths'] += 1
            paths += 1
        self.memo[key] = paths
        return paths

    def events(self):
        return [verb + ' ' + name for verb, name in self.reference.state['events']]

    def label(self):
        s = self.reference.state
        changed = ', '.join(n + '=' + v for n, v in s['objectives'].items() if v != 'Unchanged')
        return ('giver dead; ' if self.npc in s['dead'] else '') + 'quest ' + s['quest'] + ('; ' + changed if changed else '')

    def describe(self, path):
        names = {'talk': lambda m: 'talk (' + m[1] + ') ' + self.dialogues[m[2]].rpartition('_')[2]}
        return [names[m[0]](m) if m[0] in names else ' '.join(map(str, m)) for m in path]

    def run(self):
        paths = self.explore()
        self.restore_initial = None
        classes = Counter((m['move'].split(' ')[0], tuple(sorted(d['field'] for d in m['differences']))) for m in self.mismatches)
        status = ('PASS' if not (self.mismatches or self.blocked or self.truncated or self.structure or self.graph.unsupported)
                  else 'UNSUPPORTED' if not (self.mismatches or self.structure) else 'FAIL')
        return dict(quest=self.quest, status=status, paths=paths, states=len(self.memo), transitions=self.transitions,
                    loops_cut=self.loops, truncated=self.truncated, depth_limit=self.limit,
                    ends=[dict(state=k, **v) for k, v in sorted(self.ends.items())],
                    mismatch_count=len(self.mismatches),
                    mismatch_classes=[dict(move=k[0], fields=list(k[1]), count=n) for k, n in classes.most_common()],
                    mismatches=self.mismatches[:200], blocked=self.blocked[:200], structure=self.structure,
                    unsupported_nodes=self.graph.unsupported, assumptions=self.graph.world.report()['assumptions'],
                    kcd1_rules=KCD1_RULES, walk_rules=RULES, external=self.graph.contracts, nodes=len(self.graph.nodes), native_runtime_verified=False)


class Mismatch(Exception):
    pass


def table(results):
    lines = ['| quest | status | paths | states | moves checked | end states | mismatches | blocked | truncated |',
             '|---|---|---|---|---|---|---|---|---|']
    for r in results:
        lines.append('| %s | %s | %d | %d | %d | %d | %d | %d | %d |' % (
            r['quest'], r['status'], r['paths'], r['states'], r['transitions'], len(r['ends']), r['mismatch_count'],
            len(r['blocked']), r['truncated']))
    for r in results:
        lines += ['', '## ' + r['quest'], '', 'End states (KCD1 objective sequence of one path that reaches each):', '']
        for end in r['ends']:
            lines.append('- %s (%d joint states): %s' % (end['state'], end['paths'], ' > '.join(end['kcd1_events']) or 'nothing'))
        if r['mismatch_classes']:
            lines += ['', 'Mismatches by move and field:', '']
            for c in r['mismatch_classes']:
                first = next(m for m in r['mismatches'] if m['move'].split(' ')[0] == c['move']
                             and sorted(d['field'] for d in m['differences']) == c['fields'])
                lines.append('- %d x %s: %s' % (c['count'], c['move'], '; '.join(
                    '%s: KCD1 %s, lowered %s' % (d['field'], d['kcd1'], d['lowered']) for d in first['differences'])))
                lines.append('  - first path: ' + ' > '.join(first['path']))
        for item in r['structure']: lines.append('- structure: ' + json.dumps(item))
        for item in r['blocked'][:10]: lines.append('- blocked (%s): %s after %s' % (item['side'], item['error'], ' > '.join(item['path'])))
        for item in r['unsupported_nodes'][:10]: lines.append('- unsupported node: ' + json.dumps(item))
    return '\n'.join(lines) + '\n'
