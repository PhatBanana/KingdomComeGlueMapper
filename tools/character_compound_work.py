"""Convert KCD1 compound work: a host offers ``compWork`` edges, the worker reserves one.

Every KCD1 compound tree runs the same selection: from the host (smart area or
group object) follow depth-1 ``compWork`` edges whose ``srcBeh`` equals the
requested behaviour tag, then call the edge's ``behavior`` on the target (or on
the host with ``sourceSelf``). Hosts may also add edges at run time from an
authored category query. Works that end in the bench ``use`` behaviour become a
native pool of the already converted shared seats; every other work is reported
as pending and never replaced by an invented activity.

Selection is by tree identity and structure, never by person, town or position.
"""
import copy
import re
import xml.etree.ElementTree as E

from campaign_bindings import parse_link_labels
from campaign_entity_links import guid_value
from character_person import resolve_link_targets, unique, world_entity
from character_station_work import unquote
from upgrade_map import read
import character_area_wait_work as area_wait
import character_city_benches as benches

TAG = 'compWork'
TYPE = 'compoundWork'
# One row per KCD1 tree identity: the (file, tree) of the selection core it runs.
SOURCES = {
    ('final/sa_compoundwork.xml', 'CompoundWork'): ('final/sa_compoundwork.xml', 'CompoundWork'),
    ('final/sa_compoundwork.xml', 'CompoundWorkLODGuarded'): ('final/sa_compoundwork.xml', 'CompoundWork'),
    ('final/sa_compoundworkcamp.xml', 'CompoundWorkCamping'): ('final/sa_compoundwork.xml', 'CompoundWork2_main'),
}
BOOLEANS = ('sourceSelf', 'justIdle')


# Plain CompoundWork is decoded but not claimed: its only census users (castle
# varlets) do seatless wood/carry/bucket chores, so claiming it would only turn
# "adapter missing" residue into a binding failure.
CLAIMED = frozenset(SOURCES) - {('final/sa_compoundwork.xml', 'CompoundWork')}


def supports(entry):
    return area_wait.identity(entry) in CLAIMED and entry.get('target_kind', 'smart_area') == 'smart_area'


def attributes(node):
    return {k: unquote(v) for k, v in node.attrib.items()}


def is_core(tree):
    """A tree selecting compWork edges by the requested behaviour and calling the chosen work."""
    searches = [s for s in tree.iter('GraphSearch')
                if attributes(s).get('Origin') == 't_compoundWorkplace' and attributes(s).get('depth') == '1'
                and attributes(s).get('SubGraph') == TAG]
    selected = any('$compWork.srcBeh == $__behaviorName' in (attributes(f).get('condition', '')
                   + attributes(f).get('Condition', '')) for s in searches for f in s)
    called = any(attributes(c).get('BehaviorName') == '$t_chosenWork.behavior' for c in tree.iter('CallBehavior'))
    return selected and called


def includes(tree, default):
    return {((attributes(n).get('File') or default).replace('\\', '/').lower(), attributes(n).get('Name'))
            for n in tree.iter('IncludeTree')}


def recognize(lookup, location, core=None):
    """True when the tree is, or directly includes, a compound selection core (the given one if any)."""
    location = (location[0].replace('\\', '/').lower(), location[1])
    wrapper = tree(lookup, location)
    if wrapper is None:
        return False
    included = includes(wrapper, location[0])
    candidates = [core] if core else [location, *sorted(included)]
    for candidate in candidates:
        if candidate != location and candidate not in included:
            continue
        found = tree(lookup, candidate)
        if found is not None and is_core(found):
            return True
    return False


def work_defaults(types):
    node = unique((t for t in types.iter('Type') if t.get('name') == TYPE), 'source compound work type')
    return {m.get('name'): (m.text or '').strip() for m in node if m.tag.lower() == 'member'}


def link_works(links, defaults, wanted):
    """(link, work) for authored compWork edges offered to the wanted behaviour tag."""
    result = []
    for link in links:
        if not link.get('Name'):
            continue
        for tag in parse_link_labels(link['Name']):
            if tag['tag'] != TAG or tag['positional']:
                continue
            work = dict(defaults, **{k: str(v).lower() if isinstance(v, bool) else str(v)
                                     for k, v in tag['named'].items()})
            if work.get('srcBeh') == wanted:
                result.append((link, work))
    return result


def dynamic_rules(trees, defaults, wanted):
    """Run-time edges: a category query excluding compWork targets, then AddLink compWork for the wanted tag."""
    rules = []
    for sequence in trees.iter('Sequence'):
        category = None
        for child in sequence:
            if child.tag == 'GraphSearch':
                filters = [attributes(f).get('categories') for f in child.findall('CategoryFilter')]
                excluded = any(attributes(f).get('tag') == TAG for n in child.findall('NegationOp')
                               for f in n.iter('LinkTagFilter'))
                origin = attributes(child).get('Origin', '')
                category = filters[0] if len(filters) == 1 and excluded and origin in ('', 'this.id') \
                    and attributes(child).get('depth') == '1' else None
                continue
            if category is None:
                continue
            for add in child.iter('AddLink'):
                values = attributes(add)
                if values.get('Tag') != TAG or values.get('From') != 'this.id':
                    continue
                named = dict(re.findall(r"(\w+)\(\s*'?([^')]*?)'?\s*\)", values.get('Data', '')))
                work = dict(defaults, **named)
                if work.get('srcBeh') == wanted and (category, work) not in rules:
                    rules.append((category, work))
    return rules


def uses_chosen_workplace(tree):
    """A host behaviour that only forwards to ``use`` on the chosen workplace."""
    root = tree.find('Root')
    calls = [] if root is None else [attributes(c) for c in root.iter('CallBehavior')]
    return len(calls) == 1 and calls[0].get('Target') == 't_chosenWorkplace' and calls[0].get('BehaviorName') == 'use'


def categories(entity):
    props = entity.find('Properties')
    return set() if props is None else set(filter(None, props.get('sWH_AI_EntityCategory', '').split(',')))


def is_seat(entity):
    props = entity.find('Properties')
    return (entity.get('EntityClass') == 'SmartObjectHolder' and 'Seat' in categories(entity)
            and props.get('soclasses_SmartObjectHelpers', '').startswith('Bench_'))


def describe(entity, work):
    props = entity.find('Properties')
    return dict(behavior=work['behavior'], source_self=work.get('sourceSelf') == 'true',
                target_class=entity.get('EntityClass'), target_categories=sorted(categories(entity)),
                target_helper='' if props is None else props.get('soclasses_SmartObjectHelpers', ''))


class Source:
    """Source lookups one resolve needs; a fake with the same methods drives the unit tests."""
    def __init__(self, source, reader):
        from campaign_dependency_adapters import SourceTables
        self.source, self.reader, self.tables, self.files = source, reader, SourceTables(source, reader), {}

    def trees(self, path):
        key = path.replace('\\', '/').lower()
        if key not in self.files:
            entry = path if path.startswith('Libs/') else 'Libs/AI/' + path
            self.files[key] = E.fromstring(self.reader(self.source, {'f': ('Scripts.pak', entry)})['f']['data'])
        return self.files[key]

    def _bound(self, kind, template):
        tags = {r[kind + '_behaviour_tag_id']: r for r in self.tables.get('ai/' + kind + '_behaviour_tag')['rows']}
        owner = kind + ('_smart_area_id' if kind == 'sa' else '_smart_object_id')
        table = 'ai/sa_smart_area2sa_behaviour_tag' if kind == 'sa' else 'ai/so_smart_object2so_behaviour_tag'
        return {tags[b[kind + '_behaviour_tag_id']][kind + '_behaviour_tag_name']:
                (tags[b[kind + '_behaviour_tag_id']]['tree_file'], tags[b[kind + '_behaviour_tag_id']]['tree_name'])
                for b in self.tables.get(table)['rows'] if b[owner] == template}

    def area_behaviors(self, template):
        return self._bound('sa', template)

    def object_behaviors(self, template):
        return self._bound('so', template)


def tree(lookup, location):
    return next((t for t in lookup.trees(location[0]).findall('BehaviorTree') if t.get('name') == location[1]), None)


def collect(host, links, wanted, entities, archive, lookup, defaults, host_behaviors, rules, nested=False):
    """Seats and pending works reachable from one host for one requested behaviour tag."""
    request = E.Element('Entity', host)
    edges = E.SubElement(request, 'EntityLinks')
    for link in links:
        if not {'parent', 'inventory'}.intersection(link.get('Name', '').split(',')):
            E.SubElement(edges, 'Link', link)
    entities = resolve_link_targets(archive, request, entities, {})
    by_id = {e.get('EntityId'): e for e in entities}
    offered = [(by_id[l['TargetId']], w) for l, w in link_works([dict(e.attrib) for e in edges], defaults, wanted)]
    authored = {t.get('EntityId') for t, _ in link_works_targets([dict(e.attrib) for e in edges], by_id)}
    for category, work in rules:
        for edge in edges:
            target = by_id[edge.get('TargetId')]
            if category in categories(target) and target.get('EntityId') not in authored \
                    and not any(target is t and work == w for t, w in offered):
                offered.append((target, work))
    seats, pending = {}, []
    for target, work in offered:
        behavior = work['behavior']
        if work.get('sourceSelf') == 'true':
            location = host_behaviors.get(behavior)
            forwarded = location and tree(lookup, location)
            behavior = 'use' if forwarded is not None and uses_chosen_workplace(forwarded) else None
        if behavior == 'use' and is_seat(target):
            seats[target.get('EntityId')] = dict(world_entity(archive, target, entities).attrib)
            continue
        props = target.find('Properties')
        group = None
        if behavior == 'use' and not nested and props is not None and props.get('guidSmartObjectType'):
            group = lookup.object_behaviors(props.get('guidSmartObjectType')).get('use')
        if group and recognize(lookup, group):
            # A group object runs the same selection on its own edges, requested as its ``use`` behaviour.
            inner, inner_pending, entities = collect(dict(target.attrib),
                [dict(l.attrib) for l in target.findall('EntityLinks/Link')], 'use', entities, archive, lookup,
                defaults, {}, [], nested=True)
            seats.update(inner); pending.extend(inner_pending)
            continue
        pending.append(describe(target, work))
    return seats, pending, entities


def link_works_targets(links, by_id):
    """(target, tag) for every authored compWork edge, whatever behaviour tag it serves."""
    return [(by_id[l['TargetId']], t) for l in links if l.get('Name')
            for t in parse_link_labels(l['Name']) if t['tag'] == TAG]


def resolve(entry, archive, source, reader, lookup=None):
    lookup = lookup or Source(source, reader)
    behavior = entry['behavior']
    if not recognize(lookup, (behavior['tree_file'], behavior['tree_name']), SOURCES[area_wait.identity(entry)]):
        raise ValueError('Unsupported source compound work routine: ' + behavior['tree_name'])
    defaults = work_defaults(lookup.trees(area_wait.TYPES))
    wanted = behavior['sa_behaviour_tag_name']
    host_behaviors = lookup.area_behaviors(entry['binding']['sa_smart_area_id'])
    rules = []
    for path in sorted({f.replace('\\', '/').lower() for f, _ in host_behaviors.values()}):
        for rule in dynamic_rules(lookup.trees(path), defaults, wanted):
            if rule not in rules:
                rules.append(rule)
    entities = list(E.fromstring(read(archive, 'objects_mission0.xml')))
    seats, pending, _ = collect(entry['area'], entry['target_links'], wanted, entities, archive, lookup,
                                defaults, host_behaviors, rules)
    if not seats:
        raise ValueError('Compound work ' + wanted + ' has no convertible work; pending: '
                         + (', '.join(sorted({p['behavior'] + '@' + (p['target_helper'] or p['target_class'])
                                              for p in pending})) or 'no offered work'))
    data = host_behaviors.get(wanted + '_data')
    data_tree = data and tree(lookup, data)
    overrides = area_wait.data_overrides(data_tree) if data_tree is not None else {}
    # Without an area move the worker goes straight to the reserved work.
    arrival = next(iter(seats.values())) if overrides.get('moveToArea') is False \
        else area_wait.arrival_point(entry, archive, overrides)
    return dict(entry, arrival=arrival, compound_work=dict(
        requested=wanted, seats=list(seats.values()), pending=pending, area_move=overrides))


def bind(mission, scheduler, person, entry, target):
    from character_schedule_world import ARRIVAL_TEMPLATE
    contract = entry['compound_work']
    job = unique((e for e in mission if e.get('Name') == 'gm_schedule_' + person + '_' + entry['arrival']['EntityId']),
                 'compound-work arrival')
    props = job.find('Properties')
    if props is None or props.get('guidSmartObjectType') != ARRIVAL_TEMPLATE:
        raise ValueError('Compound work requires an importer-owned arrival')
    rows = scheduler.find('Schedulers')
    hub_id = str(guid_value(job.get('EntityGuid')))
    hub = unique((r for r in rows if r.get('EntityGuid') == hub_id), 'compound-work scheduler hub')
    incoming = [l for r in rows for l in r.findall('Links/S_ActivityLink') if l.get('TargetGuid') == hub_id]
    if len(hub) or not incoming or any(l.find('Parameters').get('BehaviorName') != 'use' for l in incoming):
        raise ValueError('Compound-work arrival has conflicting scheduler dependencies')
    converted, missing = [], []
    for seat in contract['seats']:
        pattern = re.compile(r'gm_bench_' + re.escape(seat['EntityId']) + r'_\d+_StanceSmartObject')
        (converted if any(pattern.fullmatch(e.get('Name', '')) for e in mission) else missing).append(seat)
    if not converted:
        raise ValueError('Compound work has no converted seat: ' + ', '.join(s['EntityId'] for s in missing))
    seats, activity = benches.prepare_sources(mission, converted, target)
    # The holder becomes a transparent hub: the native scheduler reserves one shared seat
    # and the seat's own ``use`` owns movement, sitting, interruption and release.
    job.set('EntityClass', 'SchedulerHub')
    job.remove(props)
    E.SubElement(job, 'Properties', bSaved_by_game='0')
    hub.set('Position', job.get('Pos'))
    for link in incoming:
        link.find('Parameters').attrib.pop('BehaviorName')
    E.SubElement(hub, 'Links')
    waiting = benches.attach(job, hub, rows, seats, benches.choices(seats, activity, incoming))
    return job, waiting, dict(person=person, job='native_compound_seats', source_behavior=dict(entry['behavior']),
        source_area=dict(entry['area']), requested=contract['requested'], source_seats=copy.deepcopy(converted),
        target_seats=[dict(name=s.get('Name'), guid=s.get('EntityGuid'), position=s.get('Pos')) for s in seats],
        unconverted_seats=missing, interval=[entry['start_minute'], entry['end_minute']],
        pending=[p['behavior'] + ' on ' + (p['target_helper'] or p['target_class']) for p in contract['pending']]
                + ['source behaviour run while seated (next-behaviour timing, barks, customer service)'],
        runtime_verified=False)
