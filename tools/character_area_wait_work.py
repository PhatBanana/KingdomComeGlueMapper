"""Convert KCD1 "go to the smart area, then wait until the daycycle changes" work.

The source work tree only waits: a LODGuardian whose branches are both
``While $t_timeChanged == false -> Wait``. Movement is not in that tree; it is
the daycycle wrapper (sa_city.xml goToSmartArea) that walks the person to the
area unless the area's ``<tag>_data`` behaviour clears moveToArea. Both halves
are read from the source, so the generated program repeats the source Move and
Wait parameters instead of assuming them.

Selection is by tree identity and structure, never by person, town or position.
"""
import hashlib
import json
import uuid
import xml.etree.ElementTree as E

from campaign_bindings import parse_link_labels
from character_person import resolve_link_targets, unique, world_entity
from character_station_work import unquote
from upgrade_map import read, xml

# One row per KCD1 tree identity sharing this program.
SOURCES = {('final/emptywork.xml', 'Wait')}
ACTIVITY = 'use'
WRAPPER = ('final/sa_city.xml', 'goToSmartArea')
MOVE = ('final/moveutils.xml', 'distanceMove')
TYPES = 'Libs/AI/typedefinitions.xml'


def identity(entry):
    behavior = entry['behavior']
    return behavior['tree_file'].replace('\\', '/').lower(), behavior['tree_name']


def supports(entry):
    return identity(entry) in SOURCES and entry.get('target_kind', 'smart_area') == 'smart_area'


def attributes(node):
    return {k: unquote(v) for k, v in node.attrib.items()}


def recognize_wait(tree):
    """The Wait parameters when the tree is only a time-change wait, else None."""
    root = tree.find('Root')
    if root is None or [c.tag for c in root] != ['Behavior'] or len(root[0]) != 1:
        return None
    guard = root[0][0]
    branches = list(guard) if guard.tag == 'LODGuardian' else [guard]
    if guard.tag == 'LODGuardian':
        if sorted(b.tag for b in branches) != ['Detail', 'LOD'] or any(len(b) != 1 for b in branches):
            return None
        branches = [b[0] for b in branches]
    waits = []
    for loop in branches:
        if loop.tag != 'While' or len(loop) != 1 or loop[0].tag != 'Wait':
            return None
        if ''.join(attributes(loop).get('condition', '').split()) != '$t_timeChanged==false':
            return None
        waits.append(attributes(loop[0]))
    if any(w != waits[0] for w in waits) or waits[0].get('duration', '-1').startswith('-'):
        return None
    return dict(duration=waits[0]['duration'], timeType=waits[0].get('timeType', 'GameTime'),
                doFail=waits[0].get('doFail', 'false'), variation=waits[0].get('variation', ''),
                skipInLOD=waits[0].get('skipInLOD', 'false'))


def member_defaults(types, path):
    """Default member values of a nested source type such as a:b:c."""
    node = types
    for name in path.split(':'):
        node = unique((t for t in node.findall('Type') if t.get('name') == name), 'source type ' + path)
    return {m.get('name'): (m.text or '').strip() for m in node if m.tag.lower() == 'member'}


def recognize_move(wrapper, move, types):
    """Source area-arrival contract: the flag guarding it, its link fallback and Move values."""
    gates = [n for n in wrapper.iter('IfCondition')
             if '$t_behaviorData.moveToArea == true' in attributes(n).get('condition', '')]
    gate = unique(gates, 'source area-arrival gate')
    includes = [attributes(n) for n in gate.iter('IncludeTree')]
    if [(i['File'].lower(), i['Name']) for i in includes] != [MOVE]:
        raise ValueError('Source area arrival no longer uses distanceMove')
    expressions = ' '.join(attributes(n).get('expressions', '') for n in gate.iter('Expression'))
    if ('$t_distanceMove_params.target = $t_behavior.areaId' not in expressions
            or '$t_distanceMove_params.outsideAreaOnly = $t_behaviorData.moveToOutside' not in expressions):
        raise ValueError('Source area arrival target changed')
    fast = [attributes(n) for n in gate.iter('GraphSearch')]
    if len(fast) != 1 or fast[0].get('SubGraph') != 'inside' or fast[0].get('Origin') != 't_behavior.areaId':
        raise ValueError('Source area fast-start point changed')
    moves = [attributes(n) for n in move.iter('Move') if attributes(n).get('destinationSpecification') == 't_destination']
    node = unique(moves, 'source distanceMove walk')
    data = member_defaults(types, 'daycycle:behavior:data')
    params = member_defaults(types, 'distanceMove_params')
    if data.get('moveToArea') != 'true' or data.get('moveToOutside') != 'false':
        raise ValueError('Source area-arrival defaults changed')
    values = {}
    for field, member in (('stopWithinDistance', 'distance'), ('stopDistanceVariation', 'variation'),
                          ('successDistance', 'successDist')):
        if node.get(field) != '$t_distanceMove_params.' + member or member not in params:
            raise ValueError('Source distanceMove parameter changed: ' + field)
        values[field] = params[member]
    if params.get('speed') != '$enum:movementSpeed.walk' or params.get('exact') != 'false':
        raise ValueError('Source distanceMove defaults changed')
    return dict(values, speed='Walk', rayCasteFlee=node.get('rayCasteFlee', 'false'))


def data_overrides(tree):
    """moveToArea/moveToOutside assignments made by an area's ``<tag>_data`` tree."""
    result = {}
    for node in tree.iter('Expression'):
        for part in attributes(node).get('expressions', '').replace('\n', ',').split(','):
            name, _, value = (x.strip() for x in part.partition('='))
            name = name.lstrip('$')
            if name in ('t_behaviorData.moveToArea', 't_behaviorData.moveToOutside') and value in ('true', 'false'):
                result[name.split('.')[1]] = value == 'true'
    return result


def area_data(entry, source, reader, tables=None):
    """The area's ``<tag>_data`` overrides. An area without that tag keeps the defaults."""
    from campaign_dependency_adapters import SourceTables
    tables = tables or SourceTables(source, reader)
    template = entry['binding']['sa_smart_area_id']
    wanted = entry['behavior']['sa_behaviour_tag_name'] + '_data'
    tags = {r['sa_behaviour_tag_id']: r for r in tables.get('ai/sa_behaviour_tag')['rows']}
    bound = [tags[b['sa_behaviour_tag_id']] for b in tables.get('ai/sa_smart_area2sa_behaviour_tag')['rows']
             if b['sa_smart_area_id'] == template and tags[b['sa_behaviour_tag_id']]['sa_behaviour_tag_name'] == wanted]
    if not bound:
        return {}
    row = unique(bound, 'source area data behaviour')
    blob = reader(source, {'data': ('Scripts.pak', 'Libs/AI/' + row['tree_file'])})['data']['data']
    tree = unique((t for t in E.fromstring(blob).findall('BehaviorTree') if t.get('name') == row['tree_name']),
                  'source area data tree')
    return data_overrides(tree)


def arrival_point(entry, archive, overrides):
    """The authored point the source walk ends at: 'outside' when requested and present, else 'inside'."""
    def tagged(tag):
        return [l for l in entry['target_links'] if l.get('Name')
                and any(t['tag'] == tag for t in parse_link_labels(l['Name']))]
    links = (tagged('outside') if overrides.get('moveToOutside') else []) or tagged('inside')
    if not links:
        raise ValueError('Source area has no authored arrival point')
    # Several authored points are alternatives of one AnyLinkFilter; keep the first in authored order.
    area = E.Element('Entity', entry['area'])
    E.SubElement(E.SubElement(area, 'EntityLinks'), 'Link', links[0])
    entities = resolve_link_targets(archive, area, list(E.fromstring(read(archive, 'objects_mission0.xml'))), {})
    point = unique((e for e in entities if e.get('EntityId') == links[0]['TargetId']), 'source area arrival point')
    if point.get('EntityClass') != 'TagPoint':
        raise ValueError('Source area arrival point must be an authored TagPoint')
    return dict(world_entity(archive, point, entities).attrib)


def source_trees(source, reader, files):
    blobs = reader(source, {k: ('Scripts.pak', v if v.startswith('Libs/') else 'Libs/AI/' + v) for k, v in files.items()})
    return {k: E.fromstring(v['data']) for k, v in blobs.items()}


def tree_named(root, name, label):
    return unique((t for t in root.findall('BehaviorTree') if t.get('name') == name), label)


def resolve(entry, archive, source, reader):
    behavior = entry['behavior']
    roots = source_trees(source, reader, dict(work=behavior['tree_file'], wrapper=WRAPPER[0], move=MOVE[0], types=TYPES))
    wait = recognize_wait(tree_named(roots['work'], behavior['tree_name'], 'source wait tree'))
    if wait is None:
        raise ValueError('Unsupported source area wait routine: ' + behavior['tree_name'])
    move = recognize_move(tree_named(roots['wrapper'], WRAPPER[1], 'source daycycle wrapper'),
                          tree_named(roots['move'], MOVE[1], 'source distance move'), roots['types'])
    overrides = area_data(entry, source, reader)
    if overrides.get('moveToArea') is False:
        # The person then waits wherever the previous activity left them; there is no authored place to bind.
        raise ValueError('Source area wait does not move to its area')
    return dict(entry, arrival=arrival_point(entry, archive, overrides),
                area_wait_work=dict(movement=move, wait=wait))


def resources(contract):
    """(template id, published files) of the generated Move + Wait program for one contract."""
    from campaign_behavior import quote
    name = 'gm_area_wait_' + hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()[:16]
    template = str(uuid.uuid5(uuid.NAMESPACE_URL, 'kingdomcomegluemapper/' + name))
    table = E.Element('database', name='barbora')
    obj = E.SubElement(E.SubElement(table, 'SmartEntitys', version='1'), 'SmartEntityTemplate',
                       DatabaseId=template, Name=name, UpdatePriority='false')
    bt = E.SubElement(E.SubElement(obj, 'BehaviorTemplates'), 'SmartBehaviorTemplate',
                      Name='use', InitialState='Enabled', MaxInstances='1')
    E.SubElement(bt, 'TreeLocation', FileName='gluemapper/' + name + '.xml', TreeName='use')
    trees = E.Element('BehaviorTrees')
    tree = E.SubElement(trees, 'BehaviorTree', name='use', is_function='0')
    E.SubElement(tree, 'Variables')
    root = E.SubElement(tree, 'Root', OneTimeOnly='false', FailState='Recoverable', saveVersion='2')
    seq = E.SubElement(E.SubElement(root, 'Behavior', canSkip='1'), 'Sequence')
    movement = contract['movement']
    E.SubElement(seq, 'Move', destinationSpecification='$__object.id', destinationSpecification2='',
                 destinationSpecification3='', speed=movement['speed'],
                 stopWithinDistance=movement['stopWithinDistance'],
                 stopDistanceVariation=movement['stopDistanceVariation'], rayCasteFlee=movement['rayCasteFlee'],
                 successDistance=movement['successDistance'], changeNPCState='true', fastForwardIncludesMove='false',
                 additionalParams='', pathFindingParams='', staminaPolicy='', pathInfo='',
                 AnimationToPlay='', AnimationContext='')
    E.SubElement(seq, 'WaitAction')
    waiting = dict(contract['wait'])
    waiting['duration'] = quote(waiting['duration'])
    E.SubElement(seq, 'Wait', waiting)
    return template, {'Libs/Tables/ai/smartEntity/SmartEntity__' + name + '.xml': xml(table),
                      'AI/gluemapper/' + name + '.xml': xml(trees)}


def entry_resources(entry):
    """Registry publishing hook: the program this resolved entry's holder runs."""
    return resources(entry['area_wait_work'])


def bind(mission, scheduler, person, entry, target):
    from character_schedule_world import ARRIVAL_TEMPLATE
    template, _ = resources(entry['area_wait_work'])
    job = unique((e for e in mission if e.get('Name') == 'gm_schedule_' + person + '_' + entry['arrival']['EntityId']),
                 'area-wait arrival')
    props = job.find('Properties')
    if props is None or props.get('guidSmartObjectType') not in (ARRIVAL_TEMPLATE, template):
        raise ValueError('Area wait requires an importer-owned arrival')
    props.set('guidSmartObjectType', template)
    return job, [], dict(person=person, job='source_area_wait', source_behavior=dict(entry['behavior']),
                         source_area=dict(entry['area']), source_destination=entry['arrival'],
                         program=entry['area_wait_work'], interval=[entry['start_minute'], entry['end_minute']],
                         pending=[], runtime_verified=False)
