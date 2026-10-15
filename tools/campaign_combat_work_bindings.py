"""Resolve work dependencies through authored links and native contracts."""
import copy
import uuid
import xml.etree.ElementTree as E
import zipfile
from campaign_bindings import parse_link_labels
from campaign_entity_links import native_guid
from campaign_combat_plan import one
from campaign_quest_graph import xml
from upgrade_map import read


def element(ast):
    node = E.Element(ast['op'], ast['attributes'])
    for child in ast['children']:
        node.append(element(child))
    return node


def bind(stem, plan, bindings, roles, objects, home, native_game, asset, additions,
         compiled_scheduler, activity_template):
    """Return runtime assets and a dedicated behavior host, never change sa_land."""
    aftermath = plan['outcomes']['won'].get('aftermath')
    if not aftermath:
        raise ValueError('Combat work conversion requires a resolved aftermath program')
    world = bindings['_world']
    entities = {e.get('EntityGuid'): e for e in objects}
    def add(name, cls, guid, pos, properties, rotation=None):
        if guid in entities:
            raise ValueError('Generated work entity identity collision: ' + guid)
        node = E.SubElement(objects, 'Entity', Name=name, EntityClass=cls, EntityGuid=guid,
            EntityId=str(max(int(e.get('EntityId', '0')) for e in objects) + 1), Pos=pos)
        if rotation: node.set('Rotate', rotation)
        node.append(copy.deepcopy(properties))
        entities[guid] = node
        return node
    role = aftermath['work']['role']
    record = one((b for b in bindings['bindings'] if any(
        t['tag'] == 'QuestPlace' and t.get('positional') == [role] for t in (b.get('label') or []))),
        'Missing source work role: ' + role)
    source = element(world['entities'][record['entity']]['entity'])
    props = source.find('Properties')
    # This is a source helper ABI adapter, shared by all ground sitting spots.
    # Other helpers must supply their own alignment/stance adapter.
    if props.get('soclasses_SmartObjectHelpers') != 'sitGround':
        raise ValueError('Unconverted source sitting helper: ' + str(props.attrib))
    with zipfile.ZipFile(native_game / 'Data/Tables.pak') as z:
        template = E.fromstring(read(z, 'Libs/Tables/ai/smartEntity/SmartEntity__so_sitPlace.xml')).find('SmartEntitys/SmartEntityTemplate')
    if template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='use']") is None:
        raise ValueError('Native sitting use behavior is unavailable')
    # Validate a shipped ground-sitting placement before adopting its helper.
    with zipfile.ZipFile(native_game / 'Data/Levels/trosecko/level.pak') as z:
        native = E.fromstring(read(z, 'objects_mission0.xml'))
    placement = next((e for e in native
        if e.find('Properties') is not None and e.find('Properties').get('guidSmartObjectType') == template.get('DatabaseId')
        and e.find('Properties/Script') is not None and e.find('Properties/Script').get('Misc') == 'isGroundPlace:true'), None)
    if placement is None:
        raise ValueError('Missing native ground-sitting placement')
    guid = record['registration']['guid']
    spot = entities.get(guid)
    if spot is None:
        spot = add(stem + '_work_place', placement.get('EntityClass'), guid,
            record['transform']['Pos'], placement.find('Properties'), record['transform'].get('Rotate'))
    elif spot.find('Properties') is None or spot.find('Properties').get('guidSmartObjectType') != template.get('DatabaseId'):
        raise ValueError('Existing work placement has an incompatible native template')
    work_asset = asset('SmartObjectAsset', stem + '_work_place', spot)
    area_link = one(home.findall("EntityLinks/Link[@Name='home_area']"), 'Missing native Home area')
    area = entities[area_link.get('TargetGuid')]
    if area.get('EntityClass') != 'TriggerArea':
        raise ValueError('Home privacy target is not a native trigger area')
    area_asset = asset('TriggerAreaAsset', stem + '_home_area', area)
    cleanup = plan.get('preparation')
    tool_asset = None
    if cleanup:
        actor = roles[plan['actor_role']]['entity']
        def labels(link):
            text = link['source_link'].get('Name', '')
            return {v['tag'].lower() for v in parse_link_labels(text)} if text.strip() else set()
        source_home = one((l['to'] for l in world['links'] if l['from'] == actor and 'home' in labels(l)), 'Missing source actor Home')
        frontier, visited = {source_home}, {source_home}
        candidates = []
        for _ in range(cleanup['depth']):
            adjacent = {l['to'] for l in world['links'] if l['from'] in frontier and l.get('to')
                        and not labels(l).intersection({'parent', 'inventory'})}
            frontier = adjacent - visited
            visited.update(frontier)
            for key in frontier:
                e = element(world['entities'][key]['entity'])
                if e.tag == 'Entity' and e.get('EntityClass') == 'ItemSlot' and e.find('Properties').get('guidItemClassId', '').lower() == cleanup['item_class'].lower():
                    candidates.append((key, e))
        if candidates:
            key, source_slot = one(candidates, 'Ambiguous source cleanup slot')
            identities = {native_guid(int(source_slot.get('EntityGuid'), 16))}
            # World item conversion may promote the slot's pickable child.
            for link in world['links']:
                if link['from'] == key and link.get('to') and 'slotlink' in labels(link):
                    identities.add(native_guid(int(world['entities'][link['to']]['attributes']['EntityGuid'], 16)))
            slot = one((e for g, e in entities.items() if g in identities and e.get('EntityClass') == 'ItemSlot'),
                       'Source cleanup slot/item has not been imported')
            if slot.find('Properties').get('guidItemClassId', '').lower() != cleanup['item_class'].lower():
                raise ValueError('Cleanup item identity requires the item importer mapping')
            tool_asset = asset('ItemSlotAsset', stem + '_tool_slot', slot)
    host_guid = native_guid(uuid.uuid5(uuid.NAMESPACE_URL, stem + '/work-host').int & ((1 << 64) - 1))
    template_id = str(uuid.uuid5(uuid.NAMESPACE_URL, stem + '/work-template'))
    host = add(stem + '_work_host', 'SmartObjectHolder', host_guid, home.get('Pos'),
               E.Element('Properties', guidSmartObjectType=template_id, bSaved_by_game='0'))
    host_asset = asset('SmartObjectAsset', stem + '_work_host', host)
    from campaign_behavior_schedule import connect, source_policy
    actor_entity = entities[roles[plan['actor_role']]['registration']['guid']]
    routine_priority, routine_speed = source_policy(plan['outcomes']['won']['schedule_patch'])
    for phase in ('prepare', 'privacy', 'routine'):
        # Native immediate quest actions use _199,!Instant. The continuing
        # routine retains its authored daycycle priority instead.
        priority, speed = (routine_priority, routine_speed) if phase == 'routine' else (199, 'Instant')
        connect(objects, additions, actor_entity, host, phase, priority, speed, stem + '_work_' + phase,
                compiled_scheduler, activity_template)
    table = E.Element('database', name='barbora')
    templ = E.SubElement(E.SubElement(table, 'SmartEntitys', version='1'), 'SmartEntityTemplate',
                         DatabaseId=template_id, Name=stem + '_work', UpdatePriority='false')
    bs = E.SubElement(templ, 'BehaviorTemplates')
    for name in ('prepare', 'privacy', 'routine'):
        b = E.SubElement(bs, 'SmartBehaviorTemplate', Name=name, InitialState='Disabled', MaxInstances='-1', PreventsMonsterLod='true')
        E.SubElement(b, 'TreeLocation', FileName=stem + '_work.xml', TreeName=name)
    return dict(host=host_asset, tool=tool_asset, area=area_asset, place=work_asset), {
        'Libs/Tables/ai/smartEntity/SmartEntity__' + stem + '_work.xml': xml(table)}
