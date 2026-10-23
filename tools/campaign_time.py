"""Convert bounded source clock programs and named pause locks to native Skald."""
import hashlib
import re
from decimal import Decimal
import xml.etree.ElementTree as ET
from campaign_quest_bridge import UnsupportedOperation
from campaign_quest_graph import definition, identifier, xml, constant, edge


def parse(script):
    token = re.compile(r"\s*(?:forwardTime\(\s*(\d+(?:\.\d*)?)\s*\)|"
                       r"Utils\.SetWorldTimePaused\(\s*(true|false)\s*,\s*(['\"])([^'\"\r\n]+)\3\s*\))\s*;?")
    actions, position = [], 0
    while script[position:].strip():
        match = token.match(script, position)
        if not match:
            raise UnsupportedOperation('Clock program requires a semantic adapter; no partial clock actions emitted')
        if match[1] is not None:
            hour = Decimal(match[1])
            if not 0 <= hour < 24:
                raise UnsupportedOperation('Clock target must be a source hour in [0,24)')
            actions.append(dict(kind='forward', hour=format(hour, 'f')))
        else:
            actions.append(dict(kind='pause', active=match[2] == 'true', reason=match[4]))
        position = match.end()
    # Shipped TriggerSequence users include A..I. Bound this adapter to A..H;
    # e.g. rutinaAVypad/.../vyber_muzu_pro_vypad.xml uses the H output.
    if not actions or len(actions) > 8:
        raise UnsupportedOperation('Clock program requires one to eight ordered operations')
    return actions


def time_of_day(hour):
    seconds = Decimal(hour) * 3600
    if not seconds.is_finite() or not 0 <= seconds < 86400 or seconds != int(seconds):
        raise ValueError('Clock target must resolve to a whole second within one day')
    h, rest = divmod(int(seconds), 3600); m, sec = divmod(rest, 60)
    return f'{h:02d}h{m:02d}m' + (f'{sec:02d}s' if sec else '')


class TimeBridge:
    def __init__(self, namespace):
        self.namespace = identifier(namespace)
        self.actions = {}

    def lower(self, script, site):
        actions = parse(script)
        name = self.namespace + '_clock_' + hashlib.sha256(script.encode()).hexdigest()[:20]
        record = self.actions.setdefault(name, dict(actions=actions, source=script, sites=[]))
        record['sites'].append(site)
        return ET.Element('SendAIConceptSignal_' + name)

    def emit(self):
        root, module = definition('Module', self.namespace + '_time_bridge')
        nodes = ET.SubElement(module, 'Nodes')
        database = ET.Element('database')
        signals = ET.SubElement(database, 'AIConceptSignalDatabase', version='1')
        locks = {}
        for record in self.actions.values():
            for action in record['actions']:
                if action['kind'] != 'pause' or action['reason'] in locks:
                    continue
                name = 'lock_' + hashlib.sha256(action['reason'].encode()).hexdigest()[:20]
                locks[action['reason']] = name
                state = ET.SubElement(nodes, 'State', Name=name, TypeT='bool')
                constant(state, 'DefaultValue', 'false')
                pause = ET.SubElement(nodes, 'PauseWorldTime', Name=name + '_pause')
                edge(pause, name + '.State', 'IsActive')
        for name, record in sorted(self.actions.items()):
            ET.SubElement(signals, 'AIConceptSignal', Name=name)
            trigger = ET.SubElement(nodes, 'AIConceptSignalTrigger', Name=name, NotificationName=name)
            constant(trigger, 'IsActive', 'true')
            sequence = ET.SubElement(nodes, 'TriggerSequence', Name=name + '_ordered')
            edge(sequence, name + '.OnNotification', 'Exec')
            for index, action in enumerate(record['actions']):
                event = name + '_ordered.' + chr(ord('A') + index)
                if action['kind'] == 'pause':
                    state = nodes.find("State[@Name='" + locks[action['reason']] + "']")
                    edge(state, event, 'SetTrue' if action['active'] else 'SetFalse')
                else:
                    # Use the retail RPG node, preserving forward-only day rollover.
                    call = ET.SubElement(nodes, 'Function', Name=name + '_hour_' + str(index),
                        MethodName='wh::rpgmodule::AdvanceWorldTime', DeclaringType='wh::rpgmodule')
                    constant(call, 'TimeOfDay', time_of_day(action['hour']))
                    edge(call, event, 'Exec')
        return {'Quests/' + self.namespace + '_time_bridge.xml': xml(root),
                'Libs/Tables/ai/AIConceptSignalDatabase__' + self.namespace.lower() + '_time.xml': xml(database)}
