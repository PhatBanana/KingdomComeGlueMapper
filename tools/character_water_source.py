"""Resolve household buckets, tubs and wells from authored area relationships."""
import xml.etree.ElementTree as E

from character_crime_districts import contains
from character_person import unique
from character_person_world import source_home_geometry
from character_station_work import unquote


def source_contract(program):
    root = program.find("BehaviorTree[@name='bucketFill']/Root")
    searches = [] if root is None else root.findall('.//GraphSearch')
    if len(searches) != 5:
        raise ValueError('Unsupported source bucket selection graph')
    city, local, remote, tub, bucket = searches
    if (any(unquote(city.get(k, '')) != v for k, v in dict(
            Origin='__area.id', depth='-1', SubGraph='parent', EdgePruning='child').items())
            or city.find('HasBehaviorFilter') is None
            or unquote(city[0].get('BehaviorList', '')) != 'Waterfill_waterTube_refill'):
        raise ValueError('Unsupported source water parent query')
    for search, origin, categories in ((local, '__area.id', ['WaterRefillSpot', 'Well']),
            (remote, 'city', ['WaterRefillSpot', 'Well']), (tub, '__area.id', ['Watertub']),
            (bucket, '__area.id', ['bucket'])):
        if (any(unquote(search.get(k, '')) != v for k, v in dict(Origin=origin,
                depth='1', EdgePruning='parent', SubGraph='', AllowedEdges='', includeOrigin='false').items())
                or [unquote(n.get('categories', '')) for n in search.findall('CategoryFilter')] != categories):
            raise ValueError('Unsupported source water resource query')
    reserve = root.find('.//ReserveBehavior')
    call = root.find('.//CallBehavior')
    if (reserve is None or unquote(reserve.get('behaviorName', '')) != 'useItem'
            or unquote(reserve.get('reserveFrom', '')) != 't_bucketSlot'
            or call is None or unquote(call.get('Target', '')) != 't_bucketSlot'
            or unquote(call.get('BehaviorName', '')) != 'useItem'):
        raise ValueError('Source bucket reservation changed')


def bucket_contract(program, helpers):
    root = program.find("BehaviorTree[@name='Waterfill_waterTube_refill']/Root")
    calls = [] if root is None else [(unquote(n.get('Target', '')), unquote(n.get('BehaviorName', '')))
                                     for n in root.iter('CallBehavior')]
    if calls != [('t_fillSpot', 'use'), ('t_waterTube', 'manageQueue')]:
        raise ValueError('Source water fill/return sequence changed')
    expressions = '\n'.join(unquote(n.get('expressions', '')) for n in root.iter('Expression'))
    if "$t_queue_params.actionBehavior.behavior = 'refill_tube'" not in expressions:
        raise ValueError('Source destination tub no longer requests refill')
    gate = unique((h for h in helpers.iter('Helper') if h.get('className') == 'Well'
                   and h.get('name') == 'gate'), 'source well alignment helper')
    if (tuple(map(float, gate.get('pos').split(','))) != (0,0,0)
            or tuple(map(float, gate.get('rot').split(','))) != (1,0,0,0)):
        raise ValueError('Source well alignment requires a new native pose mapping')


def category(entity):
    props = entity.find('Properties')
    return set() if props is None else set(props.get('sWH_AI_EntityCategory', '').split(','))


def children(area, entities, categories):
    found = {}
    for link in area.findall('EntityLinks/Link'):
        if 'parent' in link.get('Name', '').split(','): continue
        target = entities.get(link.get('TargetId'))
        if target is None: raise ValueError('Unresolved source water-area link')
        if category(target).intersection(categories): found[target.get('EntityId')] = target
    return list(found.values())


def city_templates(tables):
    behaviors = {r['sa_behaviour_tag_id'] for r in tables.get('ai/sa_behaviour_tag')['rows']
        if r['sa_behaviour_tag_name'] == 'Waterfill_waterTube_refill'
        and r['tree_file'].replace('\\', '/').lower() == 'final/so_bucket.xml'
        and r['tree_name'] == 'Waterfill_waterTube_refill'}
    return {r['sa_smart_area_id'] for r in tables.get('ai/sa_smart_area2sa_behaviour_tag')['rows']
        if r['sa_behaviour_tag_id'] in behaviors}


def resolve(entry, entities, templates):
    home = entities[entry['area']['EntityId']]
    tubs = children(home, entities, {'Watertub'})
    buckets = children(home, entities, {'bucket'})
    if not tubs or not buckets:
        raise ValueError('Source household lacks a tub or bucket')
    # The source parent graph is generated from area containment. Require one
    # unambiguous containing provider, rather than selecting a nearby town/well.
    position = tuple(map(float, home.get('Pos').split(',')))
    providers = [e for e in entities.values() if e.get('EntityClass') == 'SmartAreaShape'
        and e.find('Properties') is not None
        and e.find('Properties').get('guidSmartAreaTemplate') in templates
        and contains(source_home_geometry(e), position)]
    city = unique(providers, 'household water city')
    wells = children(home, entities, {'WaterRefillSpot', 'Well'})
    origin = home
    if not wells:
        origin = city
        wells = children(city, entities, {'WaterRefillSpot', 'Well'})
    if not wells: raise ValueError('Source household has no linked water source')
    return dict(tubs=tubs, buckets=buckets, sources=wells, provider=origin)


def conflicting_tools(resolved):
    """A shared native tub cannot silently borrow another home's bucket pool."""
    owners = {}
    for result in resolved:
        tools = frozenset(e.get('EntityGuid') for e in result['buckets'])
        for tub in result['tubs']: owners.setdefault(tub.get('EntityId'), set()).add(tools)
    return {key for key, pools in owners.items() if len(pools) > 1}
