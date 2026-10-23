"""Import an explicitly selected opening's clock, only on its new-game edge.

The free-running campaign policy intentionally imports the starting hour, not
the source prologue's indefinite pause lock. Save loads and regional visits
must never reapply a new-game clock.
"""
from decimal import Decimal
import xml.etree.ElementTree as E

from campaign_intro_activity import normalized
from campaign_quest_start_placement import unique
from campaign_quest_graph import xml, edge, constant, identifier
from campaign_time import parse, time_of_day


def source_clock(blob, tree):
    selected = unique(normalized(blob).findall("BehaviorTree[@name='"+tree+"']"), 'opening clock tree')
    body = unique(selected.findall('Root/Behavior/Sequence'), 'opening sequence')
    # Only an unconditional, leading clock program can initialize the game.
    # Later/conditional time skips must stay attached to their source events.
    if not len(body) or body[0].tag != 'ExecuteLua':
        raise ValueError('Opening has no unconditional leading clock program')
    actions = parse(body[0].get('code', ''))
    forwards = [a for a in actions if a['kind'] == 'forward']
    if len(forwards) != 1 or actions[0] != forwards[0]:
        raise ValueError('Opening requires one initial clock advance')
    return dict(tree=tree, hour=format(Decimal(forwards[0]['hour']).normalize(), 'f'),
                source_actions=actions, policy='source_hour_free_running')


def bind(blob, clock, opening):
    """Splice before the existing guarded initialization; reject unsafe hooks."""
    identifier(opening)
    hour = Decimal(clock['hour'])
    if not hour.is_finite() or not 0 <= hour < 24:
        raise ValueError('Invalid opening hour')
    root = E.fromstring(blob)
    nodes = root.find('Skald/Project/Nodes')
    if nodes is None: raise ValueError('Missing opening project')
    from campaign_start_policy import validate_start_policy
    validate_start_policy(blob, opening)
    # Preserve the established once-only gate and latch. B starts the loadout;
    # insert the clock there after A has consumed the new-game request.
    name = opening+'_source_clock'
    existing = nodes.findall("*[@Name='"+name+"']")
    call = E.Element('Function',Name=name,MethodName='wh::rpgmodule::AdvanceWorldTime',
                     DeclaringType='wh::rpgmodule')
    constant(call,'TimeOfDay',time_of_day(hour))
    edge(call,opening+'_initialize.B','Exec')
    if existing:
        if len(existing) == 1 and existing[0].get('MethodName') == 'wh::conceptmodule::ExecuteConsoleString':
            legacy = existing[0]
            expected = '#forwardTime('+format(hour.normalize(),'f')+')'
            if legacy.find("Constant[@Name='Command']").get('Value') != expected:
                raise ValueError('Conflicting legacy opening clock')
            nodes.remove(legacy); nodes.append(call); existing = [call]
        if len(existing)!=1 or E.tostring(existing[0]).strip()!=E.tostring(call).strip():
            # Ignore formatting only, while checking the complete node contract.
            from character_city_benches import signature
            if len(existing)!=1 or signature(existing[0])!=signature(call):
                raise ValueError('Conflicting opening clock')
        if len(nodes.findall("*/Edge[@From='"+name+".OnExec'][@To='Exec']")) != 1:
            raise ValueError('Opening clock is disconnected')
        if nodes.findall("*/Edge[@From='"+opening+"_initialize.B'][@To='Exec']") != call_edges(existing[0]):
            raise ValueError('Opening initialization bypasses clock')
        return xml(root)
    incoming = unique(nodes.findall("*/Edge[@From='"+opening+"_initialize.B'][@To='Exec']"),
                      'opening loadout initialization event')
    nodes.append(call); incoming.set('From',name+'.OnExec')
    result = xml(root)
    validate_start_policy(result, opening)
    return result


def call_edges(node):
    return node.findall("Edge[@To='Exec']")
