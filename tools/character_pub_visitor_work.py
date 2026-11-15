"""KCD1 pub patrons as native KCD2 seat reservations at the source pub's tables.

One table row per KCD1 tree identity. Every row ends in the same source chain:
pub area -> public ``pubTable`` -> ``Seat`` bench, which is what PubVisitor's
``getBench`` reserves before it starts the ``Customer`` phase. The patron's
arrival becomes a SchedulerHub over the converted ``gm_bench_*`` places of those
benches; KCD2 owns movement, sitting, occupancy and interruption.

Selection is structural (area links, categories, link tags), never a name or a
coordinate. Tankards, orders, meals, dice, rain shelter and closing time are
reported as pending, not imitated.
"""
from collections import namedtuple
import copy
import re
import xml.etree.ElementTree as E

from campaign_entity_links import guid_value
from character_person import resolve_link_targets, unique
from character_station_work import unquote

KEY = 'pub_visitor_work'
ACTIVITY = ''
PUB_FILE = 'final/sa_pub_v3.xml'

# pub: where the pub smart area comes from. 'area' is the linked activity area
# itself; 'link:<tag>' follows that one-hop link tag from the activity area.
# contract: the structural check proving the source tree still means this.
Row = namedtuple('Row', 'tree_file tree_name pub contract pending')

PATRON_PENDING = (
    'tankard, beer orders and drinking (source Customer phase, male patrons)',
    'meal tray orders and eating',
    'dice table opponents and kibitzing',
    'rain shelter for tables without a roof',
    'leaving when the bartender closes the pub',
    'reserved and group (visitInGroup) table preferences',
)

ROWS = (
    Row(PUB_FILE, 'PubVisitor', 'area', 'pub_visitor', PATRON_PENDING),
    Row(PUB_FILE, 'waitTillPubOpens', 'area', 'forwarder', PATRON_PENDING),
    Row('final/sa_pubcomp.xml', 'Visitor', 'link:pub', 'companion',
        PATRON_PENDING + ('hangingOut in the companion area while the pub is unavailable',)),
)
_BY_IDENTITY = {(r.tree_file, r.tree_name): r for r in ROWS}
if len(_BY_IDENTITY) != len(ROWS):
    raise ValueError('Duplicate pub-visitor tree identity')


def identity(entry):
    behavior = entry['behavior']
    return behavior['tree_file'].replace('\\', '/').lower(), behavior['tree_name']


def row_for(entry):
    return _BY_IDENTITY.get(identity(entry))


def supports(entry):
    return row_for(entry) is not None


def _attrs(node):
    return {k: unquote(v) for k, v in node.attrib.items()}


def _root(document, name):
    root = document.find("BehaviorTree[@name='" + name + "']/Root")
    if root is None:
        raise ValueError('Missing source pub tree: ' + name)
    return root


def check_pub_visitor(document):
    """PubVisitor picks public pubTables one hop from the area, then getBench."""
    root = _root(document, 'PubVisitor')
    queries = [s for s in root.iter('GraphSearch')
               if any(unquote(f.get('categories', '')) == 'pubTable' for f in s)]
    query = unique(queries, 'source pub-visitor table query')
    attrs = _attrs(query)
    reserved = query.find('NegationOp//LinkTagFilter')
    sink = query.find('Nodalyzer')
    if (any(attrs.get(k) != v for k, v in dict(Origin='__area.id', depth='1', EdgePruning='parent',
                                               includeOrigin='false').items())
            or attrs.get('AllowedEdges') or attrs.get('SubGraph')
            or [f.tag for f in query] != ['CategoryFilter', 'NegationOp', 'Nodalyzer']
            or reserved is None or unquote(reserved.get('tag', '')) != 'reserved'
            or unquote(sink.get('Quantifiers', '')) != 'ForAll'):
        raise ValueError('Source pub-visitor table selection changed')
    calls = [_attrs(c) for c in root.iter('CallBehavior')]
    if not any(c.get('BehaviorName') == 'getBench' and c.get('Target') == 't_pubTable' for c in calls):
        raise ValueError('Source pub-visitor no longer reserves a table bench')
    follow = [unquote(e.get('expressions', '')) for e in root.iter('Expression')]
    if not any("$t_nextBehavior.name = 'Customer'" in e for e in follow):
        raise ValueError('Source pub-visitor follow-up phase changed')


def check_forwarder(document, name):
    """A tree that only hands its own area to PubVisitor."""
    root = _root(document, name)
    if [c.tag for c in root] != ['Behavior'] or len(root[0]) != 1 or root[0][0].tag != 'CallBehavior':
        raise ValueError('Source pub forwarder is no longer a single call: ' + name)
    call = _attrs(root[0][0])
    if call.get('Target') != '__area.id' or call.get('BehaviorName') != 'PubVisitor':
        raise ValueError('Source pub forwarder target changed: ' + name)


def check_companion(document, name, tag):
    """Visitor follows one link tag to a pub and runs PubVisitor there."""
    root = _root(document, name)
    behavior = root.find('Behavior')
    queries = [] if behavior is None else behavior.findall('.//GraphSearch')
    if not queries:
        raise ValueError('Source pub companion has no pub query')
    for query in queries:
        attrs = _attrs(query)
        filters = [_attrs(f) for f in query]
        if (any(attrs.get(k) != v for k, v in dict(Origin='__area.id', depth='1',
                EdgePruning='parent,inventory', includeOrigin='false').items())
                or attrs.get('AllowedEdges') or attrs.get('SubGraph')
                or [f.tag for f in query] != ['LinkTagFilter', 'HasBehaviorFilter', 'Nodalyzer']
                or filters[0].get('tag') != tag
                or filters[1].get('BehaviorList') != 'PubVisitor' or filters[1].get('Source') != 'Child'
                or filters[2].get('Child') != 'pub'):
            raise ValueError('Source pub companion selection changed')
    calls = [_attrs(c) for c in behavior.iter('CallBehavior')]
    if not any(c.get('Target') == 'pub' and c.get('BehaviorName') == 'PubVisitor' for c in calls):
        raise ValueError('Source pub companion no longer visits the linked pub')


def source_contract(row, documents):
    """documents maps a tree file to its parsed source BehaviorTrees."""
    check_pub_visitor(documents[PUB_FILE])
    if row.contract == 'forwarder':
        check_forwarder(documents[row.tree_file], row.tree_name)
    elif row.contract == 'companion':
        check_companion(documents[row.tree_file], row.tree_name, row.pub.partition(':')[2])
    elif row.contract != 'pub_visitor':
        raise ValueError('Unknown pub-visitor contract: ' + row.contract)


def pub_area(row, entry, archive, entities):
    """(area attributes, its links) of the pub this row's patron visits."""
    if row.pub == 'area':
        return dict(entry['area']), [dict(l) for l in entry['target_links']]
    tag = row.pub.partition(':')[2]
    area = E.Element('Entity', entry['area'])
    links = E.SubElement(area, 'EntityLinks')
    for link in entry['target_links']:
        names = link.get('Name', '').split(',')
        if tag in names and not {'parent', 'inventory'}.intersection(names):
            E.SubElement(links, 'Link', link)
    edge = unique(links, 'source pub link of the companion area')
    resolved = resolve_link_targets(archive, area, entities, {})
    pub = unique((e for e in resolved if e.get('EntityId') == edge.get('TargetId')), 'linked source pub')
    if pub.get('EntityClass') != 'SmartAreaShape':
        raise ValueError('Linked source pub is not a smart area')
    return dict(pub.attrib), [dict(l.attrib) for l in pub.findall('EntityLinks/Link')]


def resolve(entry, archive, source, reader):
    row = row_for(entry)
    if row is None:
        raise ValueError('Not a pub-visitor tree')
    if source is None or reader is None:
        raise ValueError('Pub-visitor work requires its effective source behavior')
    files = {PUB_FILE, row.tree_file}
    blobs = reader(source, {f: ('Scripts.pak', 'Libs/AI/' + f) for f in files})
    source_contract(row, {f: E.fromstring(blobs[f]['data']) for f in files})
    from character_person import source_entities
    import character_pub_rest
    area, links = pub_area(row, entry, archive, source_entities(archive))
    # The bartender's rest phase runs the same table -> getBench -> Seat chain,
    # including the reserved-table and reserved-bench exclusions.
    seats = character_pub_rest.resolve(dict(entry, area=area, target_links=links), archive, source, reader)
    if not seats:
        raise ValueError('Source pub has no public table bench')
    return dict(entry, arrival=seats[0], **{KEY: dict(
        source=list(identity(entry)), pub=area, seats=seats, pending=list(row.pending))})


def converted_seats(mission, source_seats, template):
    """Converted places of the source benches; benches of inactive layers are skipped."""
    seats, missing = [], []
    for source in source_seats:
        pattern = re.compile(r'gm_bench_' + re.escape(source['EntityId']) + r'_\d+_StanceSmartObject')
        places = [e for e in mission if pattern.fullmatch(e.get('Name', ''))]
        if not places:
            missing.append(source['EntityId'])
            continue
        for seat in places:
            props = seat.find('Properties')
            if (seat.get('EntityClass') != 'StanceSmartObject' or props is None
                    or props.get('guidSmartObjectType') != template
                    or not props.get('soclass_SmartObjectHelpers', '').startswith('Sit_1Place_Bench_')):
                raise ValueError('Incompatible converted pub bench: ' + seat.get('Name'))
            if seat not in seats:
                seats.append(seat)
    if not seats:
        raise ValueError('No converted bench at the source pub tables')
    return seats, missing


def bind(mission, scheduler, person, entry, target, *, contract=None):
    """Turn the importer-owned arrival into a hub over the pub's shared seats.

    contract is the native (so_sitPlace template id, unrestricted ``use`` link);
    it is read from the installed game unless a caller supplies it.
    """
    import character_city_benches as benches
    from character_schedule_world import ARRIVAL_TEMPLATE
    work = entry[KEY]
    template, activity = contract or benches.native_contract(target)
    job = unique((e for e in mission if e.get('Name') ==
                  'gm_schedule_' + person + '_' + entry['arrival']['EntityId']), 'pub-visitor arrival')
    props = job.find('Properties')
    if props is None or props.get('guidSmartObjectType') != ARRIVAL_TEMPLATE:
        raise ValueError('Pub-visitor work requires an importer-owned arrival')
    rows = scheduler.find('Schedulers')
    hub_id = str(guid_value(job.get('EntityGuid')))
    hub = unique((r for r in rows if r.get('EntityGuid') == hub_id), 'pub-visitor scheduler hub')
    incoming = [l for r in rows for l in r.findall('Links/S_ActivityLink') if l.get('TargetGuid') == hub_id]
    if len(hub) or not incoming or any(l.find('Parameters') is None
            or l.find('Parameters').get('BehaviorName') != 'use' for l in incoming):
        raise ValueError('Pub-visitor arrival has conflicting scheduler dependencies')
    # Validate every seat before the first mutation.
    seats, missing = converted_seats(mission, work['seats'], template)
    for seat in seats:
        seat_id = str(guid_value(seat.get('EntityGuid')))
        registered = [r for r in rows if r.get('EntityGuid') == seat_id]
        if registered and (len(registered) != 1 or registered[0].tag != 'C_SmartHub' or len(registered[0])):
            raise ValueError('Pub bench has conflicting scheduler dependencies')
    links = benches.choices(seats, activity, incoming)
    job.set('EntityClass', 'SchedulerHub')
    job.remove(props)
    E.SubElement(job, 'Properties', bSaved_by_game='0')
    hub.set('Position', job.get('Pos'))
    for link in incoming:
        link.find('Parameters').attrib.pop('BehaviorName')
    E.SubElement(hub, 'Links')
    waiting = benches.attach(job, hub, rows, seats, links)
    return job, waiting, dict(person=person, job='native_pub_seat', source_behavior=dict(entry['behavior']),
        source_area=dict(entry['area']), source_pub=copy.deepcopy(work['pub']),
        source_seats=copy.deepcopy(work['seats']), unconverted_source_seats=missing,
        target_seats=[dict(name=s.get('Name'), guid=s.get('EntityGuid'), position=s.get('Pos')) for s in seats],
        interval=[entry['start_minute'], entry['end_minute']],
        policy='Native scheduler picks a free place; so_sitPlace use owns movement, sitting and occupancy',
        pending=list(work['pending']), runtime_verified=False)
