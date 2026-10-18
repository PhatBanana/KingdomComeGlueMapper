"""Bind imported RPG initialization to an existing once-only campaign entry.

Values and the entry point are supplied by the source importer. This module
does not select a quest, actor, dialogue, or a particular starting level.
"""
import math
import re
import xml.etree.ElementTree as ET

from campaign_quest_graph import constant, edge, identifier, xml
from campaign_scene import STATS


def quest_start_states(behavior):
    """Extract unconditional player-state calls from source quest-start messages.

    Do not harvest assignments out of arbitrary nested conditions or loops.
    The receipt preserves the asset readiness prerequisite for the caller.
    """
    root = ET.fromstring(behavior)
    parents = {c: p for p in root.iter() for c in p}
    values, receipt = {}, []
    for message in root.iter('ProcessMessage'):
        variable = message.get('variable', '').strip('"')
        if message.get('inbox', '').strip('"') != 'QuestMailbox': continue
        for gate in message.findall('./Switch/IfCondition'):
            if gate.get('condition', '').strip('"').replace(' ', '') != '$' + variable + '.State==$enum:QuestState.Started':
                continue
            for node in gate.findall('./Sequence/ExecuteLua'):
                script = node.get('code', '').strip('"')
                if 'player.soul:SetState' not in script: continue
                pattern = r"player\.soul:SetState\(\s*'([a-z]+)'\s*,\s*(\d+(?:\.\d+)?)\s*\)"
                matches = re.findall(pattern, script)
                if not matches or re.sub(pattern, '', script).strip(' ;\r\n\t'):
                    raise ValueError('Compound source state initializer needs conversion')
                prerequisites = []
                ancestor = gate
                while ancestor in parents:
                    ancestor = parents[ancestor]
                    if ancestor.tag == 'ExternalLock':
                        prerequisites.append(ancestor.get('SemaphoreName', '').strip('"'))
                for state, value in matches:
                    if state in values: raise ValueError('Multiple source initializers for state: ' + state)
                    values[state] = float(value)
                    receipt.append(dict(state=state, value=float(value), event='QuestState.Started',
                                        readiness_locks=prerequisites, source_script=script))
    return values, receipt


def source_stats(soul):
    result = {}
    for source, native in STATS.items():
        value = float(soul[source])
        if not math.isfinite(value) or value < 1 or not value.is_integer():
            raise ValueError('Invalid source starting stat: ' + source)
        result[native] = int(value)
    return result


def bind_before(blob, destination, input_port, source_event, soul_asset,
                namespace, stats, skills, states, definitions):
    """Splice a synchronous initializer before one caller-owned trigger edge.

    The caller must select an entry protected by its existing persisted New
    Game latch. Never attach this to level load: it would erase earned levels.
    Native advancement methods establish minimum levels. They do not reset
    higher inherited levels; report that policy explicitly. Debug setters are
    not a retail runtime contract even when listed in definitions.xml.
    """
    identifier(namespace)
    root = ET.fromstring(blob)
    hosts = list(root.find('Skald'))
    if len(hosts) != 1:
        raise ValueError('Expected one native graph host')
    host = hosts[0]
    nodes = host.find('Nodes')
    targets = [n for n in nodes if n.get('Name') == destination]
    if len(targets) != 1:
        raise ValueError('Missing or ambiguous initializer destination')
    links = [e for e in targets[0].findall('Edge')
             if e.get('From') == source_event and e.get('To') == input_port]
    if len(links) != 1:
        raise ValueError('Expected exact initialization edge; refusing to reset a different lifecycle')
    if host.find("Assets/SoulAsset[@Name='" + soul_asset + "']") is None:
        raise ValueError('Missing initializer soul asset')
    registry = ET.fromstring(definitions)
    operations = []
    for kind, values, typ, method, selector, enum in (
        ('stat', stats, 'MemberFunction', 'AdvanceToStatLevel', 'Stat', 'SoulStat'),
        ('skill', skills, 'MemberFunction', 'AdvanceToSkillLevel', 'Skill', 'SoulSkill'),
        ('state', states, 'MemberFunction', 'SetState', 'State', 'SoulState')):
        allowed = {e.get('Name') for t in registry.iter('Type')
                   if t.get('TypeName') == 'wh::rpgmodule::' + enum for e in t.findall('Enumeration')}
        abi = [d for d in registry.iter('Definition') if d.get('TypeName') == typ
               and d.find("Properties/Property[@Name='MethodName'][@Value='" + method + "']") is not None]
        if values and len(abi) != 1:
            raise ValueError('Missing native initialization method: ' + method)
        for name, value in sorted(values.items()):
            if name not in allowed:
                raise ValueError('Unknown native ' + kind + ': ' + name)
            number = float(value)
            if not math.isfinite(number) or number < 0 or (kind != 'state' and not number.is_integer()):
                raise ValueError('Invalid initial ' + kind + ' value')
            if kind == 'state' and number > 100:
                raise ValueError('Initial state outside validated percentage range')
            operations.append((kind, name, value, typ, method, selector))
    if not operations:
        raise ValueError('Empty initializer')
    previous = source_event
    for kind, name, value, typ, method, selector in operations:
        node_name = namespace + '_' + kind + '_' + identifier(name)
        if any(n.get('Name') == node_name for n in nodes):
            raise ValueError('Initializer already registered: ' + node_name)
        node = ET.SubElement(nodes, typ, Name=node_name, MethodName=method,
                             DeclaringType='wh::rpgmodule' if typ == 'Function' else 'wh::rpgmodule::I_Soul')
        ET.SubElement(node, 'Asset', Name='Soul', Alias=soul_asset)
        constant(node, selector, name); constant(node, 'Value' if kind == 'state' else 'Level', str(value))
        edge(node, previous, 'Exec')
        previous = node_name + '.OnExec'
    links[0].set('From', previous)
    return xml(root), dict(stats=stats, skills=skills, states=states,
                           source_event=source_event, destination=destination + '.' + input_port,
                           soul_asset=soul_asset, level_policy='advance_to_minimum', runtime_verified=False)


def upgrade_debug_initializers(blob, namespace, definitions):
    """Migrate generated initializers without changing lifecycle or values.

    The explicit namespace limits this to importer-owned nodes. Arbitrary
    gameplay debug calls are not assumed to have equivalent semantics.
    """
    identifier(namespace)
    registry = ET.fromstring(definitions)
    root = ET.fromstring(blob)
    changes = []
    for kind, method, selector in [('stat', 'AdvanceToStatLevel', 'Stat'),
                                   ('skill', 'AdvanceToSkillLevel', 'Skill')]:
        legacy = 'wh::rpgmodule::Set' + kind.title() + 'LevelDebug'
        selected = [n for n in root.iter('Function')
                    if n.get('Name', '').startswith(namespace+'_'+kind+'_')
                    and n.get('MethodName') == legacy]
        if not selected: continue
        abi = [d for d in registry.iter('Definition') if d.get('TypeName') == 'MemberFunction'
               and d.find("Properties/Property[@Name='MethodName'][@Value='"+method+"']") is not None
               and d.find("Properties/Property[@Name='DeclaringType'][@Value='wh::rpgmodule::I_Soul']") is not None]
        if len(abi) != 1: raise ValueError('Missing retail initializer: '+method)
        ports = {p.get('Name'): p.get('Type') for p in abi[0].findall('Ports/*')}
        if ports.get('Level') != 'uint' or ports.get('OnExec') != 'trigger':
            raise ValueError('Unsupported retail initializer ABI: '+method)
        for node in selected:
            value = node.find("Constant[@Name='Value']")
            if value is None or node.find("Constant[@Name='"+selector+"']") is None:
                raise ValueError('Unsupported generated initializer: '+node.get('Name'))
            node.tag = 'MemberFunction'
            node.set('MethodName', method)
            node.set('DeclaringType', 'wh::rpgmodule::I_Soul')
            value.set('Name', 'Level')
            changes.append(node.get('Name'))
    return (xml(root) if changes else blob), dict(nodes=changes,
        level_policy='advance_to_minimum', runtime_verified=False)
