"""Bind source tracked assets to native trackers and expose their predicate.

Call after quest emission. A source tracked objective has three consumers:
automatic completion (objective condition '1'), the IsObjectiveTrackedCompleted
predicate read by dialogue and by other objectives, and journal/map
presentation. This adapter lowers the first two for counted item assets and
named-NPC death assets. An empty or '0' condition never completes by itself:
the objective keeps its source completion path and only gains the predicate.

Markers and zero-count rows are presentation and are listed, not bound. Place
assets, category-only items, class/faction NPC selectors, expressions and
timeouts on a counted objective stay pending. Nothing here is runtime-verified.

Native shapes follow retail KCD2 quest XML: CreateItemClassDescriptor with
MinimumHealth, ItemDescriptorTrigger, and SoulDeathTrigger with a persistent
latch (Quests/Final/Barbora/fist_fights_common_library/
important_npc_death_objective.xml).
"""
from collections import defaultdict
import uuid
import xml.etree.ElementTree as ET

from campaign_objective_conditions import counted_asset
from campaign_quest_graph import all_of, constant, edge, identifier, objective_identifier, xml

PREFIX = 'lowered_track_'
PREDICATE = 'TrackedCompleted'
UNSET = ('', '-1', None)


def completion_mode(objective):
    """'auto', 'manual', or a pending reason for a counted tracked objective."""
    if (objective.get('autocomplete_timeout_str') not in UNSET
            or objective.get('expiration_timeout_str') not in UNSET
            or objective.get('time', '0') not in ('', '0')):
        return None, 'timeout on a tracked objective'
    condition = (objective.get('condition') or '').strip()
    if condition == '1':
        return 'auto', None
    if condition in ('', '0'):
        return 'manual', None
    return None, 'condition expression on a tracked objective'


def item_requirement(row, item, bindings):
    source = (item.get('item_id') or '').lower()
    if not source:
        return None, 'item asset without a class ' + row['quest_asset_id']
    if item.get('item_category_type_id') or item.get('item_category_subtype_id'):
        return None, 'unsupported item type filter ' + row['quest_asset_id']
    category = item.get('item_category_id')
    if category not in ('', '0', None):
        # A class already fixes its category. The extra filter is accepted only
        # when the source item table proves it restates the class's own category.
        known = {k.lower(): v for k, v in bindings.get('item_categories', {}).items()}.get(source)
        if known != category:
            return None, 'unproven item category filter ' + row['quest_asset_id']
    count = int(row['count'])
    if not 0 < count <= 2147483647:
        return None, 'unsupported count ' + row['count']
    health = item.get('min_health')
    minimum = 0.0 if health in ('', None) else float(health)
    if not 0 <= minimum <= 1:
        return None, 'unsupported minimum health ' + str(health)
    target = {k.lower(): v for k, v in bindings.get('item_map', {}).items()}.get(source)
    if target is None:
        return None, 'unmapped item ' + source
    return dict(kind='item', asset=row['quest_asset_id'], source_item=source, target_item=target,
                count=count, minimum_health=minimum), None


def npc_requirement(row, npc, bindings):
    if npc.get('soul_class_id') or npc.get('soul_faction_id') or not npc.get('soul_id'):
        return None, 'unsupported NPC selector ' + row['quest_asset_id']
    if row['count'] != '1':
        return None, 'unsupported NPC count ' + row['count']
    soul = npc['soul_id'].lower()
    alias = {k.lower(): v for k, v in bindings.get('soul_assets', {}).items()}.get(soul)
    if alias is None:
        return None, 'unregistered soul ' + soul
    return dict(kind='npc_death', asset=row['quest_asset_id'], source_soul=soul, soul_asset=alias), None


def plan(model, bindings):
    registered = {str(i).lower() for i in bindings.get('registered_items', ())}
    for source, target in bindings.get('item_map', {}).items():
        uuid.UUID(source); uuid.UUID(target)
        if target.lower() not in registered:
            raise ValueError('Unregistered target item: ' + target)
    for alias in bindings.get('soul_assets', {}).values():
        identifier(alias)
    tables = model['tables']
    objectives = {r['objective_id']: r for r in tables['quest_objective']['rows']}

    def assets(table):
        found = {}
        for row in tables.get(table, {}).get('rows', []):
            if row['quest_id'] != model['quest_id'] or row['quest_asset_id'] in found:
                raise ValueError('Mismatched or duplicate ' + table + ' asset')
            found[row['quest_asset_id']] = row
        return found
    items, npcs, places = assets('quest_item'), assets('quest_npc'), assets('quest_place')
    grouped = defaultdict(list)
    for row in tables.get('quest_tracked_asset', {}).get('rows', []):
        if row['quest_id'] != model['quest_id'] or row['objective_id'] not in objectives:
            raise ValueError('Unknown tracked objective')
        grouped[row['objective_id']].append(row)
    converted, presentation, pending = [], [], []
    for oid, rows in sorted(grouped.items(), key=lambda p: int(p[0])):
        objective = objectives[oid]
        record = dict(objective_id=oid, objective=objective['objective_name'])
        markers = [r for r in rows if not counted_asset(r)]
        counted = [r for r in rows if counted_asset(r)]
        if not counted:
            if (objective.get('condition') or '').strip() == '1':
                # Whether a constant-true objective with nothing to count
                # completes on start is not established. Do not guess.
                pending.append(dict(record, reasons=['constant-true objective with presentation-only tracking']))
            else:
                presentation.append(dict(record, markers=markers))
            continue
        mode, reason = completion_mode(objective)
        reasons, requirements, seen = ([reason] if reason else []), [], set()
        for row in counted:
            aid = row['quest_asset_id']
            if aid in seen:
                reasons.append('duplicate tracked asset ' + aid); continue
            seen.add(aid)
            if aid in items: requirement, why = item_requirement(row, items[aid], bindings)
            elif aid in npcs: requirement, why = npc_requirement(row, npcs[aid], bindings)
            elif aid in places: requirement, why = None, 'place tracking requires a spatial adapter ' + aid
            else: requirement, why = None, 'unknown asset kind ' + aid
            if why: reasons.append(why)
            else: requirements.append(requirement)
        if reasons:
            pending.append(dict(record, reasons=reasons))
        else:
            converted.append(dict(record, mode=mode, requirements=requirements, markers=markers,
                                  predicate=objective_identifier(objective['objective_name']) + '_' + PREDICATE))
    return dict(converted=converted, presentation=presentation, pending=pending, runtime_verified=False)


def bind(blob, model, bindings):
    report = plan(model, bindings)
    root = ET.fromstring(blob)
    quest = root.find('./Skald/Quest')
    if quest is None or quest.get('Name') != model['quest']:
        raise ValueError('Destination quest identity mismatch')
    nodes, ports = quest.find('Nodes'), quest.find('Ports')
    output = nodes.find("Output[@Name='Output']")
    if any(n.get('Name', '').startswith(PREFIX) for n in nodes):
        raise ValueError('Tracking already lowered')
    # campaign_quest_items.bind owns objectives it has already completed.
    owned = [r for r in report['converted'] if nodes.find("If[@Name='tracked_items_" + r['objective_id'] + "_complete']") is not None]
    report['bound_by_quest_items'] = [dict(objective_id=r['objective_id'], objective=r['objective']) for r in owned]
    report['converted'] = [r for r in report['converted'] if r not in owned]
    if not report['converted']:
        return blob, report
    if any(q['kind'] == 'item' for r in report['converted'] for q in r['requirements']):
        player = identifier(bindings.get('player_asset'))
        soul = ET.SubElement(nodes, 'ObjectProperties', Name=PREFIX + 'soul', DeclaringType='wh::rpgmodule::I_Soul')
        ET.SubElement(soul, 'Asset', Name='I_Soul', Alias=player)
        inventory = ET.SubElement(nodes, 'MemberFunction', Name=PREFIX + 'inventory',
                                  MethodName='Items', DeclaringType='wh::entitymodule::Inventory')
        edge(inventory, PREFIX + 'soul.Inventory', 'Inventory')
    for record in report['converted']:
        oid = record['objective_id']; stem = PREFIX + oid
        state_name = 'objective_' + oid
        state = nodes.find("State[@Name='" + state_name + "']")
        if state is None:
            raise ValueError('Missing native objective state ' + oid)
        checks, events = [], []
        for index, req in enumerate(record['requirements']):
            name = stem + '_' + str(index)
            if req['kind'] == 'item':
                desc = ET.SubElement(nodes, 'Function', Name=name + '_descriptor',
                                     MethodName='wh::entitymodule::CreateItemClassDescriptor',
                                     DeclaringType='wh::entitymodule')
                constant(desc, 'ItemClass', req['target_item']); constant(desc, 'Amount', req['count'])
                if req['minimum_health'] > 0:
                    constant(desc, 'MinimumHealth', repr(req['minimum_health']))
                match = ET.SubElement(nodes, 'MemberFunction', Name=name + '_matches',
                                      MethodName='FullyMatchesItems', DeclaringType='wh::entitymodule::ItemDescriptor')
                edge(match, name + '_descriptor.ItemDescriptor', 'ItemDescriptor')
                edge(match, PREFIX + 'inventory.Items', 'InputItems')
                checks.append(name + '_matches.bool')
                if record['mode'] == 'auto':
                    watch = ET.SubElement(nodes, 'ItemDescriptorTrigger', Name=name + '_watch')
                    edge(watch, name + '_descriptor.ItemDescriptor', 'ItemDescriptor')
                    edge(watch, PREFIX + 'soul.Inventory', 'Inventory')
                    edge(watch, state_name + '.Started', 'IsActive')
                    events += [name + '_watch.OnAcquire', name + '_watch.OnTargetAmountAcquire']
            else:
                watch = ET.SubElement(nodes, 'SoulDeathTrigger', Name=name + '_watch')
                ET.SubElement(watch, 'Asset', Name='Souls', Alias=req['soul_asset'])
                edge(watch, state_name + '.Started', 'IsActive')
                # The trigger is an event; the source predicate is a state. Keep
                # the death in a persistent latch, as the retail objective does.
                latch = ET.SubElement(nodes, 'State', Name=name + '_dead', TypeT='bool')
                constant(latch, 'DefaultValue', 'false')
                edge(latch, name + '_watch.OnAllDeath', 'SetTrue')
                checks.append(name + '_dead.State')
                events.append(name + '_dead.OnExec')
        tracked = all_of(nodes, stem + '_tracked', checks)
        ET.SubElement(ports, 'Port', Name=record['predicate'], Direction='Out', Type='bool')
        edge(output, tracked, record['predicate'])
        if record['mode'] != 'auto':
            continue
        # Same deferred boundary as the emitter's constant-true completion: a
        # zero-duration timer, then recheck the requirement and the state.
        timer = ET.SubElement(nodes, 'Timer', Name=stem + '_queued')
        constant(timer, 'Duration', '0s'); constant(timer, 'TimeType', 'GameTime')
        for event in [state_name + '.OnStarted', *events]:
            edge(timer, event, 'SetRunning')
        gate = ET.SubElement(nodes, 'If', Name=stem + '_complete')
        edge(gate, all_of(nodes, stem + '_all', [state_name + '.Started', tracked]), 'Condition')
        edge(gate, stem + '_queued.OnFinished', 'Exec')
        edge(state, stem + '_complete.True', 'SetCompleted')
    return xml(root), report
