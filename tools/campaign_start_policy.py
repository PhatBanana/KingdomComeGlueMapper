"""Separate first region visits from native New Game initialization."""
import xml.etree.ElementTree as ET
from upgrade_map import xml

METHOD = 'wh::rpgmodule::IsNewGameModeDebug'
POLICY = dict(native_predicate=METHOD, existing_player='preserve', new_game='initialize_once')


def validate_native(definitions):
    root = ET.fromstring(definitions)
    matches = [d for d in root.iter('Definition') if d.get('TypeName') == 'IfFunction'
               and d.find("Properties/Property[@Name='MethodName'][@Value='" + METHOD + "']") is not None]
    if len(matches) != 1:
        raise ValueError('Native New Game entry predicate is unavailable')
    ports = {(p.get('Name'), p.get('Direction'), p.get('Type')) for p in matches[0].find('Ports')}
    if not {('Exec', 'In', 'trigger'), ('True', 'Out', 'trigger'), ('False', 'Out', 'trigger')} <= ports:
        raise ValueError('Native New Game entry predicate ports changed')


def validate_start_policy(blob, name):
    nodes = ET.fromstring(blob).find('./Skald/Project/Nodes')
    if nodes is None:
        raise ValueError('Missing campaign project')
    def one(tag, suffix):
        found = [n for n in nodes if n.tag == tag and n.get('Name') == name + suffix]
        if len(found) != 1:
            raise ValueError('Missing or ambiguous New Game policy node: ' + name + suffix)
        return found[0]
    guard = one('IfFunction', '_new_game')
    if guard.get('MethodName') != METHOD or guard.get('DeclaringType') != 'wh::rpgmodule':
        raise ValueError('Invalid native New Game policy')
    sequence = one('TriggerSequence', '_initialize')
    once = one('If', '_begin')
    latch = one('State', '_started')
    expected = [(guard, 'Exec', name+'_begin.True'),
                (sequence, 'Exec', name+'_new_game.True'),
                (once, 'Condition', name+'_unstarted.bool')]
    for node, port, source in expected:
        if [e.get('From') for e in node.findall('Edge') if e.get('To') == port] != [source]:
            raise ValueError('Campaign initialization bypasses New Game/once-only policy')
    if latch.find("Edge[@From='"+name+"_new_game.False'][@To='SetTrue']") is None:
        raise ValueError('Existing-player visit must close the initialization latch')
    return dict(POLICY)


def gate_start(blob, name):
    """Guard the entire existing chain, including loadout, stats and quest start.

    A saved first-visit latch also closes for visitors. Reloading or returning
    cannot later turn that visit into a campaign start.
    """
    root = ET.fromstring(blob)
    nodes = root.find('./Skald/Project/Nodes')
    if nodes is None:
        raise ValueError('Missing campaign project')
    if any(n.get('Name') == name+'_new_game' for n in nodes):
        validate_start_policy(blob, name)
        return blob
    sequences = [n for n in nodes if n.tag == 'TriggerSequence' and n.get('Name') == name+'_initialize']
    latches = [n for n in nodes if n.tag == 'State' and n.get('Name') == name+'_started']
    if len(sequences) != 1 or len(latches) != 1:
        raise ValueError('Missing or ambiguous campaign initialization chain')
    edges = sequences[0].findall("Edge[@To='Exec']")
    if len(edges) != 1 or edges[0].get('From') != name+'_begin.True':
        raise ValueError('Unrecognized campaign initialization entry')
    guard = ET.SubElement(nodes, 'IfFunction', Name=name+'_new_game',
                          MethodName=METHOD, DeclaringType='wh::rpgmodule')
    ET.SubElement(guard, 'Edge', From=name+'_begin.True', To='Exec')
    edges[0].set('From', name+'_new_game.True')
    ET.SubElement(latches[0], 'Edge', From=name+'_new_game.False', To='SetTrue')
    result = xml(root)
    validate_start_policy(result, name)
    return result
