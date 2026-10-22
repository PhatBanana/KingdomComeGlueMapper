"""Source-selected native wood chopping added to importer-owned housework pools.

The native job owns basket/axe handling and its collect/chop/store cycle. This
does not claim to reproduce the source's complete ordered housework controller.
"""
import copy
import hashlib
from pathlib import Path
import xml.etree.ElementTree as E

from campaign_dependency_adapters import SourceTables
from campaign_entity_links import append_links, guid_value, native_guid
from campaign_sources import RetailSourceReader
from character_city_benches import choices, signature
from character_fence_work import supports
from character_job_items import register_item
from character_person import unique
from character_schedule_world import ARRIVAL_TEMPLATE
from character_work_capabilities import housework_phases
from character_chopping_source import source_contract, resolve
from character_chopping_native import native_contract, relocate, graph
from upgrade_map import xml


def identity(value):
    return native_guid(int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], 'little'))


def owned_pool(mission, scheduler, person, entry, clock):
    actor = unique((e for e in mission if e.get('Name') == person), 'wood worker')
    job = unique((e for e in mission if e.get('Name') == 'gm_schedule_'+person+'_'+entry['arrival']['EntityId']), 'housework pool')
    expected = identity('schedule-arrival/'+actor.get('EntityGuid')+'/'+entry['arrival']['EntityGuid'])
    rows = scheduler.find('Schedulers'); key = str(guid_value(job.get('EntityGuid')))
    hub = unique((r for r in rows if r.get('EntityGuid') == key), 'housework scheduler')
    uses = [(r, l) for r in rows for l in r.findall('Links/S_ActivityLink') if l.get('TargetGuid') == key]
    if (actor.get('EntityClass') != 'NPC' or job.get('EntityGuid') != expected or hub.tag != 'C_SmartHub'
            or job.find('Properties') is None or not uses
            or any(r.get('EntityGuid') != str(guid_value(actor.get('EntityGuid'))) or l.find('Parameters') is None for r,l in uses)):
        raise ValueError('Cannot extend non-owned housework pool')
    incoming = [l for _,l in uses]
    actual = {(int(l.find('Parameters').get('TimeOfDayStart')), int(l.find('Parameters').get('TimeOfDayEnd'))) for l in incoming}
    from character_sleep_work import waking_work_clock
    effective_clock = waking_work_clock(mission, scheduler, actor, clock)
    if actual != effective_clock: raise ValueError('Chopping clock differs from source and owned sleep')
    if job.get('EntityClass') == 'SmartObjectHolder':
        if (job.find('Properties').get('guidSmartObjectType') != ARRIVAL_TEMPLATE or len(hub)
                or job.findall('EntityLinks/Link') or any(l.find('Parameters').get('BehaviorName') != 'use' for l in incoming)):
            raise ValueError('Cannot replace non-owned housework arrival')
    elif job.get('EntityClass') == 'SchedulerHub':
        if (dict(job.find('Properties').attrib) != dict(bSaved_by_game='0') or hub.find('Links') is None
                or any(l.find('Parameters').get('BehaviorName') for l in incoming)
                or any(c.tag != 'Links' for c in hub)):
            raise ValueError('Cannot extend foreign housework controller')
        entities = {str(guid_value(e.get('EntityGuid'))): e for e in mission if e.get('EntityGuid')}
        outgoing = hub.findall('Links/S_ActivityLink')
        if not outgoing: raise ValueError('Empty existing housework pool')
        for link in outgoing:
            target = entities.get(link.get('TargetGuid')); p = link.find('Parameters')
            if (target is None or p is None or p.get('BehaviorName') != 'use'
                    or not target.get('Name', '').startswith(('gm_schedule_fence_', 'gm_bench_', 'gm_schedule_chopping_'))
                    or (int(p.get('TimeOfDayStart')), int(p.get('TimeOfDayEnd'))) not in clock | effective_clock):
                raise ValueError('Foreign activity in housework pool')
        authored = {(l.get('TargetGuid'), l.get('Name')) for l in job.findall('EntityLinks/Link')}
        expected_edges = {(entities[l.get('TargetGuid')].get('EntityGuid'), '_,use') for l in outgoing}
        if authored != expected_edges: raise ValueError('Housework authoring/scheduler links disagree')
    else: raise ValueError('Cannot extend non-owned housework entity')
    return actor, job, hub, incoming


def promote(mission, source, station, native, registered):
    """Replace one authored phase prop with its native item, retaining its identity."""
    original = source.find('Properties').get('guidItemClassId', '').lower()
    wanted = native.find('Properties').get('guidItemClassId').lower()
    if original not in registered or wanted not in registered:
        raise ValueError('Unregistered chopping item')
    entities = copy.deepcopy(station['entities']); slot = entities[source.get('EntityId')]
    slot.set('EntityClass', 'ItemSlot')
    candidates = [slot] + [entities[l.get('TargetId')] for l in slot.findall('EntityLinks/Link') if l.get('Name') == 'SlotLink']
    for e in candidates:
        if e.find('Properties').get('guidItemClassId', '').lower() != original:
            raise ValueError('Chopping prop and slot disagree')
        guid = native_guid(int(e.get('EntityGuid'), 16))
        existing = [n for n in mission if n.get('EntityGuid') == guid]
        if existing:
            node = unique(existing, 'chopping source prop')
            if node.get('EntityClass') != 'ItemSlot' or node.find('Properties').get('guidItemClassId') not in (registered[original], registered[wanted]):
                raise ValueError('Conflicting chopping prop identity')
            # A quest or another activity may own this tool. Do not repurpose it.
            if any(l.get('TargetGuid') == guid for n in mission for l in n.findall('EntityLinks/Link')):
                raise ValueError('Chopping prop has another owner')
            node.find('Properties').set('guidItemClassId', registered[wanted])
        e.find('Properties').set('guidItemClassId', wanted)
    slot, report = register_item(mission, slot, entities, dict(item_id=wanted, properties=native.find('Properties')), registered)
    props = copy.deepcopy(native.find('Properties'))
    props.set('bSaveBorrowedItem', '1')
    slot.remove(slot.find('Properties')); slot.append(props)
    # Reused world pickups need the same animation-registration path as new
    # job tools; retain their GUID so ownership/save references remain valid.
    slot.set('Name', 'gm_job_item_chopping_'+source.get('EntityGuid').lower())
    for field in ('Pos', 'Rotate'): slot.set(field, native.get(field, '1,0,0,0'))
    slot.attrib.pop('Scale', None)
    report['source_item'] = original
    return slot, report


def workstation(mission, rows, station, contract, registered):
    roles = contract['roles']; key = 'work/chopping/'+station['identity']
    group = dict(job='chopping', pivot='chopping', axe='chopping', log='chopping', half='chopping',
        chopBasket='chopping', reservation='chopping', basket='chopping', collect='collect', collectBasket='collect', unload='setAside', unloadBasket='setAside')
    origins = dict(chopping=roles['pivot'], collect=roles['collect'], setAside=roles['unload'])
    poses = {role: relocate(node, origins[group[role]], station['contacts'][group[role]]) for role,node in roles.items()}
    # Root dispatch position should be the actual block, not the native prefab's offset.
    poses['job'].set('Pos', station['contacts']['chopping']['Pos'])
    guid = identity(key+'/job')
    existing = [e for e in mission if e.get('EntityGuid') == guid]
    if existing:
        job = unique(existing, 'shared chopping job')
        existing_roles, _ = graph(job, {e.get('EntityId'): e for e in mission})
        for role in roles:
            node = existing_roles[role]
            if role in ('basket', 'axe', 'log'):
                original = station[role]
                guids = {native_guid(int(original.get('EntityGuid'), 16))}
                guids.update(native_guid(int(station['entities'][l.get('TargetId')].get('EntityGuid'), 16))
                    for l in original.findall('EntityLinks/Link') if l.get('Name') == 'SlotLink')
                if node.get('EntityGuid') not in guids: raise ValueError('Conflicting shared chopping item')
            elif node.get('EntityGuid') != identity(key+'/'+role):
                raise ValueError('Conflicting shared chopping identity')
            if role == 'basket':
                if node.find('Properties').get('guidItemClassId') != contract['reservation']['item_id']:
                    raise ValueError('Conflicting shared chopping basket')
                continue
            expected_props = copy.deepcopy(roles[role].find('Properties'))
            if role in ('axe', 'log'): expected_props.set('bSaveBorrowedItem', '1')
            if (node.get('Pos') != poses[role].get('Pos') or node.get('Rotate', '1,0,0,0') != poses[role].get('Rotate', '1,0,0,0')
                    or signature(node.find('Properties')) != signature(expected_props)):
                raise ValueError('Conflicting shared chopping workplace')
        terminal = copy.deepcopy(contract['terminal']); terminal.set('EntityGuid', str(guid_value(guid)))
        terminal.attrib.pop('Position', None)
        actual = unique((r for r in rows if r.get('EntityGuid') == terminal.get('EntityGuid')), 'shared chopping terminal')
        if signature(actual) != signature(terminal): raise ValueError('Conflicting shared chopping scheduler')
        return job, [], []
    required = {e.find('Properties').get('guidItemClassId', '').lower() for e in roles.values() if e.get('EntityClass') == 'ItemSlot'}
    if not required.issubset(registered): raise ValueError('Missing native chopping item definitions')
    reserved = {identity(key+'/'+r) for r in roles if r not in ('basket','axe','log')}
    if any(e.get('EntityGuid') in reserved for e in mission): raise ValueError('Partial or conflicting chopping graph')
    nodes = {}; reports = []
    nodes['basket'], report = register_item(mission, station['basket'], station['entities'], contract['reservation'], registered)
    reports.append(report)
    for role in ('axe', 'log'):
        nodes[role], report = promote(mission, station[role], station, poses[role], registered); reports.append(report)
    next_id = max(int(e.get('EntityId', '0')) for e in mission)+1
    for role, native in poses.items():
        if role in nodes: continue
        prefix = 'gm_job_item_chopping_' if native.get('EntityClass') == 'ItemSlot' else 'gm_schedule_chopping_'
        node = E.SubElement(mission, 'Entity', Name=prefix+station['identity']+'_'+role, EntityClass=native.get('EntityClass'),
            EntityId=str(next_id), EntityGuid=identity(key+'/'+role), Pos=native.get('Pos'), Rotate=native.get('Rotate', '1,0,0,0'))
        next_id += 1; node.append(copy.deepcopy(native.find('Properties'))); nodes[role] = node
    remap = {e.get('EntityId'): nodes[role] for role,e in roles.items()}; waiting = []
    for role, native in roles.items():
        for link in native.findall('EntityLinks/Link'):
            node = nodes[role]; target = remap[link.get('TargetId')]
            edges = node.find('EntityLinks')
            if edges is None: edges = E.SubElement(node, 'EntityLinks')
            E.SubElement(edges, 'Link', Name=link.get('Name'), TargetId=target.get('EntityId'), TargetGuid=target.get('EntityGuid'))
            waiting.append((node.get('EntityGuid'), target.get('EntityGuid'), link.get('Name')))
    terminal = copy.deepcopy(contract['terminal']); terminal.set('EntityGuid', str(guid_value(guid)))
    terminal.attrib.pop('Position', None); rows.append(terminal)
    return nodes['job'], waiting, reports


def bind(mission, scheduler, person, entry, clock, station, contract, registered):
    actor, job, hub, incoming = owned_pool(mission, scheduler, person, entry, clock)
    rows = scheduler.find('Schedulers')
    point, waiting, items = workstation(mission, rows, station, contract, registered)
    if job.get('EntityClass') == 'SmartObjectHolder':
        job.set('EntityClass', 'SchedulerHub'); job.remove(job.find('Properties')); E.SubElement(job, 'Properties', bSaved_by_game='0')
        hub.set('Position', job.get('Pos')); E.SubElement(hub, 'Links')
        for link in incoming: link.find('Parameters').attrib.pop('BehaviorName')
        for link in actor.findall('EntityLinks/Link'):
            if link.get('TargetGuid') == job.get('EntityGuid') and link.get('Name') == '_,use': link.set('Name', '_')
    outgoing = hub.find('Links'); existing = {signature(l) for l in outgoing}; added = False
    # The actor edge owns the sleep cutoff. Keep the authored leaf windows so
    # a repeat upgrade does not add overlapping copies of the same workplace.
    choice_incoming = []
    for start, end in sorted(clock):
        link = copy.deepcopy(incoming[0])
        link.find('Parameters').set('TimeOfDayStart', str(start))
        link.find('Parameters').set('TimeOfDayEnd', str(end))
        choice_incoming.append(link)
    for link in choices([point], contract['activity'], choice_incoming):
        if signature(link) not in existing: outgoing.append(link); added = True
    edges = job.find('EntityLinks')
    if edges is None: edges = E.SubElement(job, 'EntityLinks')
    if not any(l.get('TargetGuid') == point.get('EntityGuid') for l in edges):
        E.SubElement(edges, 'Link', Name='_,use', TargetId=point.get('EntityId'), TargetGuid=point.get('EntityGuid'))
    waiting.append((job.get('EntityGuid'), point.get('EntityGuid'), '_,use'))
    return job, point, waiting, items, added


def upgrade(files, schedules, archive, target, registered):
    mission = E.fromstring(files['objects_mission0.xml']); scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
    waiting = E.fromstring(files['waitinglinks.xml']); links = []; reports = []; contract = None
    source = Path(archive.filename).parents[3]
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        blobs = reader(source, dict(home=('Scripts.pak', 'Libs/AI/final/sa_home.xml'),
            warehouse=('Scripts.pak', 'Libs/AI/final/sa_warehouse.xml'), helpers=('GameData.pak', 'Libs/SmartObjects.xml')))
        program = E.fromstring(blobs['home']['data']); warehouse = E.fromstring(blobs['warehouse']['data']); helpers = E.fromstring(blobs['helpers']['data'])
        for person, entries in schedules.items():
            actor = next((e for e in mission if e.get('Name') == person), None)
            if actor is None or actor.get('EntityClass') != 'NPC': continue
            phases = housework_phases(program.find("BehaviorTree[@name='housework']"), actor.get('EntityClass'))
            if 'choppingWood' not in phases: continue
            seen = set()
            for entry in entries:
                if not supports(entry) or entry['arrival']['EntityId'] in seen: continue
                seen.add(entry['arrival']['EntityId'])
                if not any(e.get('Name') == 'gm_schedule_'+person+'_'+entry['arrival']['EntityId'] for e in mission): continue
                clock = {(e['start_minute'], e['end_minute']) for e in entries if supports(e) and e['arrival']['EntityId'] == entry['arrival']['EntityId']}
                owned_pool(mission, scheduler, person, entry, clock)
                if not source_contract(entry, tables, warehouse): continue
                station = resolve(entry, archive, helpers)
                if station is None: continue
                if contract is None: contract = native_contract(target)
                job, point, added_links, items, changed = bind(mission, scheduler, person, entry, clock, station, contract, registered)
                links.extend(added_links)
                for record in waiting.findall('.//WaitingLink'):
                    if record.get('TargetId') == job.get('EntityGuid'):
                        for definition in record:
                            if definition.text == '_,use': definition.text = '_'
                if changed:
                    reports.append(dict(person=person, job='native_wood_chopping', extension_only=True, source_behavior=entry['behavior'],
                        source_area=entry['area'], workplace=point.attrib, contacts=station['contacts'], items=items,
                        intervals=sorted(clock), runtime_verified=False, pending=['source housework phase ordering',
                        'runtime navigation, tool placement and interruption verification']))
    return dict(files, **{'objects_mission0.xml': xml(mission), 'tables/ai/scheduler.xml': xml(scheduler),
        'waitinglinks.xml': append_links(xml(waiting), links, allow_untagged=True)}), reports
