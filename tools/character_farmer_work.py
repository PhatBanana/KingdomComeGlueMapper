"""Source-linked field hoeing using KCD2's native tool and movement lifetime.

Authored field rows become exclusive native resources. Native scheduling owns
row selection and tool lifetimes; source rain-shelter behavior remains pending.
"""
import copy
import hashlib
import math
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from campaign_bindings import parse_link_labels
from campaign_entity_links import guid_value, native_guid
from character_job_items import reservation_contract, register_item, bind_reservation
from character_person import unique, resolve_link_targets, world_entity
from character_station_work import unquote
from upgrade_map import read

SOURCE = ('final/sa_farm.xml', 'Farmer')
TABLE = 'Libs/Tables/ai/smartEntity/SmartEntity__so_field.xml'


def supports(entry):
    b = entry['behavior']
    return (b['tree_file'].replace('\\', '/').lower(), b['tree_name']) == SOURCE


def source_contract(blob):
    trees = E.fromstring(blob)
    farmer = trees.find("BehaviorTree[@name='Farmer']/Root")
    main = trees.find("BehaviorTree[@name='Farmer_main']/Root")
    if farmer is None or main is None:
        raise ValueError('Missing source farmer program')
    home = [n for n in farmer.iter('GraphSearch') if unquote(n.get('SubGraph', '')) == 'Home']
    if len(home) != 1 or unquote(home[0].get('depth', '')) != '1':
        raise ValueError('Unsupported farmer home query')
    slots = list(farmer.iter('SlotClassFilter'))
    if len(slots) != 1:
        raise ValueError('Unsupported farmer tool selection')
    for label in ('rowStart', 'rowEnd', 'fieldEnd'):
        searches = [n for n in main.iter('GraphSearch') if any(
            unquote(f.get('tag', '')) == label for f in n.findall('LinkTagFilter'))]
        if (len(searches) != 1 or unquote(searches[0].get('Origin', '')) != '__area.id'
                or unquote(searches[0].get('depth', '')) != '1'):
            raise ValueError('Unsupported farmer row selection: ' + label)
    return unquote(slots[0].get('ClassId', '')).lower()


def row_rotation(first, second):
    """Face the native +Y movement axis down the authored row."""
    a, b = [tuple(map(float, p.split(','))) for p in (first, second)]
    if any(not math.isfinite(v) for v in (*a, *b)) or math.dist(a[:2], b[:2]) < .5:
        raise ValueError('Degenerate farmer row')
    yaw = math.atan2(b[1]-a[1], b[0]-a[0]) - math.pi/2
    return ','.join(format(v, '.10g') for v in (math.cos(yaw/2), 0, 0, math.sin(yaw/2)))


def source_row_count(program, definitions):
    root = E.fromstring(program)
    variable = unique(root.findall("BehaviorTree[@name='Farmer_main']/Variables/Variable[@name='fieldProperties']"), 'field geometry variable')
    if variable.get('type') != 'fieldProperties' or variable.get('values', '').strip():
        raise ValueError('Unsupported field geometry override')
    count = unique(E.fromstring(definitions).findall(".//Type[@name='fieldProperties']/Member[@name='numberOfRows']"), 'source row count')
    value = (count.text or '').strip()
    if count.get('type') != 'int' or not value.isdecimal() or not 1 <= int(value) <= 128:
        raise ValueError('Invalid authored field row count')
    expressions = '\n'.join(unquote(n.get('expressions', '')) for n in root.findall("BehaviorTree[@name='Farmer_main']/Root//Expression"))
    if any('$nextRowStep.'+axis+' /= $rowCountFloat' not in expressions for axis in 'xyz'):
        raise ValueError('Unsupported source field row spacing')
    return int(value)


def field_rows(points, count):
    """Preserve KCD1's division by count (not count minus one), including Z."""
    if type(count) is not int or not 1 <= count <= 128:
        raise ValueError('Invalid authored field row count')
    start, end, last = [tuple(map(float, points[k]['Pos'].split(','))) for k in ('rowStart', 'rowEnd', 'fieldEnd')]
    if any(len(p) != 3 for p in (start, end, last)) or not all(math.isfinite(v) for p in (start,end,last) for v in p):
        raise ValueError('Invalid field geometry')
    row_rotation(points['rowStart']['Pos'], points['rowEnd']['Pos'])
    if count > 1 and abs((end[0]-start[0])*(last[1]-start[1])-(end[1]-start[1])*(last[0]-start[0])) < .25:
        raise ValueError('Field rows overlap')
    vec = lambda values: ','.join(format(v, '.10g') for v in values)
    return [(vec(a+(c-a)*i/count for a,c in zip(start,last)),
             vec(b+(c-a)*i/count for a,b,c in zip(start,end,last))) for i in range(count)]


def resolve(entry, archive, person, source, reader):
    if person is None or reader is None:
        raise ValueError('Farming requires source person and behavior evidence')
    assets = reader(source, {'farm': ('Scripts.pak', 'Libs/AI/'+SOURCE[0]),
                             'types': ('Scripts.pak', 'Libs/AI/TypeDefinitions.xml')})
    item = source_contract(assets['farm']['data'])
    row_count = source_row_count(assets['farm']['data'], assets['types']['data'])
    homes = [E.fromstring(l['source_xml']) for l in person['ai']['links']
        if (l['label'] or '').strip() and any(t['tag'].lower() == 'home'
            for t in parse_link_labels(l['label']))]
    home = unique(homes, 'farmer home')
    area = E.Element('Entity', entry['area'])
    links = E.SubElement(area, 'EntityLinks')
    for link in entry['target_links']:
        E.SubElement(links, 'Link', link)
    entities = list(E.fromstring(read(archive, 'objects_mission0.xml')))
    entities = resolve_link_targets(archive, area, entities, {})
    entities = resolve_link_targets(archive, home, entities, {})
    by_id = {e.get('EntityId'): e for e in entities}
    points = {}
    for label in ('rowStart', 'rowEnd', 'fieldEnd'):
        link = unique((l for l in links if l.get('Name') == label), 'farmer '+label)
        point = by_id[link.get('TargetId')]
        if point.get('EntityClass') != 'TagPoint':
            raise ValueError('Farmer row is not an authored TagPoint')
        points[label] = dict(world_entity(archive, point, entities).attrib)
    slots = {e.get('EntityId'): e for l in home.findall('EntityLinks/Link')
        for e in [by_id[l.get('TargetId')]] if e.get('EntityClass') == 'ItemSlot'
        and e.find('Properties') is not None
        and e.find('Properties').get('guidItemClassId', '').lower() == item}
    if not slots:
        raise ValueError('Farmer home has no authored hoe slot')
    field_rows(points, row_count)
    return dict(entry, arrival=points['rowStart'], farmer_work=dict(points=points,
        row_count=row_count, item_id=item, slots=[E.tostring(e, encoding='unicode') for e in slots.values()]))


def native_contract(target):
    with zipfile.ZipFile(Path(target)/'Data/Tables.pak') as z:
        template = E.fromstring(read(z, TABLE)).find('.//SmartEntityTemplate')
    behavior = template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='hoeing']")
    if behavior is None or behavior.get('MaxInstances') != '1' or behavior.get('InitialState') != 'Enabled':
        raise ValueError('Native field lost exclusive hoeing activity')
    location = behavior.find('TreeLocation')
    with zipfile.ZipFile(Path(target)/'Data/Scripts.pak') as z:
        root = E.fromstring(read(z, 'AI/'+location.get('FileName').replace('\\', '/'))).find(
            "BehaviorTree[@name='"+location.get('TreeName')+"']/Root")
    if (root is None or root.find(".//HandContentElement[@decisionLabel='farmer_hoe'][@hand='Left']") is None
            or root.find(".//ExactMove[@destinationSpecification=\"$movePoints['first']\"]") is None
            or root.find(".//Move[@destinationSpecification=\"$movePoints['second']\"]") is None
            or root.find(".//EntityContext[@context='actorCondition_forcedHoeing']") is None):
        raise ValueError('Native hoeing movement/hand contract changed')
    with zipfile.ZipFile(Path(target)/'Data/Levels/trosecko/level.pak') as z:
        mission = list(E.fromstring(read(z, 'objects_mission0.xml')))
        rows = E.fromstring(read(z, 'tables/ai/scheduler.xml')).find('Schedulers')
    by_id = {e.get('EntityId'): e for e in mission}
    for job in mission:
        p = job.find('Properties')
        if p is None or p.get('guidSmartObjectType') != template.get('DatabaseId'):
            continue
        identity = str(guid_value(job.get('EntityGuid')))
        leaf = unique((r for r in rows if r.get('EntityGuid') == identity), 'native field leaf')
        if leaf.find('Links') is not None:
            continue
        for link in rows.findall('.//S_ActivityLink'):
            params = link.find('Parameters')
            if link.get('TargetGuid') != identity or params is None:
                continue
            if (link.get('PositioningDelegate') != '0' or any(params.get(k) != v for k, v in
                    dict(BehaviorName='hoeing', BehaviorOverride='false', AllowedGenders='0',
                         ProvidedRole='hoeing', Privileged='false', Priority='0').items())
                    or any(k in params.attrib for k in ('RequiredRole', 'RequiredContext', 'LinkTag'))):
                continue
            contract = unique(reservation_contract(job, by_id), 'native hoe reservation')
            if contract['behavior'] != 'hoeing' or contract['decision'] != 'farmer_hoe':
                raise ValueError('Unexpected native hoe reservation')
            if leaf.find(".//EffectSoil[@Role='hoeing'][@SoilRate='5.000000']") is None:
                raise ValueError('Native field soil effect changed')
            return copy.deepcopy(p), copy.deepcopy(link), copy.deepcopy(leaf), contract
    raise ValueError('Missing native field scheduler contract')


def bind(mission, scheduler, person, entry, archive, target, registered):
    from character_schedule_world import ARRIVAL_TEMPLATE
    props, activity, terminal, contract = native_contract(target)
    work = entry['farmer_work']
    if not work.get('slots'):
        raise ValueError('Farmer work has no source hoe slots')
    if contract['item_id'] != work['item_id']:
        raise ValueError('Source/native farmer tools differ')
    actor = unique((e for e in mission if e.get('Name') == person), 'farmer actor')
    job = unique((e for e in mission if e.get('Name') ==
        'gm_schedule_'+person+'_'+entry['arrival']['EntityId']), 'farmer arrival')
    rows = scheduler.find('Schedulers')
    job_id = str(guid_value(job.get('EntityGuid')))
    hub = unique((r for r in rows if r.get('EntityGuid') == job_id), 'farmer arrival hub')
    incoming = [(r, l) for r in rows for l in r.findall('Links/S_ActivityLink') if l.get('TargetGuid') == job_id]
    expected = native_guid(int.from_bytes(hashlib.sha256(('schedule-arrival/'+actor.get('EntityGuid')+'/'+entry['arrival']['EntityGuid']).encode()).digest()[:8], 'little'))
    if (job.get('EntityGuid') != expected or job.get('EntityClass') != 'SmartObjectHolder'
            or job.find('Properties') is None or job.find('Properties').get('guidSmartObjectType') != ARRIVAL_TEMPLATE
            or len(hub) or job.findall('EntityLinks/Link') or not incoming
            or any(r.get('EntityGuid') != str(guid_value(actor.get('EntityGuid')))
                or l.find('Parameters').get('BehaviorName') != 'use' for r, l in incoming)):
        raise ValueError('Cannot replace non-owned farmer arrival')
    waiting = []
    def connect(a, b, label):
        ls = a.find('EntityLinks')
        if ls is None: ls = E.SubElement(a, 'EntityLinks')
        if not any(l.get('Name') == label and l.get('TargetGuid') == b.get('EntityGuid') for l in ls):
            E.SubElement(ls, 'Link', Name=label, TargetId=b.get('EntityId'), TargetGuid=b.get('EntityGuid'))
        waiting.append((a.get('EntityGuid'), b.get('EntityGuid'), label))
    def create(key, cls, position, rotation):
        guid = native_guid(int.from_bytes(hashlib.sha256(('farmer/'+key).encode()).digest()[:8], 'little'))
        existing = [e for e in mission if e.get('EntityGuid') == guid]
        name = 'gm_farmer_'+key.replace('/', '_')
        if existing:
            e = unique(existing, 'shared farmer resource')
            if any(e.get(k) != v for k, v in dict(Name=name, EntityClass=cls, Pos=position, Rotate=rotation).items()):
                raise ValueError('Conflicting shared farmer resource')
            return e, False
        return E.SubElement(mission, 'Entity', Name=name, EntityClass=cls, EntityGuid=guid,
            EntityId=str(max(int(e.get('EntityId', '0')) for e in mission)+1), Pos=position, Rotate=rotation), True
    points = work['points']
    geometry = field_rows(points, work['row_count'])
    source = list(E.fromstring(read(archive, 'objects_mission0.xml')))
    tools = []; imported_tools = []
    for text in work['slots']:
        slot = E.fromstring(text)
        if not any(e.get('EntityId') == slot.get('EntityId') for e in source): source.append(slot)
        source = resolve_link_targets(archive, slot, source, {})
        # Resolve source prefab parents before the generic tool-placement helper.
        placed = world_entity(archive, slot, source)
        source = [placed if e.get('EntityId') == slot.get('EntityId') else e for e in source]
        imported, report = register_item(mission, placed, {e.get('EntityId'): e for e in source}, contract, registered)
        tools.append(report)
        imported_tools.append(imported)
    from character_city_benches import signature
    job.set('EntityClass', 'SchedulerHub'); job.remove(job.find('Properties'))
    E.SubElement(job, 'Properties', bSaved_by_game='0'); hub.set('Position', geometry[0][0])
    outgoing = E.SubElement(hub, 'Links')
    for _, link in incoming:
        link.find('Parameters').attrib.pop('BehaviorName')
    fields = []
    for index, (start, end) in enumerate(geometry):
        rotation = row_rotation(start, end)
        key = entry['area']['EntityGuid'].lower()+'/row_'+str(index)
        field, added = create(key, 'SmartObjectHolder', start, rotation)
        if added: field.append(copy.deepcopy(props))
        elif E.tostring(field.find('Properties')) != E.tostring(props):
            raise ValueError('Shared field has different properties')
        for role, position in [('first', start), ('second', end)]:
            point, new = create(key+'/'+role, 'TagPoint', position, rotation)
            if new: E.SubElement(point, 'Properties', bSaved_by_game='0')
            connect(field, point, "hoeingPoint['"+role+"']")
        for imported in imported_tools:
            waiting.extend(bind_reservation(mission, field, imported, contract))
        connect(field, field, '+Soil[hoeing,5]')
        leaf_id = str(guid_value(field.get('EntityGuid')))
        leaf = copy.deepcopy(terminal); leaf.set('EntityGuid', leaf_id); leaf.attrib.pop('Position', None)
        existing = [r for r in rows if r.get('EntityGuid') == leaf_id]
        if existing and (len(existing) != 1 or signature(existing[0]) != signature(leaf)):
            raise ValueError('Conflicting shared field scheduler')
        if not existing: rows.append(leaf)
        use = copy.deepcopy(activity); use.set('TargetGuid', leaf_id)
        # Clock stays on the actor -> pool edge. The shared resource is always
        # available, so one worker's schedule cannot shut out another worker.
        use.find('Parameters').set('TimeOfDayStart', '0')
        use.find('Parameters').set('TimeOfDayEnd', '1440')
        if not any(signature(x) == signature(use) for x in outgoing): outgoing.append(use)
        connect(job, field, '_,hoeing')
        fields.append(dict(name=field.get('Name'), start=start, end=end))
    for link in actor.findall('EntityLinks/Link'):
        if link.get('TargetGuid') == job.get('EntityGuid') and link.get('Name') == '_,use': link.set('Name', '_')
    return job, waiting, dict(person=person, job='native_farmer_hoeing', source_behavior=entry['behavior'],
        fields=fields, points=points, tools=tools,
        row_selection='native exclusive resources over source row geometry',
        pending=['source sequential row order and alternating direction', 'source rain-shelter selection'], runtime_verified=False)
