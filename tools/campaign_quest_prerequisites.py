"""Declared premises for story quests that are not ported.

A dialogue condition on a missing quest must bind to a visible, declared port,
never to a silent constant. KCD1 orders its story in `q_master_main`: one hidden
objective per story quest, each with the condition `IsQuestCompleted('<quest>')`,
chained by transitions; a quest is activated when the objective before it is
done. `story_chain` reads that order from the source model.

A chain quest that is registered for real is read as it is. A chain quest that
is not ported is a *premise*: an instance, under the quest's own name, of one
shared module with a quest's five state outputs and two inputs:

    assumed     the one switch (see `switch`): this save takes the story so far as told
    activated   the quest before it in the chain is completed

    completed = assumed            unchanged = not assumed
    available = assumed or activated
    started   = failed = false     (nobody can play a quest that is not ported)

Every premise is listed in the report with KCD1's own condition, so porting the
quest for real is one deliberate step: its premise row is deleted, and `story`
refuses a premise whose quest is registered.
"""
import re
import xml.etree.ElementTree as ET

from campaign_quest_graph import definition, xml, edge, constant, identifier

PREMISE_INPUTS = ('assumed', 'activated')
QUEST_OUTPUTS = ('available', 'started', 'completed', 'failed', 'unchanged')
SWITCH_INPUT, SWITCH_OUTPUT = 'story_unchanged', 'assumed'
COMPLETED = re.compile(r"\s*IsQuestCompleted\(\s*'([A-Za-z_]\w*)'\s*\)\s*\Z")


def _module(name, outputs):
    root, module = definition('Module', identifier(name))
    ports = ET.SubElement(module, 'Ports')
    nodes = ET.SubElement(module, 'Nodes')
    output = ET.SubElement(nodes, 'Output', Name='Output')
    for port, value in outputs:
        ET.SubElement(ports, 'Port', Name=port, Direction='Out', Type='bool')
        state = ET.SubElement(nodes, 'State', Name='stub_' + port, TypeT='bool')
        constant(state, 'DefaultValue', 'true' if value else 'false')
        edge(output, 'stub_' + port + '.State', port)
    return xml(root)


def host(name):
    """Module with one bool output, `active`, that is always true."""
    return _module(name, [('active', True)])


def premise(name):
    """The shared premise module; one instance per story quest that is not ported."""
    root, module = definition('Module', identifier(name))
    ports = ET.SubElement(module, 'Ports')
    for port in PREMISE_INPUTS:
        ET.SubElement(ports, 'Port', Name=port, Direction='In', Type='bool')
    for port in QUEST_OUTPUTS:
        ET.SubElement(ports, 'Port', Name=port, Direction='Out', Type='bool')
    nodes = ET.SubElement(module, 'Nodes')
    output = ET.SubElement(nodes, 'Output', Name='Output')
    never = ET.SubElement(nodes, 'State', Name='never', TypeT='bool')
    constant(never, 'DefaultValue', 'false')
    untold = ET.SubElement(nodes, 'Function', Name='untold', MethodName='math::boolean::Not', DeclaringType='math::boolean')
    edge(untold, 'assumed', 'Value')
    reachable = ET.SubElement(nodes, 'Function', Name='reachable', MethodName='math::boolean::Or', DeclaringType='math::boolean')
    edge(reachable, 'assumed', 'A'); edge(reachable, 'activated', 'B')
    for source, port in (('reachable.bool', 'available'), ('never.State', 'started'), ('assumed', 'completed'),
                         ('never.State', 'failed'), ('untold.bool', 'unchanged')):
        edge(output, source, port)
    return xml(root)


def switch(name):
    """The one switch every premise reads: `assumed` is its single input, unchanged."""
    root, module = definition('Module', identifier(name))
    ports = ET.SubElement(module, 'Ports')
    ET.SubElement(ports, 'Port', Name=SWITCH_INPUT, Direction='In', Type='bool')
    ET.SubElement(ports, 'Port', Name=SWITCH_OUTPUT, Direction='Out', Type='bool')
    edge(ET.SubElement(ET.SubElement(module, 'Nodes'), 'Output', Name='Output'), SWITCH_INPUT, SWITCH_OUTPUT)
    return xml(root)


def _owner(root):
    owner = root.find('./Skald/Level')
    if owner is None: owner = root.find('./Skald/Project')
    if owner is None:
        raise ValueError('Expected a level or project entry')
    definitions, nodes = owner.find('Definitions'), owner.find('Nodes')
    if definitions is None: definitions = ET.SubElement(owner, 'Definitions')
    if nodes is None: nodes = ET.SubElement(owner, 'Nodes')
    return definitions, nodes


def register(entry_blob, definition_path, name, *, instance=None, edges=()):
    """Declare a module file and add one instance of it to a Level or Project entry.

    The instance is named after the module unless `instance` is given; a module file that is
    already declared is then shared. edges are (source, input port) pairs for the instance.
    """
    identifier(name)
    shared = instance is not None
    instance = identifier(instance or name)
    root = ET.fromstring(entry_blob)
    definitions, nodes = _owner(root)
    if any(n.get('Name') == instance or n.tag == instance for n in nodes):
        raise ValueError('Prerequisite name already registered: ' + instance)
    declared = any(d.get('File') == definition_path for d in definitions)
    if declared and not shared:
        raise ValueError('Prerequisite file already registered: ' + definition_path)
    if not declared:
        ET.SubElement(definitions, 'Definition', File=definition_path)
    node = ET.SubElement(nodes, name, Name=instance)
    for source, port in edges:
        edge(node, source, port)
    return xml(root)


def instances(entry_blob):
    """{instance name: (definition name, [(source, input port)])} of a Level or Project entry."""
    _, nodes = _owner(ET.fromstring(entry_blob))
    return {n.get('Name'): (n.tag, [(e.get('From'), e.get('To')) for e in n.findall('Edge')]) for n in nodes}


def story_chain(master, quests):
    """KCD1's story order up to the given quests, read from the master quest's model.

    Returns [dict(quest, objective_id, condition, after)] from the head of the story on; `after` is
    the quest before it (None for the head). The chain is made of the objectives named after a quest
    whose condition is exactly `IsQuestCompleted('<that quest>')`, each with at most one enabled
    predecessor, itself such an objective.
    """
    rows = master['tables']['quest_objective']['rows']
    by_quest, by_id = {}, {}
    for row in rows:
        match = COMPLETED.match(row.get('condition') or '')
        # The story objective of a quest carries the quest's name; other objectives that test the same
        # quest (`dog_activation`, `playerHome_pirkstejn`) are side gates, not the chain.
        if match and row['objective_name'] == match.group(1):
            if match.group(1) in by_quest:
                raise ValueError('Story quest has two master objectives: ' + match.group(1))
            by_quest[match.group(1)] = row
            by_id[row['objective_id']] = match.group(1)
    incoming = {}
    for row in master['tables']['quest_transition']['rows']:
        if row['enabled'] == 'True':
            incoming.setdefault(row['to_objective_id'], []).append(row['from_objective_id'])
    links = {}
    for quest in quests:
        if quest not in by_quest:
            raise ValueError('Quest is not in the source story chain: ' + quest)
        seen = set()
        while quest is not None and quest not in links:
            if quest in seen:
                raise ValueError('Cyclic source story chain at ' + quest)
            seen.add(quest)
            row = by_quest[quest]
            before = incoming.get(row['objective_id'], [])
            if len(before) > 1 or (before and before[0] not in by_id):
                raise ValueError('Source story chain is not linear at ' + quest)
            previous = by_id[before[0]] if before else None
            links[quest] = dict(quest=quest, objective_id=row['objective_id'], condition=row['condition'].strip(),
                                after=previous)
            quest = previous

    def depth(name, guard=0):
        if guard > len(links):
            raise ValueError('Cyclic source story chain at ' + name)
        return 0 if links[name]['after'] is None else 1 + depth(links[name]['after'], guard + 1)
    return sorted(links.values(), key=lambda link: depth(link['quest']))


def story(entry_blob, chain, premises, real_ports, premise_name, premise_path, switch_name, switch_path):
    """Register the switch and the premises of `chain` in a Level entry; returns (entry blob, report).

    premises names the chain quests that are not ported. real_ports(name) returns the
    {port: (direction, type)} of a quest registered in the container, or None. Refused: a premise whose
    quest is registered for real, a chain quest that is neither, and a head that is not real (the switch
    reads the head's `unchanged`). Instances that are already there with the same wiring are kept.
    """
    if not chain:
        return entry_blob, dict(switch=None, premises=[], real=[])
    premises = set(premises)
    found = instances(entry_blob)

    def kind(name):
        tag = found.get(name, (None,))[0]
        if tag == premise_name:
            if name not in premises:
                raise ValueError('Premise instance has no premise row: ' + name)
            return 'premise'
        if tag is not None:
            if name in premises:
                raise ValueError('Premise quest is registered for real; delete its premise row: ' + name)
            ports = real_ports(name) or {}
            if any(ports.get(port) != ('Out', 'bool') for port in ('completed', 'unchanged')):
                raise ValueError('Registered story quest does not expose its state: ' + name)
            return 'real'
        if name in premises:
            return 'missing'
        raise ValueError('Story quest is neither registered nor a declared premise: ' + name)

    kinds = {link['quest']: kind(link['quest']) for link in chain}
    head = chain[0]['quest']
    if chain[0]['after'] is not None or kinds[head] != 'real':
        raise ValueError('The story switch needs the first story quest registered for real: ' + head)
    signal = head + '.unchanged'
    wanted = [(signal, SWITCH_INPUT)]
    if switch_name in found:
        if found[switch_name] != (switch_name, wanted):
            raise ValueError('Story switch is already registered differently')
    else:
        entry_blob = register(entry_blob, switch_path, switch_name, edges=wanted)
    for link in chain:
        name = link['quest']
        if kinds[name] == 'real':
            continue
        wanted = [(switch_name + '.' + SWITCH_OUTPUT, 'assumed'), (link['after'] + '.completed', 'activated')]
        if kinds[name] == 'premise':
            if found[name][1] != wanted:
                raise ValueError('Premise is already registered differently: ' + name)
            continue
        entry_blob = register(entry_blob, premise_path, premise_name, instance=name, edges=wanted)
    return entry_blob, dict(switch=dict(name=switch_name, signal=signal),
                            premises=[l['quest'] for l in chain if kinds[l['quest']] != 'real'],
                            real=[l['quest'] for l in chain if kinds[l['quest']] == 'real'])


def _reads(expression, quest):
    return re.search("'" + re.escape(quest) + "'", expression) is not None


def assumed_prerequisites(models, quests):
    """List each quest with the source condition text and sequences that read it.

    models are dialogue IR documents; quests are quest names. A quest read by no sequence is still
    listed, with empty conditions.
    """
    from campaign_dialogue_conditions import expand_functions
    result = []
    for quest in sorted(quests):
        identifier(quest)
        grouped, sequences = {}, []
        for model in models:
            functions = model.get('functions', {})
            for topic_id, topic in model['topics'].items():
                for sequence in topic['sequences']:
                    entry = sequence['entry']
                    for key in ('entry_condition', 'npc_entry_condition'):
                        text = entry.get(key, '')
                        if not text or not _reads(expand_functions(text, functions), quest):
                            continue
                        identity = dict(dialogue=model['alias'], topic=topic_id,
                                        sequence=sequence['source']['sequence_id'])
                        row = grouped.setdefault((key, text), dict(field=key, text=text, sequences=[]))
                        if identity not in row['sequences']: row['sequences'].append(identity)
                        if identity not in sequences: sequences.append(identity)
        result.append(dict(quest=quest, conditions=list(grouped.values()), sequences=sequences))
    return result


def premise_report(chain, registered, models, master_quest, new_game='not started', travel='completed'):
    """One row per chain quest: what it is here, KCD1's own condition, and who reads it.

    registered is the report of `story`. A premise row names the switch and what the premise reads in
    each kind of save; a real row is listed so the whole dependency is visible.
    """
    read = {r['quest']: r for r in assumed_prerequisites(models, [l['quest'] for l in chain])}
    rows = []
    for link in chain:
        name = link['quest']
        row = dict(quest=name, premise=name in registered['premises'], after=link['after'],
                   source=dict(quest=master_quest, objective_id=link['objective_id'], condition=link['condition']),
                   conditions=read[name]['conditions'], sequences=read[name]['sequences'])
        if row['premise']:
            row.update(switch=registered['switch']['name'], signal=registered['switch']['signal'],
                       when_signal_true=travel, when_signal_false=new_game)
        rows.append(row)
    return rows
