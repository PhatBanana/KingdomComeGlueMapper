"""Lower a source hand-in window to native item deliveries.

KCD1 opens the hand-in window from a dialogue exit script:

    QuestSystem.OpenInventory('<quest>', dc['<ROLE>'].this.id, '<objective>', ...)

optionally as `if QuestSystem.IsObjectiveStarted('<quest>', '<objective>') then
<call> else <call> end`. The window takes the tracked items of the listed
objectives that are started, and completes them. The sequences of the next
decision then branch on "a listed objective is completed".

KCD2 has no such Lua call. Its idiom (retail
Quests/Final/Barbora/trosecko/poi_trosecko/zlodej_zeli/kvasene_zeli.xml and its
dialogue) is an ItemDeliveryHandler with a fixed descriptor list:

    sequence trigger  -> BeginDelivery
    next decision     -> EntryCondition "Port('<result>') == Enum('DeliveryResult','Success')"
    chosen sequence   -> trigger -> AcceptDelivery / RejectDelivery
    OnAccept          -> the quest effects

A delivery has a fixed descriptor list, so one delivery is emitted per group of
objectives that are started together: objectives started by the same dialogue
sequence form a group, every other listed objective is its own group. The
begin, accept and reject triggers each run down one priority chain of `If`
gates (group started?), so exactly one handler acts per conversation. The chain
order is the script's order, which makes the source `if ... else` the first
gate of the chain.

`plan` reads only the staged dialogue, its container, the quest definition and
`campaign_quest_tracking.plan`; item class, count and minimum health are the
tracking plan's, so tracking and delivery cannot disagree. Anything it cannot
prove leaves the dialogue pending and `bind` refuses it.

Not runtime-verified. See `ASSUMPTIONS`.
"""
import re
import string
import xml.etree.ElementTree as ET

from campaign_dialogue_effects import predicate
from campaign_dialogue_lifecycle import add_trigger, container_nodes, declare_port, host_of, quest_port
from campaign_quest_graph import all_of, constant, edge, identifier, objective_identifier, xml

PREFIX = 'lowered_delivery_'
BEGIN, ACCEPT, REJECT = 'delivery_begin', 'delivery_accept', 'delivery_reject'
RESULT, STARTED = 'delivery_result_', 'delivery_started_'
SUCCESS = "Enum('DeliveryResult','Success')"
DESCRIPTORS = 'wh::entitymodule::HomogenousItemDescriptors'
LABELS = 'wh::framework::LocalizedStrings'
ASSUMPTIONS = (
    'the dialogue waits for the delivery window before it evaluates the next decision (retail relies on it)',
    'a handler keeps its last DeliveryResult; the started-check in the outcome condition discards a stale Success',
    "DeliveryMode 'Exactly' with Amount N accepts N items out of a larger stack",
    'the source window completes an objective exactly when its tracked count is handed over',
    'objectives of one group are always started together, so a group is never partly started',
)

_NAME = r"'([A-Za-z_][\w ]*)'"
_NPC = r"dc\s*(?:\[\s*'(\w+)'\s*\]|\.\s*(\w+))\s*\.\s*this\s*\.\s*id"
_CALL = (r"QuestSystem\s*\.\s*OpenInventory\s*\(\s*" + _NAME + r"\s*,\s*(" + _NPC + r")\s*((?:,\s*" + _NAME
         + r"\s*)+)\)\s*;?")
_GUARD = r"QuestSystem\s*\.\s*IsObjectiveStarted\s*\(\s*" + _NAME + r"\s*,\s*" + _NAME + r"\s*\)"
SINGLE = re.compile(r"\s*(" + _CALL + r")\s*")
BRANCHED = re.compile(r"\s*if\s+\(?\s*" + _GUARD + r"\s*\)?\s*then\s+(" + _CALL + r")\s*else\s+(" + _CALL
                      + r")\s*end\s*;?\s*")


def _call(text):
    match = re.fullmatch(_CALL, text.strip())
    return dict(quest=match.group(1), role=match.group(3) or match.group(4),
                objectives=re.findall(_NAME, match.group(5)))


def parse(script):
    """dict(quest, role, branches=[dict(guard, objectives)]) or None."""
    single = SINGLE.fullmatch(script)
    if single:
        call = _call(single.group(1))
        return dict(quest=call['quest'], role=call['role'], branches=[dict(guard=None, objectives=call['objectives'])])
    branched = BRANCHED.fullmatch(script)
    if not branched:
        return None
    groups = branched.groups()
    guard_quest, guard = groups[0], groups[1]
    # Each embedded call contributes the same number of groups; split on that.
    width = (len(groups) - 2) // 2
    first, second = _call(groups[2]), _call(groups[2 + width])
    if not (guard_quest == first['quest'] == second['quest']) or first['role'] != second['role']:
        return None
    return dict(quest=first['quest'], role=first['role'],
                branches=[dict(guard=guard, objectives=first['objectives']),
                          dict(guard=None, objectives=second['objectives'])])


def _fold(op, items):
    flat = set()
    for item in items:
        if item[0] == op: flat |= item[1]
        else: flat.add(item)
    return (op, frozenset(flat)) if len(flat) != 1 else next(iter(flat))


def canonical(tree, outputs):
    """Predicate tree up to associativity and commutativity; ports by quest output."""
    op = tree['op']
    if op == 'port':
        return ('output', outputs[tree['name']]) if tree['name'] in outputs else ('port', tree['name'])
    if op == 'not':
        return ('not', canonical(tree['children'][0], outputs))
    if op in ('and', 'or'):
        return _fold(op, [canonical(child, outputs) for child in tree['children']])
    return ('other', repr(sorted(tree.items())))


def delivered(groups):
    """The source outcome: some group has every objective completed."""
    return _fold('or', [_fold('and', [('output', objective_identifier(o) + '_Completed') for o in group])
                        for group in groups])


def group_name(objectives):
    return identifier('_'.join(objective_identifier(o) for o in objectives))


def _empty(name, quest=None):
    return dict(dialogue=name, quest=quest, sites=[], groups=[], pending=[], runtime_verified=False)


def plan(dialogue_blob, entry_blob, quest_blob, tracking, npc_assets):
    """What `bind` would do, or why it cannot.

    tracking is `campaign_quest_tracking.plan(model, bindings)` for the quest;
    npc_assets maps a source dialogue role to the SoulAsset alias of its soul.
    """
    _, host = host_of(dialogue_blob)
    name = identifier(host.get('Name'))
    sequences = {}
    for sequence in host.iter('Sequence'):
        if sequence.get('Name') in sequences:
            raise ValueError('Duplicate dialogue sequence: ' + str(sequence.get('Name')))
        sequences[sequence.get('Name')] = sequence
    sites = [s for s in sequences.values() if 'OpenInventory' in (s.get('ExitScript') or '')]
    if not sites:
        return _empty(name)
    _, quest_host = host_of(quest_blob)
    quest = quest_host.get('Name')
    result = _empty(name, quest)
    result['sites'] = [s.get('Name') for s in sites]
    pending = result['pending']

    def stop(reason, **detail):
        pending.append(dict(reason=reason, **detail))
        return result

    parsed = [parse(s.get('ExitScript')) for s in sites]
    if any(p is None for p in parsed):
        return stop('unsupported hand-in script', sequences=[s.get('Name') for s, p in zip(sites, parsed) if p is None])
    if any(p != parsed[0] for p in parsed):
        return stop('hand-in scripts of one dialogue differ')
    call = parsed[0]
    if call['quest'] != quest:
        return stop('hand-in for another quest: ' + call['quest'])
    listed = [o for branch in call['branches'] for o in branch['objectives']]
    if len(set(listed)) != len(listed):
        return stop('objective listed twice')
    ports = {p.get('Name'): (p.get('Direction'), p.get('Type')) for p in quest_host.findall('Ports/Port')}
    for objective in listed:
        oid = objective_identifier(objective)
        if (ports.get('complete_' + oid) != ('In', 'trigger') or ports.get(oid + '_Started') != ('Out', 'bool')
                or ports.get(oid + '_Completed') != ('Out', 'bool')):
            return stop('quest does not expose objective ' + objective)
    alias = dict(npc_assets or {}).get(call['role'])
    if alias is None:
        return stop('no soul asset for dialogue role ' + call['role'])
    identifier(alias)

    _, _, _, (instance, quest_node) = container_nodes(entry_blob, name, quest)
    # Groups: listed objectives one dialogue sequence starts together.
    triggered = {}
    for sequence in sequences.values():
        for port in sequence.findall('Triggers/Port'):
            triggered.setdefault(port.get('Name'), []).append(sequence.get('Name'))
    started_by, elsewhere = {}, set()
    by_identifier = {objective_identifier(o): o for o in listed}
    for e in quest_node.findall('Edge'):
        target = e.get('To', '')
        objective = by_identifier.get(target.removeprefix('start_')) if target.startswith('start_') else None
        if objective is None:
            continue
        source, _, port = e.get('From', '').partition('.')
        if source == name and port in triggered:
            for sequence in triggered[port]:
                started_by.setdefault(sequence, set()).add(objective)
        else:
            elsewhere.add(objective)
    together = {}
    for sequence, objectives in sorted(started_by.items()):
        if len(objectives) < 2:
            continue
        for objective in objectives:
            if together.setdefault(objective, frozenset(objectives)) != objectives:
                return stop('objective started with different partners: ' + objective)
    for sequence, objectives in started_by.items():
        for objective in objectives:
            if objective in together and together[objective] != objectives:
                return stop('objective not always started with its group: ' + objective)
    if elsewhere & together.keys():
        return stop('grouped objective also started outside this dialogue: ' + ', '.join(sorted(elsewhere & together.keys())))
    groups = []
    for index, branch in enumerate(call['branches']):
        own = []
        for objective in branch['objectives']:
            members = together.get(objective, frozenset([objective]))
            if not members <= set(branch['objectives']):
                return stop('group spans both script branches: ' + ', '.join(sorted(members)))
            ordered = [o for o in branch['objectives'] if o in members]
            if ordered not in own:
                own.append(ordered)
        if branch['guard'] is not None and (len(own) != 1 or branch['guard'] not in own[0]):
            return stop('script guard is not the started-check of one delivered group')
        groups.extend(own)

    # Descriptors come from the tracking plan and nowhere else.
    tracked = {r['objective']: r for r in tracking.get('converted', [])}
    labels = {o.get('Name'): o.find('LocalizedName').get('StringName') for o in quest_host.findall('Objectives/Objective')
              if o.find('LocalizedName') is not None and o.find('LocalizedName').get('StringName')}
    for objectives in groups:
        descriptors = []
        for objective in objectives:
            record = tracked.get(objective)
            if record is None:
                return stop('objective has no converted item tracking: ' + objective)
            if record['mode'] != 'manual' or any(q['kind'] != 'item' for q in record['requirements']):
                return stop('objective is not a manual item hand-in: ' + objective)
            for requirement in record['requirements']:
                descriptors.append(dict(objective=objective, objective_id=record['objective_id'],
                    item_class=requirement['target_item'], amount=requirement['count'],
                    minimum_health=requirement['minimum_health'],
                    label=labels.get(objective_identifier(objective))))
        if len(descriptors) > len(string.ascii_uppercase):
            return stop('too many descriptors in one delivery')
        gname = group_name(objectives)
        result['groups'].append(dict(name=gname, objectives=objectives, descriptors=descriptors,
            labelled=all(d['label'] for d in descriptors), result_port=identifier(RESULT + gname)))

    # The sequences after the window must test exactly "a delivered group is completed".
    targets = set()
    for sequence in sites:
        if sequence.get('EndType') == 'Decision' and len(sequence.findall('Decision')) == 1:
            targets.add(sequence.find('Decision').get('Name'))
        elif sequence.get('EndType') == 'GoTo' and sequence.get('GoToDecision'):
            targets.add(sequence.get('GoToDecision'))
        else:
            return stop('hand-in sequence does not lead to a decision: ' + sequence.get('Name'))
    decisions = [d for d in host.iter('Decision') if d.get('Name') in targets]
    if len(targets) != 1 or len(decisions) != 1:
        return stop('hand-in sequences lead to different decisions')
    outcomes = decisions[0].findall('Sequences/Sequence')
    outputs, started_ports = {}, {}
    for e in instance.findall('Edge'):
        source, _, output = e.get('From', '').partition('.')
        if source == quest:
            outputs[e.get('To')] = output
            started_ports.setdefault(output, e.get('To'))
    expected = delivered([g['objectives'] for g in result['groups']])
    roles = {}
    for sequence in outcomes:
        try:
            shape = canonical(predicate(sequence.get('EntryCondition', '')), outputs)
        except ValueError:
            shape = None
        if shape == expected: roles.setdefault('accept', []).append(sequence)
        elif shape == ('not', expected): roles.setdefault('reject', []).append(sequence)
        else: roles.setdefault('other', []).append(sequence)
    if len(outcomes) != 2 or len(roles.get('accept', [])) != 1 or len(roles.get('reject', [])) != 1:
        return stop('outcome conditions are not "a delivered group is completed" and its negation',
                    decision=decisions[0].get('Name'),
                    conditions={s.get('Name'): s.get('EntryCondition', '') for s in outcomes})
    accept, reject = roles['accept'][0], roles['reject'][0]

    # Effects of the accepting sequence must follow the completion.
    _, _, nodes, _ = container_nodes(entry_blob, name, quest)
    programs = []
    for port in [p.get('Name') for p in accept.findall('Triggers/Port')]:
        source = name + '.' + port
        steps = [n.get('Name') for n in nodes if n.tag == 'TriggerSequence'
                 and any(e.get('From') == source and e.get('To') == 'Exec' for e in n.findall('Edge'))]
        users = [(n.get('Name'), e.get('To')) for n in nodes for e in n.findall('Edge') if e.get('From') == source]
        if steps:
            if len(users) != len(steps) or triggered[port] != [accept.get('Name')]:
                return stop('effect program is shared: ' + port)
            programs.append(dict(port=port, steps=steps))
        elif any(n == quest for n, _ in users):
            return stop('unordered quest effect on the accepting sequence: ' + port)
    for objective in listed:
        output = objective_identifier(objective) + '_Started'
        started_ports.setdefault(output, identifier(STARTED + objective_identifier(objective)))
    result.update(decision=decisions[0].get('Name'), accept_sequence=accept.get('Name'),
                  reject_sequence=reject.get('Name'), programs=programs, role=call['role'], soul_asset=alias,
                  script=call, started_ports={objective_identifier(o) + '_Started':
                                              started_ports[objective_identifier(o) + '_Started'] for o in listed},
                  assumptions=list(ASSUMPTIONS))
    result['accept_condition'] = success_condition(result)
    result['reject_condition'] = '!(' + result['accept_condition'] + ')'
    return result


def success_condition(plan_):
    """Retail form: the handler's result is Success, for the group that is started."""
    terms = []
    for group in plan_['groups']:
        parts = ["Port('" + group['result_port'] + "') == " + SUCCESS]
        parts += ["Port('" + plan_['started_ports'][objective_identifier(o) + '_Started'] + "')"
                  for o in group['objectives']]
        terms.append('(' + ' AND '.join(parts) + ')')
    return ' OR '.join(terms)


def _tracked_descriptor(quest_host, descriptor, index):
    """The tracking lowering's own node for this requirement, when the quest has it."""
    node = quest_host.find("Nodes/Function[@Name='lowered_track_" + descriptor['objective_id'] + '_' + str(index)
                           + "_descriptor']")
    return None if node is None else {c.get('Name'): c.get('Value') for c in node.findall('Constant')}


def _constants(descriptor):
    values = dict(ItemClass=descriptor['item_class'], Amount=str(descriptor['amount']))
    if descriptor['minimum_health'] > 0:
        values['MinimumHealth'] = repr(descriptor['minimum_health'])
    return values


def bind(dialogue_blob, entry_blob, quest_blob, plan_, tracking, npc_assets, assets=None):
    """Apply a current plan; returns (dialogue blob, entry blob).

    assets, when given, is the set of asset aliases the container can see; the
    NPC's soul asset must be one of them. A plan with no sites changes nothing.
    """
    current = plan(dialogue_blob, entry_blob, quest_blob, tracking, npc_assets)
    if plan_ != current:
        raise ValueError('Stale dialogue delivery plan')
    if current['pending']:
        raise ValueError('Dialogue hand-in is not lowerable: ' + '; '.join(p['reason'] for p in current['pending']))
    if not current['sites']:
        return dialogue_blob, entry_blob
    root, host = host_of(dialogue_blob)
    name, quest = current['dialogue'], current['quest']
    _, quest_host = host_of(quest_blob)
    entry, _, nodes, (instance, quest_node) = container_nodes(entry_blob, name, quest)
    stem = PREFIX + name + '_'
    if any(n.get('Name', '').startswith(stem) for n in nodes):
        raise ValueError('Delivery already lowered: ' + name)
    if assets is not None and current['soul_asset'] not in set(assets):
        raise ValueError('Undeclared delivery soul asset: ' + current['soul_asset'])
    for group in current['groups']:
        by_objective = {}
        for descriptor in group['descriptors']:
            index = by_objective.setdefault(descriptor['objective'], [])
            tracked = _tracked_descriptor(quest_host, descriptor, len(index))
            index.append(descriptor)
            if tracked is not None and tracked != _constants(descriptor):
                raise ValueError('Delivery differs from the quest tracking descriptor: ' + descriptor['objective'])
        for objective in group['objectives']:
            quest_port(quest_blob, quest, 'complete_' + objective_identifier(objective), 'In', 'trigger')
            quest_port(quest_blob, quest, objective_identifier(objective) + '_Started', 'Out', 'bool')

    # Dialogue side.
    sequences = {s.get('Name'): s for s in host.iter('Sequence')}
    for port in (BEGIN, ACCEPT, REJECT):
        declare_port(host, port, 'Out', 'trigger')
    for site in current['sites']:
        del sequences[site].attrib['ExitScript']
        add_trigger(sequences[site], BEGIN)
    accept, reject = sequences[current['accept_sequence']], sequences[current['reject_sequence']]
    accept.set('EntryCondition', current['accept_condition']); add_trigger(accept, ACCEPT)
    reject.set('EntryCondition', current['reject_condition']); add_trigger(reject, REJECT)
    wired = {e.get('To') for e in instance.findall('Edge')}
    for output, port in current['started_ports'].items():
        declare_port(host, port, 'In', 'bool')
        if port not in wired:
            edge(instance, quest + '.' + output, port)
    for program in current['programs']:
        for triggers in accept.findall('Triggers'):
            for port in [p for p in triggers if p.get('Name') == program['port']]:
                triggers.remove(port)
        ports = host.find('Ports')
        for port in [p for p in ports if p.get('Name') == program['port']]:
            ports.remove(port)

    # Container side.
    soul = ET.SubElement(nodes, 'ObjectProperties', Name=stem + 'npc', DeclaringType='wh::rpgmodule::I_Soul')
    ET.SubElement(soul, 'Asset', Name='I_Soul', Alias=current['soul_asset'])
    previous = None
    for group in current['groups']:
        g = stem + group['name'] + '_'
        letters = string.ascii_uppercase
        items = ET.Element('MakeArray', Name=g + 'items', TypeT=DESCRIPTORS)
        filters = ET.Element('MakeArray', Name=g + 'filters', TypeT=DESCRIPTORS)
        labels = ET.Element('MakeArray', Name=g + 'labels', TypeT=LABELS)
        for index, descriptor in enumerate(group['descriptors']):
            wanted = ET.SubElement(nodes, 'Function', Name=g + 'item_' + str(index),
                MethodName='wh::entitymodule::CreateItemClassDescriptor', DeclaringType='wh::entitymodule')
            for key, value in _constants(descriptor).items():
                constant(wanted, key, value)
            shown = ET.SubElement(nodes, 'Function', Name=g + 'filter_' + str(index),
                MethodName='wh::entitymodule::CreateItemClassDescriptor', DeclaringType='wh::entitymodule')
            constant(shown, 'ItemClass', descriptor['item_class'])
            edge(items, g + 'item_' + str(index) + '.ItemDescriptor', letters[index])
            edge(filters, g + 'filter_' + str(index) + '.ItemDescriptor', letters[index])
            if group['labelled']:
                constant(labels, letters[index], descriptor['label'])
        nodes.append(items); nodes.append(filters)
        delivery = ET.SubElement(nodes, 'Function', Name=g + 'delivery',
            MethodName='wh::entitymodule::CreateItemDelivery', DeclaringType='wh::entitymodule')
        edge(delivery, g + 'items.Array', 'DeliveryDescriptors')
        edge(delivery, g + 'filters.Array', 'PlayerInventoryFilters')
        if group['labelled']:
            nodes.append(labels)
            edge(delivery, g + 'labels.Array', 'Labels')
        edge(delivery, stem + 'npc.Inventory', 'DeliveryInventory')
        started = all_of(nodes, g + 'started', [quest + '.' + objective_identifier(o) + '_Started'
                                                for o in group['objectives']])
        handler = ET.SubElement(nodes, 'ItemDeliveryHandler', Name=g + 'handler')
        edge(handler, g + 'delivery.ItemDelivery', 'ItemDelivery')
        for verb, port, target in (('begin', BEGIN, 'BeginDelivery'), ('accept', ACCEPT, 'AcceptDelivery'),
                                   ('reject', REJECT, 'RejectDelivery')):
            # One chain per trigger: the first started group takes it.
            gate = ET.SubElement(nodes, 'If', Name=g + verb)
            edge(gate, name + '.' + port if previous is None else previous + verb + '.False', 'Exec')
            edge(gate, started, 'Condition')
            edge(handler, g + verb + '.True', target)
        done = ET.SubElement(nodes, 'TriggerSequence', Name=g + 'accepted')
        edge(done, g + 'handler.OnAccept', 'Exec')
        for objective in group['objectives']:
            edge(quest_node, g + 'accepted.A', 'complete_' + objective_identifier(objective))
        edge(instance, g + 'handler.DeliveryResult', group['result_port'])
        declare_port(host, group['result_port'], 'In', 'DeliveryResult')
        previous = g
    by_name = {n.get('Name'): n for n in nodes}
    for program in current['programs']:
        source = name + '.' + program['port']
        for step in program['steps']:
            node = by_name[step]
            for e in [e for e in node.findall('Edge') if e.get('From') == source and e.get('To') == 'Exec']:
                node.remove(e)
            # After the completion (output A), in the source effect order.
            for group in current['groups']:
                edge(node, stem + group['name'] + '_accepted.B', 'Exec')
    return xml(root), xml(entry)
