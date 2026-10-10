"""Apply native world contracts verified by the generated combat control.

Merge into the existing world; do not replace quest, shop or scheduler data.
"""
import copy
import uuid
import xml.etree.ElementTree as ET

from campaign_entity_links import append_links, guid_value, native_guid
from character_person_activity import validate_scheduler_targets
from upgrade_map import read, xml


def apply(files, native_level):
    files = dict(files)
    mission = ET.fromstring(files['objects_mission0.xml'])
    land = next(e for e in mission if e.get('Name') == 'sa_land')
    native = ET.fromstring(read(native_level, 'objects_mission0.xml'))
    native_wh = ET.fromstring(read(native_level, 'whdata_0'))
    players = [s.findtext('EntityGuid') for s in native_wh.findall('SoulList/Souls/Soul')
               if s.findtext('Player') == '1']
    if len(players) != 1: raise ValueError('Expected native player identity')
    player = players[0]
    added = []
    def service(name):
        existing = [e for e in mission if e.get('Name') == name]
        if len(existing) > 1: raise ValueError('Duplicate world service: '+name)
        if existing: return existing[0]
        templates = [e for e in native if e.get('Name') == name]
        if len(templates) != 1: raise ValueError('Missing native service: '+name)
        entity = copy.deepcopy(templates[0])
        for child in list(entity):
            if child.tag != 'Properties': entity.remove(child)
        for key in ('Layer','EditorLayer','ParentId'): entity.attrib.pop(key,None)
        guid = native_guid(int.from_bytes(uuid.uuid5(uuid.NAMESPACE_URL,'gluemapper/world-service/'+name).bytes[:8],'little'))
        if any(e.get('EntityGuid') == guid for e in mission): raise ValueError('Service GUID collision')
        entity.set('EntityGuid',guid)
        entity.set('EntityId',str(max(int(e.get('EntityId','0')) for e in mission)+1))
        entity.set('Pos',land.get('Pos'))
        mission.append(entity); added.append(name)
        return entity
    links = land.find('EntityLinks')
    if links is None: links = ET.SubElement(land,'EntityLinks')
    static = []
    for label, name in [('playerLinkRerouter','PlayerLinkRerouter'),('hangoverSpotsHub','hangoverSpotsHub')]:
        entity = service(name)
        link = links.find("Link[@Name='"+label+"']")
        if link is None: link = ET.SubElement(links,'Link',Name=label)
        link.set('TargetGuid',entity.get('EntityGuid'));link.set('TargetId',entity.get('EntityId'))
        static.append((land.get('EntityGuid'),player if label == 'playerLinkRerouter' else entity.get('EntityGuid'),label))
    scheduler = ET.fromstring(files['tables/ai/scheduler.xml'])
    validate_scheduler_targets(scheduler)
    scheduled = {r.get('EntityGuid') for r in scheduler.find('Schedulers')}
    waiting = ET.fromstring(files['waitinglinks.xml'])
    removed = []
    for link in list(waiting.find('WaitingLinks')):
        for definition in list(link.findall('LinkDefinition')):
            label = definition.text or ''
            if label.startswith('_') or label == '^delegate':
                if label.startswith('_') and str(guid_value(link.get('SourceId'))) not in scheduled:
                    raise ValueError('Authoring link has no compiled scheduler: '+label)
                removed.append(dict(source=link.get('SourceId'),target=link.get('TargetId'),label=label))
                link.remove(definition)
            elif label == 'playerLinkRerouter' and link.get('TargetId') != player:
                link.remove(definition)  # Rebind to the native player below.
        if not link.findall('LinkDefinition'): waiting.find('WaitingLinks').remove(link)
    waiting = ET.fromstring(append_links(xml(waiting),static))
    stream = waiting.find('StreamableTargets')
    if stream is None: stream = ET.SubElement(waiting,'StreamableTargets')
    if not any(e.get('TargetId') == player for e in stream):
        ET.SubElement(stream,'StreamableTarget',TargetId=player)
    ET.indent(waiting)
    helpers = read(native_level,'smartobjecthelpersetanimations.xml')
    if ET.fromstring(helpers).tag != 'SmartObjectAnimationCollections':
        raise ValueError('Unexpected native animation-helper schema')
    files.update({'objects_mission0.xml':xml(mission),'waitinglinks.xml':xml(waiting),
                  'smartobjecthelpersetanimations.xml':helpers})
    return files, dict(added_services=added,player=player,removed_authoring_links=removed,
        animation_helper_bytes=len(helpers),runtime_verified=False)
