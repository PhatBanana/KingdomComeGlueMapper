"""Separate native campaign starts from ordinary region arrivals."""
import xml.etree.ElementTree as ET
from upgrade_map import xml

LEGACY_METHOD = 'wh::rpgmodule::IsNewGameModeDebug'
POLICY = dict(start_event='GameStart.OnStart', readiness='region_arrival',
              existing_player='preserve', new_game='initialize_once')


def validate_native(definitions):
    root = ET.fromstring(definitions)
    matches = [d for d in root.iter('Definition') if d.get('TypeName') == 'GameStart']
    if len(matches) != 1 or not any(p.get('Name') == 'OnStart' and
        p.get('Direction') == 'Out' and p.get('Type') == 'trigger' for p in matches[0].find('Ports')):
        raise ValueError('Native GameStart.OnStart contract is unavailable')


def validate_start_policy(blob, name):
    nodes = ET.fromstring(blob).find('./Skald/Project/Nodes')
    if nodes is None: raise ValueError('Missing campaign project')
    def one(tag, suffix):
        found = [n for n in nodes if n.tag == tag and n.get('Name') == name+suffix]
        if len(found) != 1: raise ValueError('Missing or ambiguous campaign entry: '+name+suffix)
        return found[0]
    one('GameStart', '_game_start')
    request = one('State', '_requested'); ready = one('State', '_ready')
    guard = one('IfFunction', '_new_game'); once = one('If', '_begin')
    sequence = one('TriggerSequence', '_initialize'); latch = one('State', '_started')
    if guard.get('MethodName') != 'math::boolean::And' or guard.get('DeclaringType') != 'math::boolean':
        raise ValueError('Invalid campaign entry condition')
    expected = [(request, 'SetTrue', [name+'_game_start.OnStart']),
                (request, 'SetFalse', [name+'_initialize.A']),
                (guard, 'Exec', [name+'_requested.OnExec', name+'_ready.OnExec']),
                (guard, 'A', [name+'_requested.State']), (guard, 'B', [name+'_ready.State']),
                (once, 'Exec', [name+'_new_game.True']),
                (once, 'Condition', [name+'_unstarted.bool']),
                (sequence, 'Exec', [name+'_begin.True']),
                (latch, 'SetTrue', [name+'_initialize.A'])]
    for node, port, sources in expected:
        if sorted(e.get('From') for e in node.findall('Edge') if e.get('To') == port) != sorted(sources):
            raise ValueError('Campaign initialization bypasses explicit start/once-only policy')
    for node in (request, ready):
        if node.find("Constant[@Name='DefaultValue'][@Value='false']") is None:
            raise ValueError('Campaign entry states must default to false')
    edges = ready.findall("Edge[@To='SetTrue']")
    if len(edges) != 1 or not edges[0].get('From') or edges[0].get('From').startswith(name+'_'):
        raise ValueError('Missing independent region readiness event')
    return dict(POLICY)


def gate_start(blob, name):
    """Latch native New Game and region readiness independently, then start once.

    Arrival alone cannot initialize a visitor. Both event orders are supported.
    The request is consumed before loadout/quest effects; saved start state remains.
    """
    root = ET.fromstring(blob); nodes = root.find('./Skald/Project/Nodes')
    if nodes is None: raise ValueError('Missing campaign project')
    if any(n.get('Name') == name+'_game_start' for n in nodes):
        validate_start_policy(blob, name); return blob
    def one(tag, suffix):
        found = [n for n in nodes if n.tag == tag and n.get('Name') == name+suffix]
        if len(found) != 1: raise ValueError('Missing or ambiguous campaign initialization chain')
        return found[0]
    sequence = one('TriggerSequence', '_initialize'); latch = one('State', '_started')
    once = one('If', '_begin')
    entry = once.findall("Edge[@To='Exec']")
    if len(entry) != 1: raise ValueError('Unrecognized campaign readiness entry')
    arrival = entry[0].get('From')
    legacy = [n for n in nodes if n.get('Name') == name+'_new_game']
    if legacy:
        if len(legacy) != 1 or legacy[0].get('MethodName') != LEGACY_METHOD:
            raise ValueError('Unrecognized previous campaign guard')
        nodes.remove(legacy[0])
        for edge in list(latch):
            if edge.get('From') == name+'_new_game.False' and edge.get('To') == 'SetTrue': latch.remove(edge)
    edges = sequence.findall("Edge[@To='Exec']")
    if len(edges) != 1 or edges[0].get('From') not in (name+'_begin.True',name+'_new_game.True'):
        raise ValueError('Unrecognized campaign initialization entry')
    edges[0].set('From', name+'_begin.True')
    entry[0].set('From', name+'_new_game.True')
    ET.SubElement(nodes, 'GameStart', Name=name+'_game_start')
    def edge(node, source, port): ET.SubElement(node, 'Edge', From=source, To=port)
    for suffix, event in (('_requested', name+'_game_start.OnStart'),('_ready', arrival)):
        state = ET.SubElement(nodes, 'State', Name=name+suffix, TypeT='bool')
        ET.SubElement(state, 'Constant', Name='DefaultValue', Value='false')
        edge(state, event, 'SetTrue')
        if suffix == '_requested': edge(state, name+'_initialize.A', 'SetFalse')
    guard = ET.SubElement(nodes, 'IfFunction', Name=name+'_new_game',
                          MethodName='math::boolean::And', DeclaringType='math::boolean')
    for suffix, port in (('_requested','A'),('_ready','B')):
        edge(guard, name+suffix+'.State', port)
        edge(guard, name+suffix+'.OnExec', 'Exec')
    result=xml(root); validate_start_policy(result,name); return result
