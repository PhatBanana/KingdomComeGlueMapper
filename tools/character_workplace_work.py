"""Convert KCD1 ``commonWorkplace`` professions to native KCD2 work stations.

Eleven KCD1 professions are a ``<X>_setParams`` Expression followed by
``final/sa_templates.xml:commonWorkplace``. That template collects every
entity linked from the smart area (depth 1, no parent/inventory edges) whose
category is in ``useCategories`` and calls each one's own ``use`` behaviour in
turn, with occasional breaks. The profession is therefore nothing but its
parameter record and the smart objects the level designer linked.

Each source work object whose ``use`` program is the plain
``so_templates:objectNewHelpers`` In/Loop/Out animation becomes one shared
native KCD2 station running the shipped program that plays the *same* body
fragments. The source arrival becomes a transparent scheduler hub choosing
among those stations. Nothing is generated: there is no ``resources()``.

Parameters are parsed from the source Expression at resolve time. The only
hand-written data are SOURCE_TREES (which trees to look at; resolve proves the
structure) and CATEGORY_PROGRAMS (KCD1 category -> native template/behaviour;
bind proves the native program plays the source animation).
"""
import copy
import functools
from pathlib import Path
import re
import xml.etree.ElementTree as E
import zipfile

from campaign_entity_links import guid_value
from character_person import resolve_link_targets, source_entities, unique, world_entity
from character_work_pool import identity
from upgrade_map import read

TEMPLATE_FILE = 'final/sa_templates.xml'
TEMPLATE_TREE = 'commonWorkplace'
OBJECT_TEMPLATE = ('final/so_templates.xml', 'objectNewHelpers')

# Identity index only: resolve() rejects any of these that stops being a
# commonWorkplace wrapper, and reads its parameters from the source.
SOURCE_TREES = (
    ('final/sa_administrator.xml', 'Administrator'),
    ('final/sa_architect.xml', 'architect'),
    ('final/sa_armorsmith.xml', 'armorsmith'),
    ('final/sa_bailiff.xml', 'bailiff'),
    ('final/sa_carpenter.xml', 'carpenter'),
    ('final/sa_lumbercamp.xml', 'lumberjack'),
    ('final/sa_scribe.xml', 'scribe'),
    ('final/sa_shoemaker.xml', 'shoemaker'),
    ('final/sa_stonemason.xml', 'stonemason'),
    ('final/sa_tailory.xml', 'tailor'),
    ('final/sa_tannery.xml', 'tanner'),
)

# KCD1 entity category -> shipped KCD2 smart entity and behaviour. A row is
# only honoured when the native unstance uses the source In/Loop/Out fragments.
CATEGORY_PROGRAMS = {
    'tanner_tub': dict(template='so_leatherTanningTub', behavior='stirLeather'),
    'tanner_log': dict(template='so_leatherScrapingLog', behavior='scrapeLeather'),
    'Carpentry': dict(template='so_carpenter', behavior='use_debarkingWood'),
    'Stonemason': dict(template='so_chiselingStone', behavior='use_chiseling'),
    'lumberjack_sawingBeam': dict(template='so_sawing', behavior='use_sawing'),
    'shoemaker_bootTree': dict(template='so_shoeMaking', behavior='use_hammeringShoe'),
    'tailor_measuring': dict(template='so_tailorTable', behavior='use_tailorMeasure'),
}

SOURCE_TABLES = dict(
    objects=('Tables.pak', 'Libs/Tables/ai/so_smart_object.xml'),
    object_tags=('Tables.pak', 'Libs/Tables/ai/so_smart_object2so_behaviour_tag.xml'),
    tags=('Tables.pak', 'Libs/Tables/ai/so_behaviour_tag.xml'),
    helpers=('GameData.pak', 'Libs/SmartObjects.xml'))

PRUNED = {'parent', 'inventory'}


def unquote(value):
    value = value or ''
    return value[1:-1] if len(value) > 1 and value[0] == value[-1] and value[0] in '"\'' else value


def identity_of(behavior):
    return behavior['tree_file'].replace('\\', '/').lower(), behavior['tree_name']


def supports(entry):
    return identity_of(entry['behavior']) in SOURCE_TREES


def assignments(expression, record):
    """``$record.field = value`` pairs of a KCD1 Expression node.

    Retail data separates assignments by comma *or* by a bare newline (bailiff)
    and may end with a comma (architect), so this is not a strict parser.
    """
    result = {}
    pattern = re.compile(r'\$' + re.escape(record) + r"\.([\w.]+)\s*=\s*('[^']*'|[^,\r\n]*)")
    for field, value in pattern.findall(expression or ''):
        result[field] = unquote(value.strip())
    return result


def includes(node):
    return [(unquote(i.get('File')).replace('\\', '/').lower(), unquote(i.get('Name')))
            for i in ([] if node is None else node.iter('IncludeTree'))]


def wrapper_params(blob, file, name):
    """Prove ``name`` is a commonWorkplace wrapper and read its parameters."""
    trees = {t.get('name'): t for t in E.fromstring(blob).findall('BehaviorTree')}
    root = trees[name].find('Root') if name in trees else None
    if root is None:
        raise ValueError('Missing source workplace tree: ' + name)
    setup, body = includes(root.find('OnInit')), includes(root.find('Behavior'))
    if (body != [(TEMPLATE_FILE, TEMPLATE_TREE)] or len(setup) != 1 or setup[0][0] != file
            or root.find('Behavior')[0].tag != 'IncludeTree' or setup[0][1] not in trees):
        raise ValueError('Source tree is not a commonWorkplace wrapper: ' + name)
    raw = {}
    for expression in trees[setup[0][1]].iter('Expression'):
        raw.update(assignments(expression.get('expressions'), 't_workplace_params'))
    categories = lambda key: [c for c in raw.get(key, '').split(',') if c]
    if not categories('useCategories'):
        raise ValueError('Source workplace declares no use categories: ' + name)
    def number(key):
        try:
            return float(raw[key]) if key in raw else None
        except ValueError:
            raise ValueError('Unreadable source workplace parameter ' + key) from None
    return dict(useCategories=categories('useCategories'), cleanCategories=categories('cleanCategories'),
                breakChance=number('breakChance'), breakDuration=raw.get('breakDuration'),
                breakVariation=raw.get('breakVariation'))


def template_contract(blob):
    """The parts of commonWorkplace this adapter relies on; fail when they change."""
    root = E.fromstring(blob).find("BehaviorTree[@name='" + TEMPLATE_TREE + "']/Root")
    search = None if root is None else root.find('OnInit//GraphSearch')
    attrs = {} if search is None else {k: unquote(v) for k, v in search.attrib.items()}
    filters = [] if search is None else [{k: unquote(v) for k, v in f.attrib.items()} for f in search]
    expected = dict(Origin='__area.id', depth='1', EdgePruning='parent,inventory', includeOrigin='false')
    if (search is None or any(attrs.get(k) != v for k, v in expected.items())
            or [f.tag for f in search] != ['CategoryFilter', 'Nodalyzer']
            or filters[0].get('categories') != '$t_workplace_params.useCategories'
            or filters[0].get('Source') != 'Child' or filters[1].get('Quantifiers') != 'ForAll'):
        raise ValueError('Source commonWorkplace selection contract changed')
    calls = [{k: unquote(v) for k, v in c.attrib.items()} for c in root.find('Behavior').iter('CallBehavior')]
    if not any(c.get('Target') == 'workspots_value' and c.get('BehaviorName') == 'use' for c in calls):
        raise ValueError('Source commonWorkplace no longer calls each work object')
    breaks = []
    for reserve in root.find('Behavior').iter('ReserveBehavior'):
        for f in reserve.iter('CategoryFilter'):
            breaks = [c for c in unquote(f.get('categories')).split(',') if c]
    return dict(break_categories=breaks)


@functools.lru_cache(maxsize=4)
def _behaviours(objects, object_tags, tags):
    """KCD1 smart-object template id -> (name, {behaviour name: (file, tree)})."""
    names = {r.get('so_smart_object_id', '').lower(): r.get('so_smart_object_name')
             for r in E.fromstring(objects).iter('row')}
    trees = {r.get('so_behaviour_tag_id'): (r.get('so_behaviour_tag_name'), r.get('tree_file'), r.get('tree_name'))
             for r in E.fromstring(tags).iter('row')}
    result = {key: (name, {}) for key, name in names.items()}
    for row in E.fromstring(object_tags).iter('row'):
        owner, tag = result.get(row.get('so_smart_object_id', '').lower()), trees.get(row.get('so_behaviour_tag_id'))
        if owner is not None and tag is not None:
            owner[1][tag[0]] = (tag[1].replace('\\', '/'), tag[2])
    return result


@functools.lru_cache(maxsize=4)
def _helpers(blob):
    result = {}
    for helper in E.fromstring(blob).iter('Helper'):
        result.setdefault(helper.get('className'), []).append(dict(helper.attrib))
    return result


def object_contract(blob, file, name):
    """In/Loop/Out record of a plain objectNewHelpers ``use`` tree, else a reason string.

    Trees that first sit on a linked chair, fetch a tool through another
    behaviour, slave a book or run a route are separate programs: report them.
    """
    trees = {t.get('name'): t for t in E.fromstring(blob).findall('BehaviorTree')}
    root = trees[name].find('Root') if name in trees else None
    if root is None:
        return 'missing use tree ' + file + ':' + name
    body = root.find('Behavior')
    if body is None or len(body) != 1 or body[0].tag != 'IncludeTree' or includes(body) != [OBJECT_TEMPLATE]:
        first = None if body is None or not len(body) else body[0]
        detail = '' if first is None else first.tag + (
            ' ' + unquote(first.get('Target', '')) + '.' + unquote(first.get('BehaviorName', ''))
            if first.tag == 'CallBehavior' else '')
        return 'compound use program (' + detail + ')'
    raw = {}
    setup = root.find('OnInit')
    for included_file, included in includes(setup):
        if included_file == file and included in trees:
            for expression in trees[included].iter('Expression'):
                raw.update(assignments(expression.get('expressions'), 't_object_params'))
    for expression in ([] if setup is None else setup.iter('Expression')):
        raw.update(assignments(expression.get('expressions'), 't_object_params'))
    animation = [raw.get(k, '') for k in ('animationIn', 'animationLoop', 'animationOut')]
    if not all(animation):
        return 'use program without an In/Loop/Out animation'
    if raw.get('helperName') or raw.get('slavedObjectCategory') or raw.get('dontMove') == 'true':
        return 'use program bound to a named helper, slaved object or fixed pose'
    wait = None if 'use_default' not in trees else trees['use_default'].find('Root/Behavior/Wait')
    return dict(animation=animation,
                tags=[raw.get(k, '') for k in ('animationInTags', 'animationLoopTags', 'animationOutTags')],
                tool_items=sorted(v.lower() for k, v in raw.items()
                                  if k in ('slot_right_itemClassId', 'slot_left_itemClassId') and v),
                created_items=sorted(v.lower() for k, v in raw.items()
                                     if k in ('item_right_guid', 'item_left_guid') and v),
                default_wait=None if wait is None else [unquote(wait.get('duration')), unquote(wait.get('variation'))])


def categories(entity):
    props = entity.find('Properties')
    return [] if props is None else [c for c in props.get('sWH_AI_EntityCategory', '').split(',') if c]


def pruned(link):
    return bool(PRUNED.intersection((link.get('Name') or '').split(',')))


def resolve(entry, archive, source, reader):
    if source is None or reader is None:
        raise ValueError('Workplace work requires its effective source behavior')
    from character_fence_work import placement
    file, name = identity_of(entry['behavior'])
    blobs = reader(source, dict(SOURCE_TABLES, wrapper=('Scripts.pak', 'Libs/AI/' + file),
                                template=('Scripts.pak', 'Libs/AI/' + TEMPLATE_FILE)))
    params = wrapper_params(blobs['wrapper']['data'], file, name)
    template = template_contract(blobs['template']['data'])
    behaviours = _behaviours(blobs['objects']['data'], blobs['object_tags']['data'], blobs['tags']['data'])
    helpers = _helpers(blobs['helpers']['data'])
    area = E.Element('Entity', entry['area'])
    edges = E.SubElement(area, 'EntityLinks')
    for link in entry['target_links']:
        if not pruned(link):
            E.SubElement(edges, 'Link', link)
    entities = resolve_link_targets(archive, area, source_entities(archive), {})
    by_id = {e.get('EntityId'): e for e in entities}
    wanted, stations, pending, seen, breaks, programs = set(params['useCategories']), [], [], set(), {}, {}
    for edge in edges:
        entity = by_id[edge.get('TargetId')]
        owned = categories(entity)
        for category in owned:
            if category in template['break_categories']:
                breaks[category] = breaks.get(category, 0) + 1
        matching = [c for c in owned if c in wanted]
        if not matching or entity.get('EntityId') in seen:
            continue
        seen.add(entity.get('EntityId'))
        category = next((c for c in matching if c in CATEGORY_PROGRAMS), matching[0])
        origin = dict(EntityId=entity.get('EntityId'), EntityGuid=entity.get('EntityGuid'), Name=entity.get('Name', ''))
        def skip(reason):
            pending.append(dict(category=category, source=origin, reason=reason))
        props = entity.find('Properties')
        if entity.get('EntityClass') != 'SmartObjectHolder':
            skip('work object is a ' + str(entity.get('EntityClass'))); continue
        kind, tagged = behaviours.get(props.get('guidSmartObjectType', '').lower(), (None, {}))
        if 'use' not in tagged:
            skip('work object template has no use behaviour'); continue
        use_file, use_tree = tagged['use']
        if use_file not in programs:
            programs[use_file] = reader(source, {'use': ('Scripts.pak', 'Libs/AI/' + use_file)})['use']['data']
        contract = object_contract(programs[use_file], use_file.lower(), use_tree)
        if isinstance(contract, str):
            skip(str(kind) + ': ' + contract); continue
        if category not in CATEGORY_PROGRAMS:
            skip(str(kind) + ': no native program mapped for ' + contract['animation'][1]); continue
        family = props.get('soclasses_SmartObjectHelpers', '')
        # ActionHelperMapper picks the helper that lists the In animation.
        contacts = [h for h in helpers.get(family, []) if "Animation('" + contract['animation'][0] + "'" in h.get('description', '')]
        if len(contacts) != 1:
            skip(str(kind) + ': no single ' + contract['animation'][0] + ' contact helper in ' + repr(family)); continue
        entities = resolve_link_targets(archive, entity, entities, {})
        by_id = {e.get('EntityId'): e for e in entities}
        tools = []
        for link in entity.findall('EntityLinks/Link'):
            slot = by_id[link.get('TargetId')]
            slot_props = slot.find('Properties')
            if pruned(link) or slot.get('EntityClass') != 'ItemSlot' or slot_props is None:
                continue
            placed = world_entity(archive, slot, entities)
            tools.append(dict(EntityId=slot.get('EntityId'), EntityGuid=slot.get('EntityGuid'),
                Pos=placed.get('Pos'), Rotate=placed.get('Rotate', '1,0,0,0'),
                item=slot_props.get('guidItemClassId', '').lower(),
                visuals=[slot.get('EntityId')] + [l.get('TargetId') for l in slot.findall('EntityLinks/Link')
                                                 if l.get('Name') == 'SlotLink']))
        pose = placement(world_entity(archive, entity, entities), E.Element('Helper', contacts[0]))
        stations.append(dict(category=category, source=origin, source_template=kind, source_helper=family,
            pose=dict(EntityId=origin['EntityId'], EntityGuid=origin['EntityGuid'], Pos=pose['Pos'], Rotate=pose['Rotate']),
            animation=contract['animation'], default_wait=contract['default_wait'],
            tool_items=contract['tool_items'], created_items=contract['created_items'],
            tools=tools, program=dict(CATEGORY_PROGRAMS[category])))
    if not stations:
        raise ValueError('Source workplace has no convertible work object' + (
            ': ' + '; '.join(sorted({p['category'] + ' - ' + p['reason'] for p in pending})) if pending
            else ' linked for ' + ','.join(params['useCategories'])))
    inside = [by_id[l.get('TargetId')] for l in edges if l.get('Name') == 'inside']
    if len(inside) == 1 and inside[0].get('EntityClass') == 'TagPoint':
        arrival = dict(world_entity(archive, inside[0], entities).attrib)
    else:
        arrival = dict(stations[0]['pose'])
    return dict(entry, arrival=arrival, workplace_work=dict(source=[file, name], params=params,
        break_spots=breaks, stations=stations, pending=pending))


_NATIVE = {}


def _native_level(target):
    key = str(Path(target).resolve())
    if key not in _NATIVE:
        with zipfile.ZipFile(Path(target)/'Data/Levels/trosecko/level.pak') as z:
            _NATIVE[key] = (list(E.fromstring(read(z, 'objects_mission0.xml')).iter('Entity')),
                            E.fromstring(read(z, 'tables/ai/scheduler.xml')).find('Schedulers'),
                            E.fromstring(read(z, 'smartobjecthelpersetanimations.xml')))
    return _NATIVE[key]


def native_program(target, template, behavior):
    """Shipped station contract: properties, activity edge, leaf row, fragments, tool links."""
    target = Path(target)
    with zipfile.ZipFile(target/'Data/Tables.pak') as z:
        record = E.fromstring(read(z, 'Libs/Tables/ai/smartEntity/SmartEntity__' + template + '.xml')).find('.//SmartEntityTemplate')
        unstances = E.fromstring(read(z, 'Libs/Tables/ai/NPCStateUnstanceDatabase.xml'))
    use = None if record is None else record.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='" + behavior + "']")
    if use is None or use.get('InitialState') != 'Enabled' or use.find('TreeLocation') is None:
        raise ValueError('Missing enabled native work behaviour ' + template + '.' + behavior)
    location = use.find('TreeLocation')
    with zipfile.ZipFile(target/'Data/Scripts.pak') as z:
        names = {n.replace('\\', '/').lower(): n for n in z.namelist()}
        path = names.get('ai/' + location.get('FileName').replace('\\', '/').lower())
        root = None if path is None else E.fromstring(read(z, path)).find(
            "BehaviorTree[@name='" + location.get('TreeName') + "']/Root")
    sequence = None if root is None else root.find('Behavior/Sequence')
    if (sequence is None or [n.tag for n in sequence] != ['UnstanceAction', 'Wait']
            or sequence[0].get('locationObject') != '$__object.id' or sequence[0].get('slaveObject')
            or sequence[1].get('timeType') != 'GameTime'):
        raise ValueError('Native work program is not a plain object unstance: ' + template + '.' + behavior)
    unstance = [u for u in unstances.iter('UnstanceData') if u.get('Name') == sequence[0].get('unstance')]
    if len(unstance) != 1 or unstance[0].get('Stance') or any(
            unstance[0].find(k) is None or unstance[0].find(k).get('Tags') for k in ('In', 'Loop', 'Out')):
        raise ValueError('Native work unstance changed: ' + str(sequence[0].get('unstance')))
    fragments = [unstance[0].find(k).get('Fragment') for k in ('In', 'Loop', 'Out')]
    entities, rows, collections = _native_level(target)
    by_id = {e.get('EntityId'): e for e in entities}
    by_guid = {r.get('EntityGuid'): r for r in rows}
    holders = {str(guid_value(e.get('EntityGuid'))): e for e in entities
               if e.get('EntityClass') == 'SmartObjectHolder' and e.find('Properties') is not None
               and e.find('Properties').get('guidSmartObjectType') == record.get('DatabaseId')}
    for row in rows:
        for link in row.findall('Links/S_ActivityLink'):
            holder, p = holders.get(link.get('TargetGuid')), link.find('Parameters')
            terminal = by_guid.get(link.get('TargetGuid'))
            if (holder is None or p is None or terminal is None or terminal.find('Links') is not None
                    or link.get('PositioningDelegate') != '0' or p.get('BehaviorName') != behavior
                    or p.get('BehaviorOverride') != 'false'
                    or p.get('TimeOfDayStart') != '0' or p.get('TimeOfDayEnd') != '1440'
                    or any(k in p.attrib for k in ('RequiredRole', 'LinkTag', 'RequiredContext', 'BuffTag'))):
                continue
            family = holder.find('Properties').get('soclass_SmartObjectHelpers', '')
            collection = [c for c in collections if c.get('HelperSetName') == family]
            transforms = [t for c in collection for t in c.iter('HelperTransformLocal')]
            if len(collection) != 1 or not transforms or any(
                    t.attrib != dict(Rotation='1,0,0,0', Position='0,0,0') for t in transforms):
                continue
            tools, other = [], []
            for edge in holder.findall('EntityLinks/Link'):
                linked = by_id.get(edge.get('TargetId'))
                if linked is not None and linked.get('EntityClass') == 'ItemSlot' and linked.find('Properties') is not None:
                    tools.append((edge.get('Name'), copy.deepcopy(linked.find('Properties'))))
                else:
                    other.append(edge.get('Name'))
            return dict(database_id=record.get('DatabaseId'), tree=dict(location.attrib), unstance=unstance[0].get('Name'),
                fragments=fragments, wait=unquote(sequence[1].get('duration')), family=family,
                properties=copy.deepcopy(holder.find('Properties')), activity=copy.deepcopy(link),
                terminal=copy.deepcopy(terminal), tools=tools, omitted_links=other)
    raise ValueError('No shipped scheduled instance of ' + template + '.' + behavior)


_PROGRAMS, _BODIES = {}, {}


def cached_program(target, template, behavior):
    key = (str(target), template, behavior)
    if key not in _PROGRAMS:
        try:
            _PROGRAMS[key] = native_program(target, template, behavior)
        except ValueError as error:
            _PROGRAMS[key] = error
    if isinstance(_PROGRAMS[key], ValueError):
        raise ValueError(str(_PROGRAMS[key]))
    return _PROGRAMS[key]


def body_fragments(target):
    """Untagged body fragments per controller ('male'/'female')."""
    key = str(target)
    if key not in _BODIES:
        from campaign_work_animations import fragment_catalog
        variants = fragment_catalog(target)['controller_variants']
        _BODIES[key] = {c: {f for f, tags in v.items() if [] in tags} for c, v in variants.items()}
    return _BODIES[key]


def signature(element):
    return element.tag, tuple(sorted(element.attrib.items())), tuple(signature(c) for c in element)


def bind(mission, scheduler, person, entry, target):
    """Turn the owned arrival into a hub over shared native work stations."""
    work = entry['workplace_work']
    actor = unique((e for e in mission if e.get('Name') == person), 'workplace actor')
    controller = 'female' if actor.get('EntityClass') == 'NPC_Female' else 'male'
    job = unique((e for e in mission if e.get('Name') ==
        'gm_schedule_' + person + '_' + entry['arrival']['EntityId']), 'workplace arrival')
    rows = scheduler.find('Schedulers')
    hub_id = str(guid_value(job.get('EntityGuid')))
    hub = unique((r for r in rows if r.get('EntityGuid') == hub_id), 'workplace scheduler hub')
    incoming = [l for r in rows for l in r.findall('Links/S_ActivityLink') if l.get('TargetGuid') == hub_id]
    if len(hub) or not incoming or any(l.find('Parameters').get('BehaviorName') != 'use' for l in incoming):
        raise ValueError('Workplace work requires an importer-owned arrival activity')
    # Plan and validate every station before touching either document.
    planned, skipped = [], []
    for station in work['stations']:
        try:
            native = cached_program(target, **station['program'])
            if native['fragments'] != station['animation']:
                raise ValueError('native ' + native['unstance'] + ' plays ' + '/'.join(native['fragments'])
                                 + ', source plays ' + '/'.join(station['animation']))
            if any(f not in body_fragments(target).get(controller, ()) for f in native['fragments']):
                raise ValueError('no ' + controller + ' body animation for ' + native['unstance'])
            genders = native['activity'].find('Parameters').get('AllowedGenders', '0')
            if genders not in ('0', '1' if controller == 'male' else '2'):
                raise ValueError('native ' + station['program']['behavior'] + ' excludes ' + controller + ' actors')
        except ValueError as error:
            skipped.append(dict(category=station['category'], source=station['source'], reason=str(error)))
            continue
        guid = identity('work/workplace/' + station['source']['EntityGuid'].lower())
        attrs = dict(Name='gm_schedule_workplace_' + station['source']['EntityGuid'].lower(), EntityGuid=guid,
                     EntityClass='SmartObjectHolder', Pos=station['pose']['Pos'], Rotate=station['pose']['Rotate'])
        existing = [e for e in mission if e.get('EntityGuid') == guid or e.get('Name') == attrs['Name']]
        if existing and (len(existing) != 1 or any(existing[0].get(k) != v for k, v in attrs.items())
                         or existing[0].find('Properties') is None
                         or signature(existing[0].find('Properties')) != signature(native['properties'])):
            raise ValueError('Conflicting native work station: ' + station['source']['EntityGuid'])
        registered = [r for r in rows if r.get('EntityGuid') == str(guid_value(guid))]
        if registered and (len(registered) != 1 or registered[0].tag != 'C_SmartHub'
                           or registered[0].find('Links') is not None):
            raise ValueError('Work station has conflicting scheduler dependencies')
        planned.append((station, native, attrs, existing[0] if existing else None, bool(registered)))
    if not planned:
        raise ValueError('No native work station for ' + '/'.join(work['source']) + ': '
                         + '; '.join(sorted({s['category'] + ' - ' + s['reason'] for s in skipped})))
    next_id = max(int(e.get('EntityId', '0')) for e in mission.iter('Entity')) + 1
    job.set('EntityClass', 'SchedulerHub')
    job.remove(job.find('Properties'))
    E.SubElement(job, 'Properties', bSaved_by_game='0')
    hub.set('Position', job.get('Pos'))
    clock = sorted({(l.find('Parameters').get('TimeOfDayStart'), l.find('Parameters').get('TimeOfDayEnd'))
                    for l in incoming}, key=lambda c: (int(c[0]), int(c[1])))
    for link in incoming:
        link.find('Parameters').attrib.pop('BehaviorName')
    outgoing = E.SubElement(hub, 'Links')
    edges = job.find('EntityLinks')
    if edges is None:
        edges = E.SubElement(job, 'EntityLinks')
    waiting, bound, tool_pending = [], [], []
    for station, native, attrs, holder, registered in planned:
        behavior = station['program']['behavior']
        if holder is None:
            holder = E.SubElement(mission, 'Entity', EntityId=str(next_id), **attrs)
            next_id += 1
            holder.append(copy.deepcopy(native['properties']))
            # The shipped animation events take the tool from the station's
            # linked slot. Only a one-to-one authored slot is carried over.
            if len(native['tools']) == 1 and len(station['tools']) == 1:
                link_name, slot_props = native['tools'][0]
                tool = station['tools'][0]
                slot_guid = identity('work/workplace-tool/' + tool['EntityGuid'].lower())
                slot_name = 'gm_workplace_tool_' + tool['EntityGuid'].lower()
                if any(e.get('EntityGuid') == slot_guid or e.get('Name') == slot_name for e in mission):
                    raise ValueError('Conflicting native work tool: ' + tool['EntityGuid'])
                slot = E.SubElement(mission, 'Entity', Name=slot_name, EntityGuid=slot_guid, EntityId=str(next_id),
                                    EntityClass='ItemSlot', Pos=tool['Pos'], Rotate=tool['Rotate'], CastShadowMinSpec='1')
                next_id += 1
                slot.append(copy.deepcopy(slot_props))
                E.SubElement(E.SubElement(holder, 'EntityLinks'), 'Link', Name=link_name,
                             TargetId=slot.get('EntityId'), TargetGuid=slot_guid)
                waiting.append((attrs['EntityGuid'], slot_guid, link_name))
                for old in [e for e in mission if e.get('Name') in {'glue_item_' + i for i in tool['visuals']}]:
                    mission.remove(old)
            elif native['tools'] or station['tools']:
                tool_pending.append(station['source']['EntityGuid'])
        leaf_id = str(guid_value(attrs['EntityGuid']))
        if not registered:
            leaf = copy.deepcopy(native['terminal'])
            leaf.set('EntityGuid', leaf_id)
            leaf.attrib.pop('Position', None)
            rows.append(leaf)
        for start, end in clock:
            link = copy.deepcopy(native['activity'])
            link.set('TargetGuid', leaf_id)
            link.find('Parameters').set('TimeOfDayStart', start)
            link.find('Parameters').set('TimeOfDayEnd', end)
            outgoing.append(link)
        E.SubElement(edges, 'Link', Name='_,' + behavior, TargetId=holder.get('EntityId'), TargetGuid=attrs['EntityGuid'])
        waiting.append((job.get('EntityGuid'), attrs['EntityGuid'], '_,' + behavior))
        bound.append(dict(category=station['category'], source=station['source'], target_guid=attrs['EntityGuid'],
            name=attrs['Name'], position=attrs['Pos'], native_template=station['program']['template'],
            native_template_id=native['database_id'], native_behavior=behavior, native_unstance=native['unstance'],
            fragments=native['fragments'], native_wait=native['wait'], source_wait=station['default_wait'],
            omitted_native_links=native['omitted_links']))
    params = work['params']
    pending = ['source break at ' + ', '.join(k + ' x' + str(v) for k, v in sorted(work['break_spots'].items()))
               + ' (chance ' + str(params['breakChance']) + ', ' + str(params['breakDuration']) + ' +/- '
               + str(params['breakVariation']) + ')' if work['break_spots'] else
               'source break (no break spot linked; chance ' + str(params['breakChance']) + ')',
               'source MERCHANT/REPAIRMAN meta roles and sing/self-talk contexts while working',
               'source station order (sequential loop) and per-object wait durations',
               'smart-area workBreakChance override']
    if params['cleanCategories']:
        pending.append('end-of-shift cleanup of ' + ','.join(params['cleanCategories']))
    if tool_pending:
        pending.append('tool slots of ' + ', '.join(tool_pending))
    pending.extend(p['category'] + ' work object ' + p['source']['EntityGuid'] + ': ' + p['reason']
                   for p in [*work['pending'], *skipped])
    return job, waiting, dict(person=person, job='native_workplace', source_behavior=dict(entry['behavior']),
        source_area=dict(entry['area']), source_params=params, stations=bound,
        interval=[entry['start_minute'], entry['end_minute']], pending=pending, runtime_verified=False)
