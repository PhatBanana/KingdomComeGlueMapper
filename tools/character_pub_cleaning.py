"""Source-linked pub-table cleaning choices, without inventing a tavern routine.

Tables retain their authored Place1 contact and share an exclusive resource.
The native action owns animation completion; no guessed loop timer is used.
Order service, source phase sequencing and monologues are separate conversions.
"""
import copy
from pathlib import Path
import uuid
import xml.etree.ElementTree as E
import zipfile

from campaign_entity_links import append_links, guid_value
from character_city_benches import signature
from character_fence_work import placement
from character_person import resolve_link_targets, unique, world_entity
from character_station_work import unquote
from character_work_pool import bind, identity
from upgrade_map import read, xml

SOURCE = ('final/sa_pub_v3.xml', 'Bartender')
TEMPLATE = str(uuid.uuid5(uuid.NAMESPACE_URL, 'kingdomcomegluemapper/pub-table-cleaning/v1'))
PROGRAM = 'gluemapper/pub_table_cleaning.xml'
FRAGMENT = 'Bartender_CleaningTable'


def supports(entry):
    b = entry['behavior']
    return (b['tree_file'].replace('\\', '/').lower(), b['tree_name']) == SOURCE


def source_contract(pub, table):
    root = pub.find("BehaviorTree[@name='wiping']/Root")
    search = unique([] if root is None else root.findall('.//GraphSearch'), 'source pub cleaning search')
    if (any(unquote(search.get(k, '')) != v for k, v in dict(Origin='__area.id', depth='1',
            EdgePruning='parent', includeOrigin='false').items())
            or [n.tag for n in search] != ['CategoryFilter', 'Nodalyzer']
            or unquote(search[0].get('categories', '')) != 'pubTable'
            or unquote(search[1].get('Quantifiers', '')) != 'ForAll'
            or not any(unquote(n.get('BehaviorName', '')) == 'wiping' for n in root.iter('CallBehavior'))):
        raise ValueError('Source pub cleaning selection changed')
    leaf = table.find("BehaviorTree[@name='wiping']/Root")
    helper = None if leaf is None else leaf.find('.//GetHelper')
    align = None if leaf is None else leaf.find('.//GetAnimationHelperData')
    animation = None if leaf is None else leaf.find('.//PlayAnimation')
    semaphore = None if leaf is None else leaf.find('.//Semaphore')
    if (helper is None or unquote(helper.get('helperName', '')) != 'Place1'
            or align is None or unquote(align.get('fragment', '')) != FRAGMENT
            or animation is None or unquote(animation.get('animation', '')) != FRAGMENT
            or semaphore is None or unquote(semaphore.get('SemaphoreName', '')) != 'usePubTable'
            or unquote(semaphore.get('SemaphoreCount', '')) != '1'):
        raise ValueError('Source pub cleaning alignment/reservation changed')


def native_action(target):
    """Use the shipped standalone action, not the food-service tavern graph."""
    from campaign_work_animations import fragment_catalog
    target = Path(target)
    with zipfile.ZipFile(target/'Data/Scripts.pak') as z:
        root = E.fromstring(read(z, 'AI/quests/budovaniLazni/budovanilazni.xml')).find(
            "BehaviorTree[@name='bathmaid_cleaningTable']/Root/Behavior")
    if (root is None or len(root) != 1 or root[0].tag != 'AnimationAction'
            or root[0].get('fragment') != "'"+FRAGMENT+"'"
            or root[0].get('alignObject') != '$__object.id'
            or root[0].get('tags') or root[0].get('slaveObject')):
        raise ValueError('Native standalone table-cleaning action changed')
    catalog = fragment_catalog(target)['controller_variants']
    controllers = {k for k,v in catalog.items() if [] in v.get(FRAGMENT, [])}
    if not controllers:
        raise ValueError('Native table cleaning has no untagged human body animation')
    return copy.deepcopy(root[0]), controllers


def resources(target):
    action, _ = native_action(target)
    table = E.Element('database', name='barbora')
    template = E.SubElement(E.SubElement(table, 'SmartEntitys', version='1'),
        'SmartEntityTemplate', DatabaseId=TEMPLATE, Name='gm_pub_table_cleaning', UpdatePriority='false')
    behavior = E.SubElement(E.SubElement(template, 'BehaviorTemplates'), 'SmartBehaviorTemplate',
        Name='use', InitialState='Enabled', MaxInstances='1')
    E.SubElement(behavior, 'TreeLocation', FileName=PROGRAM, TreeName='use')
    trees = E.Element('BehaviorTrees')
    tree = E.SubElement(trees, 'BehaviorTree', name='use', is_function='0')
    E.SubElement(tree, 'Variables')
    root = E.SubElement(tree, 'Root', OneTimeOnly='false', FailState='Recoverable', saveVersion='2')
    E.SubElement(root, 'Behavior', canSkip='1').append(action)
    return {'Libs/Tables/ai/smartEntity/SmartEntity__gm_pub_table_cleaning.xml': xml(table),
            'AI/'+PROGRAM: xml(trees)}


def resolve(entry, archive, source, reader):
    blobs = reader(source, {'pub': ('Scripts.pak', 'Libs/AI/final/sa_pub_v3.xml'),
        'table': ('Scripts.pak', 'Libs/AI/final/so_pub_table_2.xml'),
        'helpers': ('GameData.pak', 'Libs/SmartObjects.xml')})
    source_contract(E.fromstring(blobs['pub']['data']), E.fromstring(blobs['table']['data']))
    helpers = E.fromstring(blobs['helpers']['data'])
    area = E.Element('Entity', entry['area']); links = E.SubElement(area, 'EntityLinks')
    for link in entry['target_links']:
        if 'parent' not in link.get('Name', '').split(','): E.SubElement(links, 'Link', link)
    entities = resolve_link_targets(archive, area, list(E.fromstring(read(archive, 'objects_mission0.xml'))), {})
    byid = {e.get('EntityId'): e for e in entities}; result = {}
    for link in links:
        node = byid[link.get('TargetId')]; props = node.find('Properties')
        if props is None or 'pubTable' not in props.get('sWH_AI_EntityCategory', '').split(','): continue
        if node.get('EntityClass') != 'SmartObjectHolder' or props.get('guidSmartObjectType', '').lower() != '1e8bdd40-b2d4-4216-8503-c1659e4b38e0':
            raise ValueError('Unsupported source pub table behavior template')
        family = props.get('soclasses_SmartObjectHelpers')
        helper = unique((h for h in helpers.findall('Helper') if h.get('className') == family
            and h.get('name') == 'Place1'), 'pub cleaning contact')
        result[node.get('EntityGuid')] = placement(world_entity(archive, node, entities), helper)
    return list(result.values())


def register(mission, contact):
    guid = identity('work/pub-cleaning/'+contact['EntityGuid'].lower())
    attrs = dict(Name='gm_pub_cleaning_'+contact['EntityGuid'].lower(), EntityGuid=guid,
        EntityClass='SmartObjectHolder', Pos=contact['Pos'], Rotate=contact['Rotate'])
    props = dict(guidSmartObjectType=TEMPLATE, bSaved_by_game='0')
    existing = [e for e in mission if e.get('EntityGuid') == guid or e.get('Name') == attrs['Name']]
    if existing:
        entity = unique(existing, 'shared pub cleaning resource')
        if (any(entity.get(k) != v for k,v in attrs.items()) or entity.find('Properties') is None
                or dict(entity.find('Properties').attrib) != props or entity.find('EntityLinks') is not None):
            raise ValueError('Modified pub cleaning resource; rebuild required')
    else:
        entity = E.SubElement(mission, 'Entity', EntityId=str(max(int(e.get('EntityId','0')) for e in mission)+1), **attrs)
        E.SubElement(entity, 'Properties', props)
    return entity, E.Element('C_SmartHub', EntityGuid=str(guid_value(guid)), IgnoreDeadEnds='false', StupidHub='false')


def upgrade_files(files, schedules, archive, target, source, reader):
    from character_city_work import native_contract
    mission = E.fromstring(files['objects_mission0.xml']); scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
    reports = []; waiting = []; contract = None
    for person, entries in schedules.items():
        actor = unique((e for e in mission if e.get('Name') == person), 'pub worker')
        for entry in entries:
            if not supports(entry): continue
            if not any(e.get('Name') == 'gm_schedule_'+person+'_'+entry['arrival']['EntityId'] for e in mission): continue
            if contract is None:
                _, controllers = native_action(target)
                _, activity, _ = native_contract(target)
                contract = controllers, activity
            controllers, activity = contract
            controller = 'female' if actor.get('EntityClass') == 'NPC_Female' else 'male'
            if controller not in controllers:
                reports.append(dict(person=person, job='pub_cleaning_pending', extension_only=True,
                    pending=['Native cleaning body animation unavailable for '+controller], runtime_verified=False)); continue
            contacts = resolve(entry, archive, source, reader)
            if not contacts: continue
            leaves = [register(mission, c) for c in contacts]
            pool, added, clock = bind(mission, scheduler, person, entry, 'pub_cleaning', leaves, activity)
            waiting.extend(added)
            reports.append(dict(person=person, job='source_pub_table_cleaning', extension_only=True,
                resources=[e.get('Name') for e,_ in leaves], intervals=clock, pool=pool.get('Name'),
                runtime_verified=False, pending=['Source bartender phase ordering, order service and wiping monologues']))
    return dict(files, **{'objects_mission0.xml': xml(mission), 'tables/ai/scheduler.xml': xml(scheduler),
        'waitinglinks.xml': append_links(files['waitinglinks.xml'], waiting, allow_untagged=True)}), reports


def extend_people(files, people, tables, archive, target, source, reader):
    from character_schedule import plan
    from character_schedule_world import resolve_arrivals
    from campaign_work_speech import requests, assess
    from campaign_dialogue import load
    names = {e.get('Name') for e in E.fromstring(files['objects_mission0.xml'])}
    schedules = {}
    for name, person in people.items():
        if name not in names: continue
        schedule = plan(person, tables)
        work = [e for e in schedule['resolved'] if supports(e)]
        if schedule['pending'] or not work: continue
        schedules[name] = resolve_arrivals(dict(schedule, resolved=work), archive, person, source, reader, target)
    if not schedules: return files, []
    result, reports = upgrade_files(files, schedules, archive, target, source, reader)
    from character_pub_rest import upgrade_files as upgrade_rest
    result, resting = upgrade_rest(result, schedules, archive, target, source, reader)
    reports.extend(resting)
    if reports:
        blob = reader(source, {'leaf': ('Scripts.pak', 'Libs/AI/final/so_pub_table_2.xml')})['leaf']['data']
        speech = [assess(r, load(Path(source), r['alias'])) for r in requests(blob, 'wiping')]
        for report in reports: report['speech_pending'] = speech
    return result, reports
