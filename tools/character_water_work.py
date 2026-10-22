"""Source household water refill using a shared native well and authored bucket.

Only the native female refill contract is enabled. This adds a job choice;
source housework ordering and unsupported water-resource families stay pending.
"""
import copy
import xml.etree.ElementTree as E

from campaign_entity_links import append_links, guid_value
from character_city_benches import signature
from character_fence_work import supports
from character_job_items import register_item, bind_reservation
from character_person import unique, world_entity
from character_water_source import source_contract, bucket_contract, city_templates, resolve, conflicting_tools
from character_work_pool import bind, identity
from character_work_capabilities import housework_phases
from cooking_pots import rotate, vector
from entity_visuals import world_transform, quaternion_product
from upgrade_map import xml


def connect(a, b, name):
    links = a.find('EntityLinks')
    if links is None: links = E.SubElement(a, 'EntityLinks')
    existing = [l for l in links if l.get('Name') == name and l.get('TargetGuid') == b.get('EntityGuid')]
    if existing:
        if len(existing) != 1 or existing[0].get('TargetId') != b.get('EntityId'):
            raise ValueError('Conflicting water link identity')
    else: E.SubElement(links, 'Link', Name=name, TargetGuid=b.get('EntityGuid'), TargetId=b.get('EntityId'))
    return a.get('EntityGuid'), b.get('EntityGuid'), name


def well_group(mission, source, entities, contract):
    props = source.find('Properties')
    donor = contract['well']; originals = dict(contract['group'], holder=donor)
    model = contract['group']['animObject'].find('Properties').get('object_Model', '').lower().removeprefix('data/')
    if (source.get('EntityClass') != 'AnimObject' or props is None
            or props.get('object_Model', '').lower() != model
            or props.get('soclasses_SmartObjectHelpers') != 'Well'):
        raise ValueError('Water source needs a separate native interaction adapter')
    sp, sq, ss = world_transform(source, entities)
    if any(abs(v-1) > .001 for v in ss): raise ValueError('Scaled well is unsupported')
    native_entities = {e.get('EntityId'): e for e in originals.values()}
    dp, dq, _ = world_transform(donor, native_entities)
    delta = quaternion_product(sq, (dq[0], -dq[1], -dq[2], -dq[3]))
    next_id = max(int(e.get('EntityId', '0')) for e in mission)+1
    group = {}; fresh = []
    for role, original in originals.items():
        guid = identity('water-well/'+source.get('EntityGuid')+'/'+role)
        name = 'gm_schedule_water_source_'+source.get('EntityId')+'_'+role
        old = [e for e in mission if e.get('EntityGuid') == guid or e.get('Name') == name]
        node = copy.deepcopy(original)
        for attr in ('Prefab', 'EditorLayer', 'Layer', 'ParentId', 'ParentGuid'): node.attrib.pop(attr, None)
        for links in node.findall('EntityLinks'): node.remove(links)
        node.set('EntityGuid', guid); node.set('Name', name)
        node.set('EntityId', old[0].get('EntityId') if len(old) == 1 else str(next_id)); next_id += 1
        p, q, _ = world_transform(original, native_entities)
        offset = rotate(delta, tuple(a-b for a,b in zip(p,dp)))
        node.set('Pos', vector(tuple(a+b for a,b in zip(sp,offset))))
        node.set('Rotate', vector(quaternion_product(delta,q)))
        if old:
            expected = copy.deepcopy(old[0])
            for links in expected.findall('EntityLinks'): expected.remove(links)
            if len(old) != 1 or signature(expected) != signature(node):
                raise ValueError('Existing water well differs from native contract')
            node = old[0]
        else: fresh.append(node)
        group[role] = node
    visual = [e for e in mission if e.get('Name') == 'glue_item_'+source.get('EntityId')]
    if fresh and (len(fresh) != 3 or len(visual) != 1):
        raise ValueError('Incomplete source well conversion')
    if not fresh and visual: raise ValueError('Duplicate well visual')
    mission.extend(fresh)
    for e in visual: mission.remove(e)
    waiting = [connect(group['holder'], group[role], role) for role in ('animObject', 'slot')]
    leaf = copy.deepcopy(contract['well_leaf'])
    leaf.set('EntityGuid', str(guid_value(group['holder'].get('EntityGuid'))))
    return (group['holder'], leaf), waiting


def refill_graph(mission, scheduler, tub, sources, contract):
    """Extend only the known wash leaf, preserving its clean interaction."""
    number = str(guid_value(tub.get('EntityGuid')))
    row = unique((r for r in scheduler.find('Schedulers') if r.get('EntityGuid') == number), 'wash tub scheduler')
    planned = copy.deepcopy(row)
    expected_soil = copy.deepcopy(contract['tub_row'].find(".//EffectSoil[@Role='refillWatertube']"))
    effects = planned.find('PostSearchData/SmartHubPostSearchData/SchedulerEffect')
    if effects is None or effects.find('EffectClean') is None:
        raise ValueError('Water refill requires an existing native wash effect')
    soil = effects.find('EffectSoil')
    if soil is None: effects.insert(0, expected_soil)
    elif signature(soil) != signature(expected_soil): raise ValueError('Conflicting refill soil effect')
    # Preserve the native tub -> source pool -> well graph. The tub's override
    # owns the action while the final well is its exclusive resource.
    guid = identity('water-source-pool/'+tub.get('EntityGuid'))
    found = [e for e in mission if e.get('EntityGuid') == guid]
    if found:
        pool = unique(found, 'water source pool')
        if pool.get('EntityClass') != 'SchedulerHub': raise ValueError('Conflicting water source pool')
    else:
        pool = E.Element('Entity', Name='gm_schedule_water_pool_'+guid, EntityGuid=guid,
                         EntityClass='SchedulerHub', Pos=tub.get('Pos'),
                         EntityId=str(max(int(e.get('EntityId', '0')) for e in mission)+1))
        E.SubElement(pool, 'Properties', bSaved_by_game='0')
    pool_row = E.Element('C_SmartHub', EntityGuid=str(guid_value(guid)),
                         IgnoreDeadEnds='false', StupidHub='false', Position=pool.get('Pos'))
    pool_links = E.SubElement(pool_row, 'Links')
    for source, _ in sources:
        edge = copy.deepcopy(contract['well_edge']); edge.set('TargetGuid', str(guid_value(source.get('EntityGuid'))))
        pool_links.append(edge)
    outgoing = []
    edge = copy.deepcopy(contract['source_edge']); edge.set('TargetGuid', str(guid_value(guid)))
    outgoing.append(edge)
    existing = planned.find('Links')
    if existing is None: E.SubElement(planned, 'Links').extend(outgoing)
    elif sorted(signature(e) for e in existing) != sorted(signature(e) for e in outgoing):
        raise ValueError('Existing tub has different refill resources')
    # Commit only after all graph properties have been checked.
    if signature(row) != signature(planned):
        row.clear(); row.attrib.update(planned.attrib); row.extend(copy.deepcopy(list(planned)))
    if not found: mission.append(pool)
    waiting = [connect(tub, pool, contract['source_definition'])]
    waiting.extend(connect(pool, e, '_,refillWatertube') for e, _ in sources)
    connect(tub, tub, '+Soil[refillWatertube,1]')
    waiting.append((tub.get('EntityGuid'), tub.get('EntityGuid'), '+Soil[refillWatertube,1]'))
    return (tub, copy.deepcopy(row)), (pool, pool_row), waiting


def upgrade(files, schedules, archive, target, source, reader, tables, registered):
    from chairs import inventory
    from character_water_native import load
    mission = E.fromstring(files['objects_mission0.xml'])
    scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
    blobs = reader(source, {'home': ('Scripts.pak', 'Libs/AI/final/sa_home.xml'),
                            'bucket': ('Scripts.pak', 'Libs/AI/final/so_bucket.xml'),
                            'helpers': ('GameData.pak', 'Libs/SmartObjects.xml')})
    program = E.fromstring(blobs['home']['data'])
    source_contract(program)
    bucket_contract(E.fromstring(blobs['bucket']['data']), E.fromstring(blobs['helpers']['data']))
    entities = None; native = None; templates = city_templates(tables)
    selections = {}
    for person, entries in schedules.items():
        actor = unique((e for e in mission if e.get('Name') == person), 'water worker')
        if 'bucketFill' not in housework_phases(program.find("BehaviorTree[@name='housework']"), actor.get('EntityClass')):
            continue
        for entry in entries:
            if not supports(entry): continue
            if not any(e.get('Name') == 'gm_schedule_'+person+'_'+entry['arrival']['EntityId'] for e in mission): continue
            if entities is None: entities, _, _ = inventory(archive)
            area_id = entry['area']['EntityId']
            if area_id not in selections: selections[area_id] = resolve(entry, entities, templates)
    conflicts = conflicting_tools(selections.values())
    waiting = []; reports = []; done = set()
    for person, entries in schedules.items():
        actor = unique((e for e in mission if e.get('Name') == person), 'water worker')
        if 'bucketFill' not in housework_phases(program.find("BehaviorTree[@name='housework']"), actor.get('EntityClass')):
            continue
        for entry in entries:
            if not supports(entry): continue
            if not any(e.get('Name') == 'gm_schedule_'+person+'_'+entry['arrival']['EntityId'] for e in mission): continue
            key = person, entry['arrival']['EntityId']
            if key in done: continue
            done.add(key)
            report = dict(person=person, job='native_home_bucketFill', extension_only=True, runtime_verified=False)
            if actor.get('EntityClass') != 'NPC_Female':
                reports.append(dict(report, pending=['Source water chore requires a validated male native refill contract']))
                continue
            if entities is None: entities, _, _ = inventory(archive)
            if native is None: native = load(target)
            resolved = selections[entry['area']['EntityId']]
            shared = sorted(t.get('EntityId') for t in resolved['tubs'] if t.get('EntityId') in conflicts)
            if shared:
                reports.append(dict(report, shared_tubs=shared,
                    pending=['Shared source tub has different household bucket pools; needs actor-scoped tool reservations']))
                continue
            if any(e.get('EntityClass') != 'AnimObject' for e in resolved['sources']):
                reports.append(dict(report, pending=['Source water-resource family requires an adapter']))
                continue
            tubs = [unique((e for e in mission if e.get('Name') == 'gm_wash_'+t.get('EntityId')+'_SmartObjectHolder'),
                           'converted household tub') for t in resolved['tubs']]
            if any(t.find('Properties').get('guidSmartObjectType') != native['tub_template'] for t in tubs):
                raise ValueError('Converted tub has incompatible native template')
            resources = []
            for s in resolved['sources']:
                pair, links = well_group(mission, s, entities, native)
                resources.append(pair); waiting.extend(links)
            slots = []
            for s in resolved['buckets']:
                detached = world_entity(archive, s, list(entities.values()))
                linked = dict(entities); linked[s.get('EntityId')] = detached
                for l in s.findall('EntityLinks/Link'):
                    child = entities.get(l.get('TargetId'))
                    if child is not None: linked[child.get('EntityId')] = world_entity(archive, child, list(entities.values()))
                slot, _ = register_item(mission, detached, linked, native['bucket'], registered)
                slots.append(slot)
            destinations = []; dependencies = list(resources)
            for tub in tubs:
                for slot in slots: waiting.extend(bind_reservation(mission, tub, slot, native['bucket']))
                pair, pool_pair, links = refill_graph(mission, scheduler, tub, resources, native)
                dependencies.append(pool_pair)
                destinations.append(pair); waiting.extend(links)
            pool, links, clock = bind(mission, scheduler, person, entry, 'bucketFill', destinations,
                                      native['activity'], dependencies=dependencies)
            waiting.extend(links)
            reports.append(dict(report, pool=pool.get('Name'), intervals=clock,
                source_area=entry['area'], source_provider=resolved['provider'].get('EntityId'),
                sources=[s.get('EntityId') for s in resolved['sources']],
                buckets=[s.get('EntityId') for s in resolved['buckets']],
                tubs=[t.get('EntityId') for t in resolved['tubs']],
                pending=['Source housework ordering/duration and live pickup, well, pour and return verification']))
    return dict(files, **{'objects_mission0.xml': xml(mission), 'tables/ai/scheduler.xml': xml(scheduler),
        'waitinglinks.xml': append_links(files['waitinglinks.xml'], waiting, allow_untagged=True)}), reports
