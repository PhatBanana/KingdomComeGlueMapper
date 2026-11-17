"""Lower source quest lifecycle calls in dialogue exit scripts to trigger edges.

A KCD1 sequence script such as `QuestSystem.StartQuest('<quest>')` is copied
into the emitted dialogue as an `ExitScript`. KCD2 Lua has no such table, so
the call is replaced by an `Out` trigger port on the dialogue, a
`Triggers/Port` on the sequence and an edge to the quest's input in the
container. The call-to-input table is `campaign_quest_bridge.QUEST_ACTIONS`
plus our own `CancelQuest` -> `cancel`; any other lifecycle call stays pending.

KCD1 `CancelQuest` ends a quest without success and leaves its objectives as
they are. KCD2's quest progress is None / Active / Done / Failed, and retail
ends a quest that can no longer be done with Failed: of the edges into a quest's
progress that follow a death trigger, 24 are SetFailed and 4 SetDone (for
example klaster_hibernate_mode/staryMnich.xml and kutnohorsko/klasterniTajemstvi.xml,
`deathtrigger.OnDeath -> SetFailed`). SetNone is used by 17 retail quests, for
resets and version patches, and would let the quest be offered again. So a
canceled quest becomes Failed. `expose_cancel` adds that input to an emitted
quest: `cancel` fails an active quest and always sets the `canceled` output,
so the source's own word for the ending stays readable. **Guess:** the journal
lists it with the failed quests, as it does a retail failed quest.

A script is lowered only when it consists of nothing but such calls on quests
the caller registered. Any other statement keeps the whole sequence pending and
`bind` refuses a plan that has pending sequences.

Load-bearing and not runtime-verified: a sequence `Triggers/Port` fires for an
effect the source ran at sequence exit. The objective `action_*` ports the
dialogue emitter writes rely on the same mechanism.
"""
import re
import xml.etree.ElementTree as ET

from campaign_quest_bridge import QUEST_ACTIONS
from campaign_quest_graph import constant, edge, identifier, xml

# Ours, on top of the maintainer's table: what a source quest function becomes on an emitted quest.
QUEST_INPUTS = dict(QUEST_ACTIONS, CancelQuest='cancel')
CANCEL, CANCELED = 'cancel', 'canceled'
CANCEL_GATE, CANCEL_LATCH = 'lowered_cancel_if_active', 'lowered_cancel_canceled'

PREFIX = 'lifecycle_'
CANDIDATE = re.compile(r'QuestSystem\s*\.\s*\w*Quest\s*\(')
CALL = re.compile(r"\s*QuestSystem\.(\w+)\s*\(\s*'([^'\\]*)'\s*\)\s*;?\s*")


def parse(script):
    """[(function, quest)] when the script is only quest calls, else None."""
    calls, offset = [], 0
    while offset < len(script):
        match = CALL.match(script, offset)
        if match is None:
            return None
        calls.append((match.group(1), match.group(2)))
        offset = match.end()
    return calls or None


def port_name(quest, action):
    return identifier(PREFIX + quest + '_' + action)


def host_of(blob):
    root = ET.fromstring(blob)
    hosts = list(root.find('Skald'))
    if len(hosts) != 1:
        raise ValueError('Expected one Skald definition')
    return root, hosts[0]


def plan(dialogue_blob, quest_names):
    """Sites this module can lower and the sequences it must leave alone."""
    quests = set(quest_names)
    _, host = host_of(dialogue_blob)
    sites, pending, seen = [], [], set()
    for sequence in host.iter('Sequence'):
        script = sequence.get('ExitScript')
        if not script or not CANDIDATE.search(script):
            continue
        name = sequence.get('Name')
        if name in seen:
            raise ValueError('Duplicate dialogue sequence: ' + str(name))
        seen.add(name)
        calls = parse(script)
        if calls is None:
            pending.append(dict(sequence=name, reason='script is not only quest lifecycle calls', script=script))
            continue
        reasons = []
        for function, quest in calls:
            if function not in QUEST_INPUTS:
                reasons.append('no native input for QuestSystem.' + function)
            elif quest not in quests:
                reasons.append('unregistered quest ' + quest)
        if len(set(calls)) != len(calls):
            reasons.append('repeated call')
        if reasons:
            pending.append(dict(sequence=name, reason='; '.join(reasons), script=script))
            continue
        for function, quest in calls:
            sites.append(dict(sequence=name, function=function, quest=quest, input=QUEST_INPUTS[function],
                              port=port_name(quest, QUEST_INPUTS[function])))
    return dict(dialogue=host.get('Name'), sites=sites, pending=pending, runtime_verified=False)


def add_trigger(sequence, port):
    """Reference an output trigger from a sequence, once."""
    if any(p.get('Name') == port for p in sequence.findall('Triggers/Port')):
        return
    triggers = sequence.find('Triggers')
    if triggers is None:
        triggers = ET.Element('Triggers')
        children = list(sequence)
        before = next((i for i, c in enumerate(children) if c.tag in ('Elements', 'Decision')), len(children))
        sequence.insert(before, triggers)
    ET.SubElement(triggers, 'Port', Name=port)


def declare_port(host, name, direction, kind):
    ports = host.find('Ports')
    found = [p for p in ports.findall('Port') if p.get('Name') == name]
    if found:
        if len(found) != 1 or found[0].get('Direction') != direction or found[0].get('Type') != kind:
            raise ValueError('Conflicting dialogue port: ' + name)
        return
    ET.SubElement(ports, 'Port', Name=name, Direction=direction, Type=kind)


def container_nodes(entry_blob, *instances):
    """The container's node list and the named instances, each present once."""
    root, host = host_of(entry_blob)
    if host.tag not in ('Project', 'Level'):
        raise ValueError('Expected a project or level container')
    nodes = host.find('Nodes')
    found = []
    for name in instances:
        matches = [n for n in nodes if n.get('Name') == name]
        if len(matches) != 1 or matches[0].tag != name:
            raise ValueError('Missing or ambiguous container instance: ' + name)
        found.append(matches[0])
    return root, host, nodes, found


def quest_port(quest_blob, quest, port, direction, kind):
    _, host = host_of(quest_blob)
    if host.get('Name') != quest:
        raise ValueError('Quest definition identity mismatch: ' + quest)
    found = [p for p in host.findall('Ports/Port') if p.get('Name') == port]
    if len(found) != 1 or found[0].get('Direction') != direction or found[0].get('Type') != kind:
        raise ValueError('Quest does not declare ' + direction + ' ' + kind + ' port ' + quest + '.' + port)


def expose_cancel(quest_blob, sources=()):
    """Give an emitted quest the `cancel` input and `canceled` output; returns the quest blob.

    sources are triggers inside the quest definition (for example `objective_79.OnCompleted` behind a
    controller rule's own gate) that cancel it too. Calling it again only adds sources that are new.
    """
    root, host = host_of(quest_blob)
    if host.tag != 'Quest':
        raise ValueError('Expected an emitted quest definition')
    ports, nodes = host.find('Ports'), host.find('Nodes')
    by_name = {n.get('Name'): n for n in nodes}
    progress, output = by_name.get('quest_progress'), by_name.get('Output')
    if progress is None or output is None or progress.get('TypeT') != 'wh::questmodule::QuestProgress':
        raise ValueError('Quest has no native progress state to cancel')
    declared = {p.get('Name'): (p.get('Direction'), p.get('Type')) for p in ports}
    if CANCEL_GATE not in by_name:
        if CANCEL in declared or CANCELED in declared or CANCEL_LATCH in by_name:
            raise ValueError('Quest already declares a different cancel')
        ET.SubElement(ports, 'Port', Name=CANCEL, Direction='In', Type='trigger')
        ET.SubElement(ports, 'Port', Name=CANCELED, Direction='Out', Type='bool')
        gate = ET.SubElement(nodes, 'If', Name=CANCEL_GATE)
        edge(gate, 'quest_progress.Active', 'Condition')
        edge(gate, CANCEL, 'Exec')
        latch = ET.SubElement(nodes, 'State', Name=CANCEL_LATCH, TypeT='bool')
        constant(latch, 'DefaultValue', 'false')
        edge(latch, CANCEL, 'SetTrue')
        edge(progress, CANCEL_GATE + '.True', 'SetFailed')
        edge(output, CANCEL_LATCH + '.State', CANCELED)
    elif declared.get(CANCEL) != ('In', 'trigger') or declared.get(CANCELED) != ('Out', 'bool'):
        raise ValueError('Quest already declares a different cancel')
    gate, latch = nodes.find("If[@Name='" + CANCEL_GATE + "']"), nodes.find("State[@Name='" + CANCEL_LATCH + "']")
    for source in sources:
        origin = source.partition('.')[0]
        if '.' not in source or nodes.find("*[@Name='" + origin + "']") is None:
            raise ValueError('Cancel source is not a node of the quest: ' + source)
        if not any(e.get('From') == source and e.get('To') == 'Exec' for e in gate.findall('Edge')):
            edge(gate, source, 'Exec')
            edge(latch, source, 'SetTrue')
    return xml(root)


def bind(dialogue_blob, entry_blob, plan_, quests):
    """Apply a current plan. `quests` maps each quest name to its definition blob.

    Returns (dialogue blob, entry blob). A plan with no sites changes nothing,
    so a second run over lowered files is a no-op.
    """
    current = plan(dialogue_blob, quests.keys())
    if plan_ != current:
        raise ValueError('Stale dialogue lifecycle plan')
    if current['pending']:
        raise ValueError('Dialogue lifecycle scripts are not lowerable: ' + ', '.join(
            p['sequence'] + ' (' + p['reason'] + ')' for p in current['pending']))
    if not current['sites']:
        return dialogue_blob, entry_blob
    root, host = host_of(dialogue_blob)
    name = identifier(host.get('Name'))
    targets = sorted({s['quest'] for s in current['sites']})
    entry, _, _, found = container_nodes(entry_blob, name, *targets)
    instances = dict(zip(targets, found[1:]))
    for site in current['sites']:
        quest_port(quests[site['quest']], site['quest'], site['input'], 'In', 'trigger')
    sequences = {s.get('Name'): s for s in host.iter('Sequence')}
    for site in current['sites']:
        sequence = sequences[site['sequence']]
        sequence.attrib.pop('ExitScript', None)
        declare_port(host, site['port'], 'Out', 'trigger')
        add_trigger(sequence, site['port'])
        source = name + '.' + site['port']
        node = instances[site['quest']]
        if not any(e.get('From') == source and e.get('To') == site['input'] for e in node.findall('Edge')):
            ET.SubElement(node, 'Edge', From=source, To=site['input'])
    return xml(root), xml(entry)
