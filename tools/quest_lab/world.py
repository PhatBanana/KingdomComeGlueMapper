"""Modeled native quest effects: rewards, soul deaths and item deliveries.

Every behaviour of the engine that is not established by retail data is a
named assumption (`ASSUMPTIONS`). A scenario has to declare the value it runs
under; reaching the behaviour without a declaration is UNSUPPORTED, never a
silent default. Declared assumptions are part of the graph fingerprint and of
the report, so a PASS always names what it assumed.

Nothing here computes an amount of money or reputation: a payout is the list
of reward rows the AddReward node names, kept in a ledger.
"""
import copy

from . import Unsupported
from .expressions import boolean


# name -> (allowed values, what the value means)
ASSUMPTIONS = {
    'delivery.player_inventory': (None,
        'identity of the inventory a delivery window takes items from (a binding, the engine uses the player)'),
    'delivery.window_blocks_dialogue': ((True,),
        'the dialogue does not evaluate its next decision while a delivery window is open'),
    'delivery.result_after_close': (('persists', 'resets'),
        'whether a handler keeps its DeliveryResult after AcceptDelivery or RejectDelivery'),
    'delivery.unset_result': (('not_success',),
        'a handler that has no result yet does not compare equal to DeliveryResult Success'),
    'delivery.exactly_from_larger_stack': ((True, False),
        "DeliveryMode 'Exactly' with Amount N accepts N items out of a larger stack"),
    'delivery.amount_with_minimum_health': ((True,),
        'Amount and MinimumHealth on one delivery class descriptor both apply'),
    'delivery.transfer': (('on_accept',),
        'the selected items leave the player when AcceptDelivery runs, not when the window closes'),
    'rewards.load_does_not_replay': ((True,),
        'loading a save does not fire State.OnCompleted again, so an AddReward on it pays once'),
    'soul_death.inactive_trigger': (('missed',),
        'a SoulDeathTrigger that is inactive when its soul dies does not fire later'),
    'area.inactive_trigger': (('missed',),
        'an AreaTrigger that is inactive when a soul enters or leaves does not fire later, and does not raise '
        'OnEnter for a soul already inside when it becomes active'),
    'dialogue.nested_end_topic': (('root',),
        'a sequence that ends its topic inside a nested decision returns to the root decision'),
    'dialogue.unprompted_sequence': (('first_eligible',),
        'a decision plays its first eligible sequence without a UiPrompt; prompted ones are the player choices'),
}
REWARDS = {'MoneyReward', 'SoulReputationReward', 'FactionReputationReward', 'StatReward', 'SkillReward',
           'ItemReward', 'PerkReward'}
# Retail Libs/concept/definitions.xml.
DELIVERY_RESULTS = ('Success', 'Canceled', 'WrongItems', 'MissingItems', 'StolenMismatch', 'QualityMismatch',
                    'PriceMismatch', 'Invalid')
DELIVERY_MODES = ('CanMore', 'CanLess', 'Exactly', 'Any', 'AnyInfinite')
KINDS = {'AddReward', 'SoulDeathTrigger', 'ItemDeliveryHandler', 'AreaTrigger'}
CONTROL = {'AddReward': {'AddReward'}, 'ItemDeliveryHandler': {'BeginDelivery', 'AcceptDelivery', 'RejectDelivery'}}
OUTPUTS = {'AddReward': {'OnAdded'}, 'SoulDeathTrigger': {'OnAllDeath', 'OnDeath'},
           'AreaTrigger': {'OnEnter', 'OnLeave', 'OnAllEnter', 'OnAllLeave'},
           'ItemDeliveryHandler': {'OnResultAvailable', 'OnAccept', 'OnReject', 'DeliveryResult'}}
INPUTS = {'AddReward': set(), 'SoulDeathTrigger': {'Souls', 'IsActive'}, 'ItemDeliveryHandler': {'ItemDelivery'},
          'AreaTrigger': {'Souls', 'Areas', 'IsActive'}}


def checked_assumptions(values):
    values = copy.deepcopy(values or {})
    if not isinstance(values, dict):
        raise ValueError('Assumptions must map names to values')
    for name, value in values.items():
        if name not in ASSUMPTIONS:
            raise ValueError('Unknown assumption: ' + str(name))
        allowed = ASSUMPTIONS[name][0]
        if allowed is None:
            if not isinstance(value, str) or not value:
                raise ValueError('Assumption needs an explicit identity: ' + name)
        elif not any(type(value) is type(a) and value == a for a in allowed):
            raise ValueError('Unsupported value for assumption ' + name + ': ' + repr(value))
    return values


# ---------------------------------------------------------------- items with health

def stacks(value, item):
    """[(amount, health)] of one class. A plain count has no health and cannot answer a health question."""
    held = value.get(item, 0)
    if type(held) is int:
        if held:
            raise Unsupported('A health descriptor needs inventory stacks with health: ' + item)
        return []
    return [(s['amount'], s['health']) for s in held]


def total(value, item):
    held = value.get(item, 0)
    return held if type(held) is int else sum(s['amount'] for s in held)


def eligible(value, descriptor):
    minimum = descriptor.get('minimum_health')
    if minimum is None:
        return total(value, descriptor['item_class'])
    return sum(amount for amount, health in stacks(value, descriptor['item_class']) if health >= minimum)


def take(value, descriptor):
    """Remove descriptor['amount'] eligible items, first listed stack first (emulator policy). Returns the stacks taken."""
    item, wanted, minimum = descriptor['item_class'], descriptor['amount'], descriptor.get('minimum_health')
    held = value.get(item, 0)
    if type(held) is int:
        if minimum is not None:
            raise Unsupported('A health descriptor needs inventory stacks with health: ' + item)
        value[item] = held - wanted
        if not value[item]: del value[item]
        return wanted
    taken, kept = [], []
    for stack in held:
        usable = stack['amount'] if minimum is None or stack['health'] >= minimum else 0
        used = min(usable, wanted)
        wanted -= used
        if used: taken.append(dict(amount=used, health=stack['health']))
        if stack['amount'] - used: kept.append(dict(amount=stack['amount'] - used, health=stack['health']))
    if wanted:
        raise ValueError('Not enough eligible items to take: ' + item)
    if kept: value[item] = kept
    else: del value[item]
    return taken


def give(value, item, taken):
    held = value.get(item, 0)
    if type(taken) is int:
        if type(held) is not int:
            raise Unsupported('Cannot add a plain count to stacks with health: ' + item)
        value[item] = held + taken
    else:
        if type(held) is int:
            if held: raise Unsupported('Cannot add stacks with health to a plain count: ' + item)
            held = []
        value[item] = [*held, *copy.deepcopy(taken)]


# ---------------------------------------------------------------- the modeled effects

class World:
    def __init__(self, graph, assumptions=None):
        self.graph = graph
        self.assumptions = checked_assumptions(assumptions)
        self.used = set()
        self.state = dict(ledger=[], dead=[], deliveries={}, window=None, inside=[])

    def assume(self, name):
        if name not in self.assumptions:
            raise Unsupported('Scenario must declare assumption ' + name + ': ' + ASSUMPTIONS[name][1])
        self.used.add(name)
        return self.assumptions[name]

    # -- loading

    def audit(self, name, node):
        g, kind, element = self.graph, node['kind'], node['element']
        bound = set(node['values']) | set(node['constants']) | {a.get('Name') for a in element.findall('Asset')}
        for port in sorted(bound - INPUTS[kind]):
            g.issue(name, 'Unsupported input: ' + port)
        for port in sorted(INPUTS[kind] - bound):
            g.issue(name, 'Missing explicit value input: ' + port)
        if kind == 'AddReward':
            rewards = element.findall('Rewards/*')
            if len(element.findall('Rewards')) != 1 or not rewards:
                g.issue(name, 'AddReward needs one Rewards list')
            for reward in rewards:
                if reward.tag not in REWARDS or not reward.attrib or len(reward):
                    g.issue(name, 'Unsupported reward: ' + reward.tag)

    # -- rewards

    def pay(self, name):
        g = self.graph
        rows = [dict(kind=r.tag, **dict(sorted(r.attrib.items()))) for r in g.nodes[name]['element'].findall('Rewards/*')]
        entry = dict(id=len(self.state['ledger']) + 1, node=name, time_us=g.now, rewards=rows)
        self.state['ledger'].append(entry)
        g.record('reward_added', id=entry['id'], node=name, rewards=copy.deepcopy(rows), boundary='modeled_reward_ledger')
        g.emit(name + '.OnAdded')

    # -- deaths

    def souls(self, name):
        value = self.graph._args(name)
        found = value['Souls']
        found = [found] if isinstance(found, str) else found
        if not isinstance(found, list) or not found or any(not isinstance(s, str) or not s for s in found):
            raise Unsupported('SoulDeathTrigger needs explicit soul identities: ' + name)
        return found, boolean(value['IsActive'])

    def kill(self, soul):
        g = self.graph
        if not isinstance(soul, str) or not soul:
            raise ValueError('A death needs an explicit soul identity')
        if soul in self.state['dead']:
            raise ValueError('Soul is already dead: ' + soul)
        events, missed = [], []
        self.state['dead'].append(soul)
        for name, node in g.nodes.items():
            if node['kind'] != 'SoulDeathTrigger': continue
            watched, active = self.souls(name)
            if soul not in watched: continue
            if not active:
                if self.assume('soul_death.inactive_trigger') == 'missed': missed.append(name)
                continue
            events.append(name + '.OnDeath')
            if all(s in self.state['dead'] for s in watched): events.append(name + '.OnAllDeath')
        g.record('soul_death', soul=soul, events=events, missed=missed, boundary='explicit_scenario_event')
        for event in reversed(events): g.emit(event)
        g.drain()

    # -- areas

    def identities(self, name, port):
        found = self.graph._arg(name, port)
        found = [found] if isinstance(found, str) else found
        if not isinstance(found, list) or not found or any(not isinstance(s, str) or not s for s in found):
            raise Unsupported(self.graph.nodes[name]['kind'] + ' needs explicit identities for ' + port + ': ' + name)
        return found

    def area(self, soul, area, event):
        """A soul enters or leaves an area: a scenario outcome, never computed from positions."""
        g, inside = self.graph, self.state['inside']
        if any(not isinstance(v, str) or not v for v in (soul, area)) or event not in ('enter', 'leave'):
            raise ValueError('An area event needs a soul, an area and enter or leave')
        if ([soul, area] in inside) == (event == 'enter'):
            raise ValueError('Soul is ' + ('already' if event == 'enter' else 'not') + ' inside: ' + soul + ' ' + area)
        if event == 'enter': inside.append([soul, area])
        else: inside.remove([soul, area])
        events, missed = [], []
        for name, node in g.nodes.items():
            if node['kind'] != 'AreaTrigger': continue
            souls, areas = self.identities(name, 'Souls'), self.identities(name, 'Areas')
            if soul not in souls or area not in areas: continue
            if not boolean(g._arg(name, 'IsActive')):
                if self.assume('area.inactive_trigger') == 'missed': missed.append(name)
                continue
            present = [s for s in souls if any([s, a] in inside for a in areas)]
            if event == 'enter':
                events.append(name + '.OnEnter')
                if len(present) == len(souls): events.append(name + '.OnAllEnter')
            else:
                events.append(name + '.OnLeave')
                if not present: events.append(name + '.OnAllLeave')
        g.record('area_' + event, soul=soul, area=area, events=events, missed=missed, boundary='explicit_scenario_event')
        for found in reversed(events): g.emit(found)
        g.drain()

    # -- deliveries

    def handler(self, name):
        return self.state['deliveries'].setdefault(name, dict(phase='idle', result=None, delivery=None))

    def result(self, name):
        return self.handler(name)['result']

    def delivery(self, name):
        value = self.graph._arg(name, 'ItemDelivery')
        if not isinstance(value, dict) or set(value) != {'descriptors', 'inventory', 'filters', 'mode', 'labels'}:
            raise Unsupported('ItemDeliveryHandler needs a CreateItemDelivery value: ' + name)
        if value['mode'] != 'Exactly':
            raise Unsupported('Only DeliveryMode Exactly is modeled: ' + name)
        if any('minimum_health' in d for d in value['descriptors']):
            self.assume('delivery.amount_with_minimum_health')
        return value

    def player_items(self):
        inventory = self.assume('delivery.player_inventory')
        return inventory, self.items(inventory)

    def items(self, inventory):
        from .objects import INVENTORY
        facets = copy.deepcopy(self.graph.objects.records.get(inventory, {}))
        matches = [q for q in facets.get(INVENTORY, {}).get('queries', []) if q['method'] == 'Items' and q['arguments'] == {}]
        if len(matches) != 1:
            raise Unsupported('A delivery needs an explicit Items snapshot of ' + str(inventory))
        return facets, matches[0]['result']

    def satisfiable(self, delivery, items):
        """Whether the player can fill every row. Rows of one class draw from the same stacks."""
        trial = copy.deepcopy(items)
        for descriptor in delivery['descriptors']:
            held = eligible(trial, descriptor)
            if held < descriptor['amount']:
                return False
            if held > descriptor['amount'] and not self.assume('delivery.exactly_from_larger_stack'):
                return False
            take(trial, descriptor)
        return True

    def deliver(self, name, port):
        g, state = self.graph, self.handler(name)
        if port == 'BeginDelivery':
            if self.state['window'] is not None:
                raise Unsupported('A delivery window is already open: ' + self.state['window'])
            state.update(phase='open', result=None, delivery=self.delivery(name))
            self.state['window'] = name
            g.record('delivery_opened', node=name, delivery=copy.deepcopy(state['delivery']),
                     boundary='window awaits an explicit player outcome')
            return
        if state['phase'] != 'resolved':
            raise Unsupported(port + ' without a closed delivery window: ' + name)
        after = self.assume('delivery.result_after_close')
        if port == 'AcceptDelivery':
            if state['result'] != 'Success':
                raise Unsupported('AcceptDelivery after a result other than Success is not modeled: ' + name)
            self.assume('delivery.transfer')
            source, (facets, items) = self.assume('delivery.player_inventory'), self.player_items()[1]
            target = state['delivery']['inventory']
            target_facets, target_items = self.items(target)
            moved = []
            for descriptor in state['delivery']['descriptors']:
                taken = take(items, descriptor)
                give(target_items, descriptor['item_class'], taken)
                moved.append(dict(item_class=descriptor['item_class'], amount=descriptor['amount'], taken=taken))
            g.objects.replace(source, facets)
            g.objects.replace(target, target_facets)
            g.record('delivery_accepted', node=name, source=source, target=target, moved=moved,
                     boundary='modeled_item_transfer')
            event = name + '.OnAccept'
        else:
            g.record('delivery_rejected', node=name, result=state['result'])
            event = name + '.OnReject'
        state.update(phase='idle', delivery=None, result=state['result'] if after == 'persists' else None)
        g.emit(event)

    def resolve(self, name, outcome, result=None):
        """The player's action in the open window: hand over what it asks for, or close it with a result."""
        g = self.graph
        if self.state['window'] != name:
            raise ValueError('No open delivery window on ' + str(name))
        state = self.handler(name)
        self.assume('delivery.window_blocks_dialogue')
        if outcome == 'hand_over':
            if result is not None: raise ValueError('A hand-over has no explicit result')
            inventory, (_, items) = self.player_items()
            if not self.satisfiable(state['delivery'], items):
                raise ValueError('The player does not hold what the delivery asks for: ' + name)
            result = 'Success'
        elif outcome == 'close':
            if result not in DELIVERY_RESULTS or result == 'Success':
                raise ValueError('Closing a window needs an explicit result other than Success')
        else:
            raise ValueError('Unknown delivery outcome: ' + str(outcome))
        state.update(phase='resolved', result=result)
        self.state['window'] = None
        g.record('delivery_resolved', node=name, outcome=outcome, result=result, boundary='explicit_player_outcome')
        g.emit(name + '.OnResultAvailable')
        g.drain()

    def can_hand_over(self, name):
        state = self.handler(name)
        if state['phase'] != 'open': raise ValueError('No open delivery window on ' + str(name))
        return self.satisfiable(state['delivery'], self.player_items()[1][1])

    def gate_dialogue(self):
        if self.state['window'] is not None:
            self.assume('delivery.window_blocks_dialogue')
            raise ValueError('A delivery window is open; resolve it before the dialogue continues: ' + self.state['window'])

    # -- persistence and reporting

    def snapshot(self):
        return copy.deepcopy(self.state)

    def restore(self, state):
        if state['ledger'] and any(n['kind'] == 'AddReward' for n in self.graph.nodes.values()):
            self.assume('rewards.load_does_not_replay')
        self.state = copy.deepcopy(state)

    def report(self):
        return dict(ledger=copy.deepcopy(self.state['ledger']), dead=list(self.state['dead']),
                    inside=copy.deepcopy(self.state['inside']),
                    deliveries=copy.deepcopy(self.state['deliveries']), open_window=self.state['window'],
                    assumptions={k: dict(value=v, meaning=ASSUMPTIONS[k][1], used=k in self.used)
                                 for k, v in sorted(self.assumptions.items())})
