"""Bind a controller's daycycle requests to the level, for the lease adapter.

The maintainer's lease machinery (campaign_schedule_requests, _routes,
_lifecycle) lowers a `daycycle:change` request only when its actor is one
imported entity and its shape is the one the lifecycle adapter implements.
It is transactional over a whole controller: one request outside that shape
withholds every tree. This module selects, per tree, what the adapter can
take today and says why the rest cannot, so the converter can lower the
accepted trees and keep a typed reason on the others:

    level_bindings   source level -> controller GUID and {expression: actor GUID}
    select           trees whose every request is accepted, and the capability
                     each rejected request lacks
    adapter          the maintainer's plan and ScheduleAdapter for those trees

Nothing here assembles the world side (scheduler links, native priority and
urgency, the consumer registration): `ScheduleAdapter.install` does that from
the converted level, and a lowered request is not publishable without it.
Not runtime-verified.
"""
from collections import Counter
import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

from campaign_bindings import build_bindings
from campaign_entity_links import native_guid
from campaign_schedule_requests import dependencies

# The lifecycle adapter's accepted shape (ScheduleAdapter.__init__ and
# campaign_schedule_requests.request).
SELF = ('this.id', '__object.id')


def level_bindings(kcd1, level, model):
    """Resolve the controller object and its link-bound aliases from the source level."""
    from campaign_linker import link_entities
    from upgrade_map import read
    name = model['tables']['quest']['rows'][0].get('smart_object') or model['quest']
    with zipfile.ZipFile(Path(kcd1) / 'Data/Levels' / level / 'level.pak') as archive:
        souls = ET.fromstring(read(archive, 'whdata_0'))
        documents = {n: read(archive, n) for n in archive.namelist()
                     if n.lower() == 'objects_mission0.xml'
                     or (n.lower().startswith('layers/') and n.lower().endswith('.xml'))}
    world = link_entities(documents, name, [name])
    plan = build_bindings(model, world, souls)
    if plan['controller'] is None:
        raise ValueError('Controller object is not in the level: ' + name)
    by_name = {b['name']: b for b in plan['bindings']}
    references = {}
    for expression, assets in plan['references'].items():
        if len(assets) == 1 and by_name[assets[0]]['registration']['kind'] in ('entity', 'placed_soul'):
            references[expression] = by_name[assets[0]]['registration']['guid']
    controller = native_guid(int(world['entities'][plan['controller']]['attributes']['EntityGuid'].replace('-', ''), 16))
    return dict(level=level, controller=controller, references=references,
                ambiguous=sorted(e for e, assets in plan['references'].items() if len(assets) != 1))


def _missing(record, callback, references):
    """The capability a request needs that the lease adapter lacks, or None."""
    if 'error' in record:
        return {'Daycycle addition requires explicit scheduling policy': 'addition_fields',
                'Unconverted daycycle removal fields': 'removal_fields',
                'Dynamic daycycle handle requires runtime identity conversion': 'dynamic_handle'}.get(
                    record['error'], 'unparsed_request')
    if record['operation'] != 'InstantSendMessageToNPC':
        return 'synchronous_request'
    actor = record['actor'].lstrip('$')
    if actor in SELF or not re.fullmatch(r"t_\w+\['[^']+'\]", actor):
        return 'runtime_actor'
    if actor not in references:
        return 'actor_not_in_level'
    if record['add']:
        if not record['immediate']:
            return 'next_activity_boundary'
        if record['source'].lstrip('$') not in SELF or (callback and record['source'].lstrip('$') == 'this.id'):
            return 'source_scope'
    return None


def select(model, references):
    """Return (trees, actor_bindings, report) for the requests the adapter accepts."""
    from campaign_sources import key
    from quest_import import behavior_path
    own = 'libs/ai/quests/' + model['quest'].lower() + '.xml'
    callbacks = {e['tree'] for e in (model.get('controller_registration') or {}).get('entry_points', [])
                 if e.get('kind') == 'behavior_callback' and key(behavior_path(e['file'])) == own}
    requests, rejected = {}, Counter()
    for tree, body in model['behavior_documents'][own]['trees'].items():
        records = dependencies(model, body['root'])
        if records:
            requests[tree] = [dict(r, missing=_missing(r, tree in callbacks, references)) for r in records]
    accepted = {tree for tree, records in requests.items() if not any(r['missing'] for r in records)}
    for records in requests.values():
        rejected.update(r['missing'] for r in records if r['missing'])
    # A lease is one actor and handle. It needs an addition with one policy
    # among the accepted trees; otherwise every tree that touches it waits.
    changed = True
    while changed:
        changed = False
        leases = {}
        for tree in accepted:
            for r in requests[tree]:
                lease = leases.setdefault((references[r['actor'].lstrip('$')], r['handle']), dict(trees=set(), policies=set()))
                lease['trees'].add(tree)
                if r['add']:
                    lease['policies'].add((r['behavior'], r['source'], r['priority'], r['immediate'], r['once'],
                                           r.get('callback', {}).get('tree')))
        for lease in leases.values():
            if len(lease['policies']) != 1 or None in {p[5] for p in lease['policies']}:
                rejected['lease_policy'] += sum(len(requests[t]) for t in lease['trees'] & accepted)
                accepted -= lease['trees']
                changed = True
    bindings = {(own, tree, r['actor']): references[r['actor'].lstrip('$')] for tree in accepted for r in requests[tree]}
    report = dict(requests=sum(map(len, requests.values())), trees_with_requests=len(requests),
                  accepted_requests=sum(len(requests[t]) for t in accepted), accepted_trees=sorted(accepted),
                  rejected=dict(sorted(rejected.items())), runtime_verified=False, publishable=False)
    # Requests of the accepted shape that wait because their tree holds a rejected one.
    report['accepted_shape_in_a_rejected_tree'] = (report['requests'] - report['accepted_requests']
                                                   - sum(rejected.values()))
    return {(own, tree) for tree in accepted}, bindings, report


def adapter(model, level, namespace):
    """Return (ScheduleAdapter or None, report) for the accepted trees of one controller."""
    from campaign_schedule_lifecycle import ScheduleAdapter
    from campaign_schedule_routes import plan
    trees, bindings, report = select(model, level['references'])
    report.update(level=level['level'], controller=level['controller'])
    if not trees:
        return None, report
    prepared = plan(model, bindings, trees)
    report['leases'] = [dict(actor=lease['actor'], handle=lease['handle'], sites=len(lease['sites']),
                             behavior=lease['policy']['behavior'], priority=lease['policy']['priority'],
                             once=lease['policy']['once']) for lease in prepared['leases']]
    return ScheduleAdapter(prepared, level['controller'], namespace), report
