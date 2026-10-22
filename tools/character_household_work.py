"""Source-linked cooking and needlework choices for existing household routines.

No actor names, invented locations or copied Trosky NPC schedules are used.
Native resource reservations, stance actions and fireplace effects are retained.
The source phase dispatcher and unsupported chores remain explicitly pending.
"""
import copy
from pathlib import Path
import re
import xml.etree.ElementTree as E
import zipfile

from campaign_entity_links import append_links, guid_value
from character_city_benches import prepare_sources
from character_fence_work import supports
from character_person import unique
from character_station_work import unquote
from character_work_capabilities import housework_phases
from character_work_pool import bind, source_job
from upgrade_map import read, xml


def cooking_source_contract(program):
    root = program.find("BehaviorTree[@name='Cooking']/Root")
    searches = [] if root is None else root.findall('.//GraphSearch')
    search = unique(searches, 'household cooking source search')
    expected = dict(Origin='__area.id', depth='1', EdgePruning='parent', includeOrigin='false',
                    AllowedEdges='', SubGraph='', SetOperationChoice='Intersection|And')
    if (any(unquote(search.get(k, '')) != v for k, v in expected.items())
            or [c.tag for c in search] != ['UnionOp', 'HasBehaviorFilter', 'Nodalyzer']
            or [unquote(c.get('categories', '')) for c in search[0]] != ['Furnace', 'fireplace']
            or any(c.tag != 'CategoryFilter' or unquote(c.get('Source', '')) != 'Child' for c in search[0])
            or unquote(search[1].get('BehaviorList', '')) != 'Cooking'
            or unquote(search[1].get('FilterChoice', '')) != 'Requestable'
            or not any(unquote(c.get('Target', '')) == 'furnace' and
                       unquote(c.get('BehaviorName', '')) == 'Cooking' for c in root.iter('CallBehavior'))):
        raise ValueError('Unsupported household cooking source selection')


def native_cooking(target):
    target = Path(target)
    with zipfile.ZipFile(target/'Data/Tables.pak') as z:
        template = E.fromstring(read(z, 'Libs/Tables/ai/smartEntity/SmartEntity__so_fireplace.xml')).find('.//SmartEntityTemplate')
    behavior = template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='cooking']")
    resource = template.find("Resources/Resource[@Name='use']")
    if (behavior is None or behavior.get('InitialState') != 'Enabled' or behavior.get('Resource') != 'use'
            or resource is None or resource.get('MaxInstances') != '1'):
        raise ValueError('Native cooking resource contract changed')
    loc = behavior.find('TreeLocation')
    with zipfile.ZipFile(target/'Data/Scripts.pak') as z:
        root = E.fromstring(read(z, 'AI/'+loc.get('FileName'))).find("BehaviorTree[@name='"+loc.get('TreeName')+"']/Root")
    if (root is None or root.find(".//UnstanceAction[@unstance='housekeeper_cooking_home'][@locationObject='$__object.id']") is None
            or not any(n.get('type') == "'kettle:signal:onCooking'" for n in root.iter('InstantSendMessageToNPC'))):
        raise ValueError('Native cooking action/completion contract changed')
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as z:
        mission = E.fromstring(read(z, 'objects_mission0.xml'))
        rows = E.fromstring(read(z, 'tables/ai/scheduler.xml')).find('Schedulers')
    entities = {str(guid_value(e.get('EntityGuid'))): e for e in mission.iter('Entity')
        if e.get('EntityClass') == 'FireplaceSmartObject' and e.find('Properties') is not None
        and e.find('Properties').get('guidSmartObjectType') == template.get('DatabaseId')}
    activity = next((copy.deepcopy(l) for l in rows.findall('.//S_ActivityLink') if l.get('TargetGuid') in entities
        and l.get('PositioningDelegate') == '0' and l.find('Parameters') is not None
        and all(l.find('Parameters').get(k) == v for k, v in dict(BehaviorName='cooking',
            BehaviorOverride='false', ProvidedRole='cooking', AllowedGenders='0', Priority='0',
            Privileged='false', TimeOfDayStart='0', TimeOfDayEnd='1440').items())
        and not any(k in l.find('Parameters').attrib for k in ('RequiredRole', 'RequiredContext', 'LinkTag', 'BuffTag'))), None)
    if activity is None: raise ValueError('Missing native cooking activity')
    leaves = {}
    for row in rows:
        entity = entities.get(row.get('EntityGuid'))
        if entity is None or row.tag != 'C_SmartHub': continue
        leaf = copy.deepcopy(row)
        # Eating links borrow native benches. Cooking terminates at the fire;
        # preserve its self effects/initializers without importing those seats.
        for links in leaf.findall('Links'): leaf.remove(links)
        if any(n.get('TargetGuid') != row.get('EntityGuid') for n in leaf.iter() if n.get('TargetGuid')):
            continue
        if leaf.find(".//ElementInitializerEnableBehaviorForNPC[@Role='cooking']") is None: continue
        leaves[entity.get('EntityId')] = leaf
    return template.get('DatabaseId'), activity, leaves


def cooking_resources(entry, mission, pots, native):
    template, activity, leaves = native
    linked = {l['TargetId'] for l in entry['target_links'] if 'parent' not in l.get('Name', '').split(',')}
    selected = []
    for pot, owner, kind in pots:
        props = owner.find('Properties')
        if owner.get('EntityId') not in linked or props is None or not set(
                props.get('sWH_AI_EntityCategory', '').split(',')).intersection({'Furnace', 'fireplace'}): continue
        pattern = re.compile(r'gm_cooking_'+re.escape(pot.get('EntityId'))+r'_(\d+)')
        matches = [(e, pattern.fullmatch(e.get('Name', ''))) for e in mission if e.get('EntityClass') == 'FireplaceSmartObject']
        entity, match = unique(((e, m) for e, m in matches if m), 'converted household fireplace')
        if entity.find('Properties') is None or entity.find('Properties').get('guidSmartObjectType') != template:
            raise ValueError('Incompatible converted household fireplace')
        # Validate effects against the exact native root used by pot conversion.
        leaf = copy.deepcopy(leaves.get(match[1]))
        if leaf is None: raise ValueError('Missing native household fireplace scheduler effects')
        old = leaf.get('EntityGuid'); new = str(guid_value(entity.get('EntityGuid')))
        leaf.set('EntityGuid', new)
        for n in leaf.iter():
            if n.get('TargetGuid') == old: n.set('TargetGuid', new)
        selected.append((entity, leaf))
    return selected, activity


def binding(entry, phase, tables):
    definitions = {r['sa_behaviour_tag_id']: r for r in tables.get('ai/sa_behaviour_tag')['rows']}
    choices = [definitions[b['sa_behaviour_tag_id']] for b in tables.get('ai/sa_smart_area2sa_behaviour_tag')['rows']
        if b['sa_smart_area_id'] == entry['area_template']['sa_smart_area_id']
        and definitions[b['sa_behaviour_tag_id']]['sa_behaviour_tag_name'] == phase]
    result = unique(choices, 'source household '+phase+' binding')
    expected = ('final/sa_home.xml', 'Cooking') if phase == 'Cooking' else ('final/sa_embroider.xml', 'embroider_sit')
    if (result['tree_file'].replace('\\', '/').lower(), result['tree_name']) != expected:
        raise ValueError('Unsupported source household '+phase+' binding')
    return result


def upgrade(files, schedules, archive, target, source, reader, tables):
    import cooking_pots
    import character_seated_work as seated
    import character_home_rest as rest
    mission = E.fromstring(files['objects_mission0.xml']); scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
    program = E.fromstring(reader(source, {'home': ('Scripts.pak', 'Libs/AI/final/sa_home.xml')})['home']['data'])
    reports = []; waiting = []; done = set(); cooking = None; inventory = None
    for person, entries in schedules.items():
        actor = unique((e for e in mission if e.get('Name') == person), 'household actor')
        phases = housework_phases(program.find("BehaviorTree[@name='housework']"), actor.get('EntityClass'))
        for entry in entries:
            if not supports(entry): continue
            if not any(e.get('Name') == 'gm_schedule_'+person+'_'+entry['arrival']['EntityId'] for e in mission):
                continue  # Quest/service-controlled workers have no owned arrival to extend.
            for phase in ('Cooking', 'embroider_sit', 'hangingOut'):
                key = person, entry['arrival']['EntityId'], phase
                if phase not in phases or key in done: continue
                done.add(key)
                if phase != 'hangingOut': binding(entry, phase, tables)
                template = None
                if phase == 'Cooking':
                    cooking_source_contract(program)
                    if cooking is None: cooking = native_cooking(target)
                    if inventory is None: inventory = cooking_pots.inventory(archive)
                    resources, activity = cooking_resources(entry, mission, inventory[1], cooking)
                elif phase == 'embroider_sit':
                    resolved = seated.resolve(entry, archive, source, reader)
                    template, _ = seated.native_contract(target)
                    seats, activity = prepare_sources(mission, resolved['seated_work']['seats'], target)
                    if any('_Table_' in seat.find('Properties').get('soclass_SmartObjectHelpers', '')
                           or seat.find("EntityLinks/Link[@Name='withTable']") is not None for seat in seats):
                        raise ValueError('Converted household needlework bench has a table')
                    activity.find('Parameters').set('BehaviorName', 'embroidery')
                    activity.find('Parameters').set('BehaviorOverride', 'true')
                    activity.find('Parameters').set('AllowedGenders', '2')
                    resources = [(seat, E.Element('C_SmartHub', EntityGuid=str(guid_value(seat.get('EntityGuid'))),
                        IgnoreDeadEnds='false', StupidHub='false')) for seat in seats]
                else:
                    rest.source_contract(entry, tables, program)
                    seats, activity = prepare_sources(mission, rest.resolve(entry, archive), target)
                    resources = [(seat, E.Element('C_SmartHub', EntityGuid=str(guid_value(seat.get('EntityGuid'))),
                        IgnoreDeadEnds='false', StupidHub='false')) for seat in seats]
                    _, _, original = source_job(mission, scheduler, person, entry)
                    old_hub = next(r for r in scheduler.find('Schedulers') if r.get('EntityGuid') == original[0].get('TargetGuid'))
                    existing_seats = {l.get('TargetGuid') for l in old_hub.findall('Links/S_ActivityLink')
                        if l.find('Parameters').get('BehaviorName') == 'use'}
                    if resources and all(str(guid_value(e.get('EntityGuid'))) in existing_seats for e, _ in resources):
                        continue  # The earlier rest adapter already supplies this choice.
                if not resources:
                    reports.append(dict(person=person, job='native_home_'+phase, extension_only=True,
                        pending=['No unconditional source-linked resource; weather-dependent choices require their dispatcher'], runtime_verified=False))
                    continue
                pool, added, clock = bind(mission, scheduler, person, entry, phase, resources, activity, template=template)
                waiting.extend(added)
                reports.append(dict(person=person, job='native_home_'+phase, extension_only=True, source_behavior=entry['behavior'],
                    source_area=entry['area'], intervals=clock, resources=[e.get('Name') for e, _ in resources],
                    pool=pool.get('Name'), runtime_verified=False,
                    pending=['Source housework phase ordering and duration; native scheduler choice only']))
    return dict(files, **{'objects_mission0.xml': xml(mission), 'tables/ai/scheduler.xml': xml(scheduler),
        'waitinglinks.xml': append_links(files['waitinglinks.xml'], waiting, allow_untagged=True)}), reports
