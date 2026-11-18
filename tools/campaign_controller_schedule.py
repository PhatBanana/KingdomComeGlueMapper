"""Bind a controller's daycycle requests to the level, for the lease adapter.

The maintainer's lease machinery (campaign_schedule_requests, _routes,
_lifecycle) lowers a `daycycle:change` request only when its actor is one
imported entity and its shape is the one the lifecycle adapter implements.
It is transactional over a whole controller: one request outside that shape
withholds every tree. This module selects, per tree, what the adapter can
take today and says why the rest cannot, so the converter can lower the
accepted trees and keep a typed reason on the others:

    normalise        each request rewritten to the fields KCD1's own consumer acts on
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


FIELD = re.compile(r"\s*(\w+)\(\s*('[^'\r\n]*'|[^(),'\r\n]+)\s*\)\s*(?:,|$)")
# KCD1 `Libs/AI/final/sb_daycycles.xml`, the `daycycleChange` inbox of every NPC, is the
# consumer of `daycycle:change`; `Libs/AI/TypeDefinitions.xml` has the field defaults.
# Each rule below restates what that tree does with a field before `AddPatch`/`RemovePatch`.
CRITICAL_PRIORITY = {'cutscene_init': 100, 'cutscene_dialogFadingIn': 95}
NUMBER = re.compile(r'-?\d+(?:\.\d+)?')


def _fields(values):
    fields, offset = {}, 0
    while values[offset:].strip():
        match = FIELD.match(values, offset)
        if not match or match[1] in fields:
            return None
        fields[match[1]] = match[2].strip()
        offset = match.end()
    return fields


BOUNDARY = 'Sean, 2026-11-16 (relayed by Build), decision 11a: urgency Slow stands for the next activity boundary'


def normalise(model, boundary=False):
    """Rewrite the controller's daycycle requests in place; return the report.

    removal      only `handle` is read (`RemovePatch handle`): `name` and
                 `immediateDaycycleHaltSpeed` on a removal are dropped
    critical     `criticalPriority` replaces the priority (100 for cutscene_init,
                 95 for cutscene_dialogFadingIn) and is not stored in the patch
    immediate    absent means false (the type's default); when true the consumer
                 sets the window to the whole day, so a written window is dropped
    window       `startTime`/`endTime` are hours of the day (defaults 0 and 24).
                 On a request that is not immediate a narrower static window is
                 kept in `windows` as minutes and removed from the request; a
                 whole-day window is the default and is dropped. `startTime(-1)`
                 with an `endTime` below 24 is a duration from the moment of the
                 request and is left as written (no level-side form).
    boundary     with `boundary` (decision 11a), an addition that is not immediate
                 is presented to the lease adapter as immediate: KCD1 lets the
                 running activity end first, and no level field says that; the
                 lease's urgency Slow (`native_policies`) stands for it. A
                 stand-in, listed in `boundaries`; its window is kept.
    A request with any other unlisted field, or a dynamic value in one of these,
    is left as written.
    """
    own = 'libs/ai/quests/' + model['quest'].lower() + '.xml'
    report = dict(rewritten=[], windows={}, left=[], boundaries=[])
    for tree, body in model['behavior_documents'][own]['trees'].items():
        stack = [(body['root'], 'Root')]
        while stack:
            node, path = stack.pop()
            stack.extend((child, path + '/' + str(i)) for i, child in enumerate(node['children']))
            raw = node['attributes'].get('values')
            if raw is None or node['attributes'].get('type', '').strip('"').strip("'") != 'daycycle:change':
                continue
            quote = '"' if len(raw) > 1 and raw[0] == raw[-1] == '"' else ''
            fields = _fields(raw[1:-1] if quote else raw)
            if fields is None or fields.get('add') not in ('true', 'false'):
                continue
            rules, window = [], None
            if fields['add'] == 'false':
                for name in ('name', 'immediateDaycycleHaltSpeed'):
                    if fields.pop(name, None) is not None:
                        rules.append('removal:' + name)
            else:
                critical = fields.get('criticalPriority', '').removeprefix('$enum:daycyclePatchCriticalPriority.')
                if critical in CRITICAL_PRIORITY:
                    fields['priority'] = str(CRITICAL_PRIORITY[critical])
                    del fields['criticalPriority']
                    rules.append('critical:' + critical)
                if 'immediate' not in fields:
                    fields['immediate'] = 'false'
                    rules.append('immediate:default')
                if 'startTime' in fields or 'endTime' in fields:
                    start, end = fields.get('startTime', '0'), fields.get('endTime', '24')
                    static = bool(NUMBER.fullmatch(start) and NUMBER.fullmatch(end))
                    if fields['immediate'] == 'true':
                        rules.append('window:immediate')
                    elif static and (float(end) >= 24 and float(start) in (0, -1)):
                        rules.append('window:whole_day')
                    elif static and 0 <= float(start) < float(end) <= 24 and all(
                            (float(v) * 60).is_integer() for v in (start, end)):
                        window = (int(float(start) * 60), int(float(end) * 60))
                        rules.append('window:kept')
                    else:
                        report['left'].append(dict(tree=tree, path=path, reason='relative, wrapping or dynamic window'))
                        window = False
                    if window is not False:
                        fields.pop('startTime', None); fields.pop('endTime', None)
                if boundary and fields['immediate'] == 'false' and window is not False:
                    fields['immediate'] = 'true'
                    rules.append('boundary:slow')
                    node['stand_in'] = 'immediate lease, urgency Slow'
                    report['boundaries'].append(dict(tree=tree, path=path))
            if window:
                report['windows'][(tree, path)] = window
            if rules:
                node['attributes']['values'] = quote + ','.join('%s(%s)' % item for item in fields.items()) + quote
                report['rewritten'].append(dict(tree=tree, path=path, rules=rules, source=raw))
    report['rules'] = dict(sorted(Counter(r.split(':')[0] + ':' + r.split(':')[1] if r.startswith('window') else r.split(':')[0]
                                          for row in report['rewritten'] for r in row['rules']).items()))
    return report


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
    # Every reference bound to exactly one object, with its quest asset (alias and class).
    assets = {expression: dict(alias=names[0], asset_type=by_name[names[0]]['asset_type'])
              for expression, names in plan['references'].items() if len(names) == 1}
    return dict(level=level, controller=controller, references=references, assets=assets,
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


def select(model, references, windows=None):
    """Return (trees, actor_bindings, report) for the requests the adapter accepts.

    `windows` is `normalise`'s: a time window is part of a lease's policy.
    """
    windows = windows or {}
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

    def identity(r):
        return references[r['actor'].lstrip('$')], r['handle']

    def policy(tree, r):
        return (r['behavior'], r['source'], r['priority'], r['immediate'], r['once'], r.get('callback', {}).get('tree'),
                windows.get((tree, r['path'])))
    # Every addition of the accepted shape, in whichever tree: a lease whose addition
    # sits in a waiting tree waits with it; one with no such addition has none to bind.
    known = {identity(r) for tree, records in requests.items() for r in records if not r['missing'] and r['add']}
    # A lease is one actor and handle. It needs an addition with one policy
    # among the accepted trees; otherwise every tree that touches it waits.
    changed, causes = True, {}
    while changed:
        changed = False
        leases = {}
        for tree in accepted:
            for r in requests[tree]:
                lease = leases.setdefault(identity(r), dict(sites=[], policies=set()))
                lease['sites'].append((tree, r['path']))
                if r['add']:
                    lease['policies'].add(policy(tree, r))
        for key, lease in leases.items():
            policies = lease['policies']
            if len(policies) == 1 and None not in {p[5] for p in policies}:
                continue
            # The maintainer's lease holds its source as written, so the controller named
            # `$this.id` in its entry tree and `$__object.id` in a tree it runs are two policies.
            cause = ('lease_from_two_scopes' if len(policies) > 1 and len({p[:1] + p[2:] for p in policies}) == 1
                     else 'lease_policy' if policies
                     else 'lease_in_a_waiting_tree' if key in known else 'removal_without_addition')
            for site in lease['sites']:
                causes[site] = cause
            accepted -= {tree for tree, _ in lease['sites']}
            changed = True
    rejected.update(causes.values())
    bindings = {(own, tree, r['actor']): references[r['actor'].lstrip('$')] for tree in accepted for r in requests[tree]}
    report = dict(requests=sum(map(len, requests.values())), trees_with_requests=len(requests),
                  accepted_requests=sum(len(requests[t]) for t in accepted), accepted_trees=sorted(accepted),
                  rejected=dict(sorted(rejected.items())), runtime_verified=False, publishable=False)
    # Why each request site outside the accepted trees waits: {tree: {path: capability}}.
    report['sites'] = {tree: {r['path']: r['missing'] or causes.get((tree, r['path']), 'tree')
                              for r in records} for tree, records in requests.items() if tree not in accepted}
    # Requests of the accepted shape that wait because their tree holds a rejected one.
    report['accepted_shape_in_a_rejected_tree'] = (report['requests'] - report['accepted_requests']
                                                   - sum(rejected.values()))
    return {(own, tree) for tree in accepted}, bindings, report


def adapter(model, level, namespace, windows=None):
    """Return (ScheduleAdapter or None, report) for the accepted trees of one controller."""
    from campaign_schedule_lifecycle import ScheduleAdapter
    from campaign_schedule_routes import plan
    trees, bindings, report = select(model, level['references'], windows)
    report.update(level=level['level'], controller=level['controller'])
    if not trees:
        return None, report
    prepared = plan(model, bindings, trees)
    report['leases'] = [dict(actor=lease['actor'], handle=lease['handle'], sites=len(lease['sites']),
                             behavior=lease['policy']['behavior'], priority=lease['policy']['priority'],
                             once=lease['policy']['once']) for lease in prepared['leases']]
    return ScheduleAdapter(prepared, level['controller'], namespace), report


def native_policies(prepared, boundaries=()):
    """{(actor, handle): priority, urgency, evidence} for `campaign_schedule_routes.assemble`.

    `boundaries` is `normalise`'s: a lease with such a site says so in its evidence.

    The same mapping the maintainer's callers use (`campaign_behavior_schedule.source_policy`):
    the source priority as written, and the halt speed, whose KCD1 default is slow. An
    addition that names another halt speed is not accepted by the request parser.
    """
    waits = {(site['tree'], site['path']) for site in boundaries}
    return {(lease['actor'], lease['handle']): dict(
        priority=lease['policy']['priority'], urgency='Slow',
        evidence='KCD1 priority as written; immediateDaycycleHaltSpeed defaults to slow (TypeDefinitions.xml), '
                 'mapped as campaign_behavior_schedule.source_policy does'
                 + ('; stand-in for a request that waits for the next activity (' + BOUNDARY + ')'
                    if any((site['tree'], site['path']) in waits for site in lease.get('sites', ())) else ''))
            for lease in prepared['leases']}


def apply_windows(scheduler, routes, windows):
    """Write each lease's time window onto its assembled activity link; return the count.

    `scheduler` and `routes` are `assemble`'s (the scheduler table copy and its report rows);
    `windows` is `normalise`'s. Retail links carry `TimeOfDayStart`/`TimeOfDayEnd` in minutes.
    """
    changed = 0
    for route in routes:
        found = {windows[(site['tree'], site['path'])] for site in route['lease']['sites']
                 if site['add'] and (site['tree'], site['path']) in windows}
        if not found:
            continue
        if len(found) != 1:
            raise ValueError('Schedule lease has two time windows: ' + route['lease']['handle'])
        links = [link for link in scheduler.iter('S_ActivityLink') if link.find('Parameters') is not None
                 and link.find('Parameters').get('BehaviorName') == route['behavior']]
        if len(links) != 1:
            raise ValueError('Schedule lease has no unique activity link: ' + route['behavior'])
        start, end = next(iter(found))
        parameters = links[0].find('Parameters')
        if 'TimeOfDayStart' not in parameters.attrib or 'TimeOfDayEnd' not in parameters.attrib:
            raise ValueError('Activity link template has no time window fields')
        parameters.set('TimeOfDayStart', str(start)); parameters.set('TimeOfDayEnd', str(end))
        changed += 1
    return changed


def preflight(prepared, controller, objects, template, conversion):
    """What `campaign_schedule_routes.assemble` would need from this converted world, and has.

    `objects` is the converted level's entity list, `template` the controller's
    converted smart-object template or None, `conversion` the behaviour
    compiler's report. Every lack is listed, not only the first one `assemble`
    would raise on.
    """
    from campaign_entity_links import guid_value
    entities = {str(guid_value(e.get('EntityGuid'))): e for e in objects if e.get('EntityGuid')}
    host = entities.get(str(guid_value(controller)))
    registered = {b.get('Name') for b in template.iter('SmartBehaviorTemplate')} if template is not None else set()
    emitted = {(r['document'], r['tree']) for r in conversion['trees']
               if r['owner'] == prepared['owner'] and r['native_emitted']}
    leases = [dict(actor=lease['actor'], handle=lease['handle'], behavior=lease['policy']['behavior'],
                   actor_in_world=lease['actor'] in entities,
                   callback_emitted=(lease['policy']['callback']['document'], lease['policy']['callback']['tree']) in emitted,
                   callback_registered=lease['policy']['behavior'] in registered) for lease in prepared['leases']]
    report = dict(controller_in_world=host is not None,
                  controller_is_holder=host is not None and host.get('EntityClass') == 'SmartObjectHolder',
                  template=template is not None, leases=leases)
    report['ready'] = (report['controller_is_holder'] and report['template']
                       and all(l['actor_in_world'] and l['callback_emitted'] and l['callback_registered'] for l in leases))
    return report


def install(lease, objects, scheduler, template, activity_template, conversion, behaviors, namespace, native,
            windows, boundaries=()):
    """Assemble the world side of the accepted leases: the maintainer's `assemble`
    (which calls `ScheduleAdapter.install`) with `native_policies`, then `apply_windows`.

    `lease` is the adapter `adapter()` returned and the compiler used. Returns
    `assemble`'s tuple with the windows written and counted in its report.
    Not exercised on a real world yet: no converted level holds the controller.
    """
    from campaign_schedule_routes import assemble
    check = preflight(lease.plan, lease.controller, objects, template, conversion)
    if not check['ready']:
        raise ValueError('Converted world cannot take the leases yet: ' + ', '.join(
            sorted(k for k in ('controller_in_world', 'controller_is_holder', 'template') if not check[k])
            + ['%d of %d leases incomplete' % (sum(not (l['actor_in_world'] and l['callback_emitted'] and l['callback_registered'])
                                                   for l in check['leases']), len(check['leases']))]))
    world, schedule, host_template, additions, report = assemble(
        lease.plan, objects, scheduler, lease.controller, template, activity_template, conversion, behaviors,
        native_policies(lease.plan, boundaries), namespace, lifecycle=lease, native=native)
    report['windows_written'] = apply_windows(schedule, report['routes'], windows)
    return world, schedule, host_template, additions, report
