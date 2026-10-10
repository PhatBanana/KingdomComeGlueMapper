"""Compile the minimal native control world's AI contracts from entity links.

This intentionally supports only the link grammar exercised by the exported
control. Unsupported scheduler/delegate syntax fails rather than being copied
as an apparently valid static link. No character or region names are special.
"""
import copy
import xml.etree.ElementTree as ET

from campaign_entity_links import guid_value, append_links
from character_person_activity import validate_scheduler_targets
from upgrade_map import xml


def compile_world(mission, souls, level):
    entities = {e.get('EntityGuid'): e for e in mission}
    if len(entities) != len(mission):
        raise ValueError('Duplicate entity GUID')
    players = [s.findtext('EntityGuid') for s in souls if s.findtext('Player') == '1']
    if len(players) != 1:
        raise ValueError('Expected exactly one player soul')
    player = players[0]
    ET.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')
    scheduler = ET.Element('database', name='barbora')
    scheduler.set('{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation', '../database.xsd')
    rows = ET.SubElement(scheduler, 'Schedulers', version='1')
    hubs, static, streamed = {}, [], set()

    def hub(guid):
        number = str(guid_value(guid))
        if guid not in hubs:
            hubs[guid] = ET.SubElement(rows, 'C_SmartHub', EntityGuid=number,
                                      IgnoreDeadEnds='false', StupidHub='false')
        return hubs[guid]

    for guid, entity in entities.items():
        for link in entity.findall('EntityLinks/Link'):
            label, target = link.get('Name'), link.get('TargetGuid')
            if target not in entities:
                raise ValueError(f'Unresolved entity link: {label} -> {target}')
            if label == '^delegate':
                continue
            if label.startswith('^'):
                raise ValueError('Unsupported delegate syntax: ' + label)
            if label.startswith('_'):
                # Supported native labels: _,schedulerWait; _,60,!instant,...;
                # _199,!Instant,event_pocestny_playerIsPoisoned.
                parts = label[1:].split(',')
                priority, urgency = '0', None
                behavior = parts[-1]
                if not behavior or behavior.startswith(('!', '@')):
                    raise ValueError('Unsupported scheduler activity: ' + label)
                for token in parts[:-1]:
                    if not token:
                        continue
                    if token.isdigit(): priority = token
                    elif token.lower() == '!instant': urgency = 'Instant'
                    else: raise ValueError('Unsupported scheduler option: ' + token)
                delegate = '0'
                delegates = entities[target].findall("EntityLinks/Link[@Name='^delegate']")
                if delegates:
                    if len(delegates) != 1: raise ValueError('Ambiguous delegate')
                    delegate = str(guid_value(target))
                    target = delegates[0].get('TargetGuid')
                    if target not in entities: raise ValueError('Missing delegated target')
                row = hub(guid)
                links = row.find('Links')
                if links is None: links = ET.SubElement(row, 'Links')
                activity = ET.SubElement(links, 'S_ActivityLink',
                    PositioningDelegate=delegate, TargetGuid=str(guid_value(target)))
                params = dict(AllowedGenders='0', Angriness='0', Attraction='0',
                    BehaviorName=behavior, BehaviorOverride='false', GlobalRepulsion='0',
                    HaltOnInvalid='false', OneTimeUse='false', Priority=priority,
                    Privileged='false', Repulsion='0', TimeOfDayEnd='1440',
                    TimeOfDayStart='0', TimeVariation='0')
                if urgency: params['Urgency'] = urgency
                ET.SubElement(activity, 'Parameters', **params)
                hub(target)
            else:
                if label == 'playerLinkRerouter':
                    target = player
                    streamed.add(player)
                static.append((guid, target, label))
    validate_scheduler_targets(scheduler)
    waiting = ET.fromstring(append_links(None, static))
    if streamed:
        container = ET.SubElement(waiting, 'StreamableTargets')
        for guid in sorted(streamed): ET.SubElement(container, 'StreamableTarget', TargetId=guid)
    wh = ET.Element('Root', version='1')
    soul_list = ET.SubElement(ET.SubElement(wh, 'SoulList'), 'Souls')
    for soul in souls: soul_list.append(copy.deepcopy(soul))
    ai = ET.SubElement(wh, 'AI')
    ET.SubElement(ai, 'LevelPath').text = 'data/levels/' + level
    areas = ET.SubElement(ET.SubElement(ai, 'SmartAreaManager', version='2'), 'SmartAreas')
    for guid, entity in entities.items():
        if entity.get('EntityClass') == 'SmartAreaShape':
            ET.SubElement(ET.SubElement(areas, 'SmartArea'), 'Guid').text = str(guid_value(guid))
    ET.SubElement(ET.SubElement(wh, 'ConceptManager'), 'IncludeModGraphs').text = '0'
    return {'tables/ai/scheduler.xml': xml(scheduler), 'waitinglinks.xml': xml(waiting),
            'whdata_0': xml(wh)}


def semantic_xml(blob):
    """Ignore formatting, attribute order and collection order for parity checks."""
    def node(e):
        return (e.tag, tuple(sorted(e.attrib.items())), (e.text or '').strip(),
                tuple(sorted((node(c) for c in e), key=repr)))
    return node(ET.fromstring(blob))
