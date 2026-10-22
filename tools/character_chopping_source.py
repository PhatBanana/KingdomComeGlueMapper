"""Resolve housework wood stations from the source area's actual behavior binding."""
import xml.etree.ElementTree as E

from character_person import unique, resolve_link_targets, world_entity
from character_fence_work import placement
from character_station_work import unquote
from upgrade_map import read


def selection_contract(program):
    root = program.find("BehaviorTree[@name='pickWoodBasket']/Root")
    reserve = None if root is None else root.find('.//ReserveBehavior')
    if reserve is None or any(unquote(reserve.get(k, '')) != v for k, v in
            dict(reserveFrom='chopBlock', behaviorName='woodChopping').items()):
        raise ValueError('Source chopping reservation changed')
    searches = reserve.findall('Search/ReserveBehaviorSearch/Sequence/GraphSearch')
    expected = [('ChopBlock', 'chopBlock', 'parent'), ('woodForSplitting', 't_logPile', 'parent,inventory'),
                ('choppedWood', 't_choppedWood', 'parent,inventory')]
    if len(searches) != 3: raise ValueError('Source chopping searches changed')
    for search, (category, child, prune) in zip(searches, expected):
        attrs = dict(Origin='__area.id', depth='1', EdgePruning=prune, includeOrigin='false',
                     AllowedEdges='', SubGraph='', SetOperationChoice='Intersection|And')
        category_filter = search.find('CategoryFilter')
        if (any(unquote(search.get(k, '')) != v for k, v in attrs.items()) or category_filter is None
                or unquote(category_filter.get('categories', '')) != category
                or unquote(category_filter.get('Child', '')) != child
                or [c.tag for c in search] != (['CategoryFilter', 'HasBehaviorFilter'] if category == 'ChopBlock' else ['CategoryFilter'])):
            raise ValueError('Source chopping query changed')
    behavior = searches[0].find('HasBehaviorFilter')
    call = reserve.find('.//CallBehavior')
    if (unquote(behavior.get('BehaviorList', '')) != 'woodChopping'
            or unquote(behavior.get('FilterChoice', '')) != 'Requestable'
            or call is None or unquote(call.get('Target', '')) != 'chopBlock'
            or unquote(call.get('BehaviorName', '')) != 'woodChopping'):
        raise ValueError('Source chopping behavior changed')


def source_contract(entry, tables, program):
    definitions = {r['sa_behaviour_tag_id']: r for r in tables.get('ai/sa_behaviour_tag')['rows']}
    bindings = tables.get('ai/sa_smart_area2sa_behaviour_tag')['rows']
    matches = [definitions[b['sa_behaviour_tag_id']] for b in bindings
        if b['sa_smart_area_id'] == entry['area_template']['sa_smart_area_id']
        and definitions[b['sa_behaviour_tag_id']]['sa_behaviour_tag_name'] == 'choppingWood']
    if not matches: return False
    behavior = unique(matches, 'source chopping binding')
    if (behavior['tree_file'].replace('\\', '/').lower(), behavior['tree_name']) != ('final/sa_warehouse.xml', 'pickWoodBasket'):
        return False  # Source test/lab bindings do not describe this activity.
    selection_contract(program)
    return True


def resolve(entry, archive, helpers):
    area = E.Element('Entity', entry['area']); edges = E.SubElement(area, 'EntityLinks')
    for link in entry['target_links']:
        if 'parent' not in link.get('Name', '').split(','): E.SubElement(edges, 'Link', link)
    entities = resolve_link_targets(archive, area, list(E.fromstring(read(archive, 'objects_mission0.xml'))), {})
    by_id = {e.get('EntityId'): e for e in entities}
    groups = {}
    for category in ('ChopBlock', 'woodForSplitting', 'choppedWood'):
        found = {}
        for link in edges:
            if category != 'ChopBlock' and 'inventory' in link.get('Name', '').split(','): continue
            e = by_id[link.get('TargetId')]; p = e.find('Properties')
            if p is not None and category in p.get('sWH_AI_EntityCategory', '').split(','):
                found[e.get('EntityId')] = e
        if not found: return None
        groups[category] = unique(found.values(), 'source '+category)
    block, collect, unload = [groups[k] for k in ('ChopBlock', 'woodForSplitting', 'choppedWood')]
    expected = [(block, 'c9fc15ae-8f3a-42eb-9b27-068daabd4142'),
                (collect, '2838f932-d89e-4bd4-be25-d908040f4503'), (unload, '047402f7-3893-4ae3-aa91-e0567fda7971')]
    for e, template in expected:
        if e.get('EntityClass') != 'SmartObjectHolder' or e.find('Properties').get('guidSmartObjectType', '').lower() != template:
            raise ValueError('Unsupported chopping workplace template')
        entities = resolve_link_targets(archive, e, entities, {})
    by_id = {e.get('EntityId'): e for e in entities}
    def child(parent, category):
        return unique((by_id[l.get('TargetId')] for l in parent.findall('EntityLinks/Link')
            if not l.get('Name') and by_id[l.get('TargetId')].find('Properties') is not None
            and category in by_id[l.get('TargetId')].find('Properties').get('sWH_AI_EntityCategory', '').split(',')), category)
    basket, axe, log = child(block, 'BasketSlot'), child(block, 'Axe'), child(block, 'WoodChips_ChoppingBlock')
    collect_slot, unload_slot = child(collect, 'BasketSlot'), child(unload, 'BasketSlot')
    for e in (basket, axe): entities = resolve_link_targets(archive, e, entities, {})
    # Detach parents before register_item evaluates item world transforms.
    needed = {e.get('EntityId') for e in (block, basket, axe, log, collect_slot, unload_slot)}
    needed.update(l.get('TargetId') for e in (basket, axe) for l in e.findall('EntityLinks/Link'))
    by_id = {e.get('EntityId'): world_entity(archive, e, entities) for e in entities if e.get('EntityId') in needed}
    def contact(entity, family, name):
        if entity.find('Properties').get('soclasses_SmartObjectHelpers') != family:
            raise ValueError('Source chopping contact family changed')
        helper = unique((h for h in helpers.iter('Helper') if h.get('className') == family and h.get('name') == name), 'chopping contact')
        return placement(by_id[entity.get('EntityId')], helper)
    return dict(identity=block.get('EntityGuid').lower(),
        contacts=dict(chopping=contact(block, 'Log_for_splitting', 'choppingBlockPivot'),
                      collect=contact(collect_slot, 'Basket_logsForWarehouse', 'slotHelper'),
                      setAside=contact(unload_slot, 'Basket_logsForHouse', 'slotHelper')),
        basket=by_id[basket.get('EntityId')], axe=by_id[axe.get('EntityId')], log=by_id[log.get('EntityId')], entities=by_id)
