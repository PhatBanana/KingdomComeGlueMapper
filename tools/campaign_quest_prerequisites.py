"""Declared stand-ins for quests that are not ported.

A dialogue condition on a missing quest must bind to a visible, declared port,
never to a silent constant. Each stand-in is listed in the report so removing it
once the real quest exists is a deliberate step.
"""
import re
import xml.etree.ElementTree as ET

from campaign_quest_graph import definition, xml, edge, constant, identifier

STATES = ('completed', 'unchanged')


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


def stub(quest_name, state):
    """Quest-shaped module whose outputs are fixed to one progress state."""
    if state not in STATES:
        raise ValueError('Unsupported prerequisite state: ' + repr(state))
    return _module(quest_name, [('available', state == 'completed'),
                                ('started', False),
                                ('completed', state == 'completed'),
                                ('failed', False),
                                ('unchanged', state == 'unchanged')])


def host(name):
    """Module with one bool output, `active`, that is always true."""
    return _module(name, [('active', True)])


def register(entry_blob, definition_path, name):
    """Declare the module file and add its instance to a Level or Project entry."""
    identifier(name)
    root = ET.fromstring(entry_blob)
    owner = root.find('./Skald/Level')
    if owner is None: owner = root.find('./Skald/Project')
    if owner is None:
        raise ValueError('Expected a level or project entry')
    definitions, nodes = owner.find('Definitions'), owner.find('Nodes')
    if definitions is None: definitions = ET.SubElement(owner, 'Definitions')
    if nodes is None: nodes = ET.SubElement(owner, 'Nodes')
    if any(n.get('Name') == name or n.tag == name for n in nodes):
        raise ValueError('Prerequisite name already registered: ' + name)
    if any(d.get('File') == definition_path for d in definitions):
        raise ValueError('Prerequisite file already registered: ' + definition_path)
    ET.SubElement(definitions, 'Definition', File=definition_path)
    ET.SubElement(nodes, name, Name=name)
    return xml(root)


def _reads(expression, quest):
    return re.search("'" + re.escape(quest) + "'", expression) is not None


def assumed_prerequisites(models, selection):
    """List each stub with the source condition text and sequences that read it.

    models are dialogue IR documents; selection maps quest name to stub state.
    A quest read by no sequence is still listed, with empty conditions.
    """
    from campaign_dialogue_conditions import expand_functions
    result = []
    for quest, state in sorted(selection.items()):
        if state not in STATES:
            raise ValueError('Unsupported prerequisite state: ' + repr(state))
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
        result.append(dict(quest=quest, state=state, conditions=list(grouped.values()),
                           sequences=sequences))
    return result
