"""Bind supported source item-tracking policies to native inventory events.

Call after quest emission. Explicit item mappings must reference registered
target classes. Unsupported predicates, asset kinds and filters stay pending.
"""
from collections import defaultdict
import uuid
import xml.etree.ElementTree as ET
from campaign_quest_graph import all_of, constant, edge, identifier, xml


def plan(model, item_map, registered):
    registered = set(registered)
    for source, target in item_map.items():
        uuid.UUID(source); uuid.UUID(target)
        if target not in registered:
            raise ValueError('Unregistered target item: ' + target)
    tables = model['tables']
    objectives = {r['objective_id']: r for r in tables['quest_objective']['rows']}
    items = {}
    for row in tables.get('quest_item', {}).get('rows', []):
        if row['quest_id'] != model['quest_id'] or row['quest_asset_id'] in items:
            raise ValueError('Mismatched or duplicate quest item')
        items[row['quest_asset_id']] = row
    grouped = defaultdict(list)
    for row in tables.get('quest_tracked_asset', {}).get('rows', []):
        if row['quest_id'] != model['quest_id'] or row['objective_id'] not in objectives:
            raise ValueError('Unknown tracked objective')
        grouped[row['objective_id']].append(row)
    accepted, pending = [], []
    for oid, rows in sorted(grouped.items(), key=lambda p: int(p[0])):
        obj = objectives[oid]
        reasons, requirements = [], []
        if (obj.get('condition', '').strip() != '1'
                or obj.get('autocomplete_timeout_str') not in ('', '-1', None)
                or obj.get('expiration_timeout_str') not in ('', '-1', None)
                or obj.get('time', '0') not in ('', '0')):
            reasons.append('unsupported completion policy')
        seen = set()
        for row in rows:
            aid = row['quest_asset_id']; item = items.get(aid)
            if aid in seen:
                reasons.append('duplicate tracked asset'); continue
            seen.add(aid)
            if item is None:
                reasons.append('non-item asset ' + aid); continue
            if (item.get('item_category_id') not in ('', '0', None)
                    or item.get('item_category_subtype_id')
                    or item.get('item_category_type_id')
                    or item.get('min_health') not in ('', '0', None)):
                reasons.append('unsupported item filter ' + aid); continue
            count = int(row['count'])
            if not 0 < count <= 2147483647:
                reasons.append('unsupported count ' + row['count']); continue
            source = item['item_id']; target = item_map.get(source)
            if target is None:
                reasons.append('unmapped item ' + source); continue
            requirements.append(dict(asset=aid, source_item=source, target_item=target, count=count))
        record = dict(objective_id=oid, objective=obj['objective_name'])
        if reasons:
            pending.append(dict(record, reasons=reasons))
        else:
            accepted.append(dict(record, requirements=requirements))
    return dict(converted=accepted, pending=pending, runtime_verified=False)


def bind(blob, model, item_map, registered, player_asset):
    identifier(player_asset)
    report = plan(model, item_map, registered)
    root = ET.fromstring(blob)
    quest = root.find('./Skald/Quest')
    if quest is None or quest.get('Name') != model['quest']:
        raise ValueError('Destination quest identity mismatch')
    nodes = quest.find('Nodes')
    if any(n.get('Name', '').startswith('tracked_items_') for n in nodes):
        raise ValueError('Inventory tracking already bound')
    if not report['converted']:
        return blob, report
    soul = ET.SubElement(nodes, 'ObjectProperties', Name='tracked_items_soul',
                         DeclaringType='wh::rpgmodule::I_Soul')
    ET.SubElement(soul, 'Asset', Name='I_Soul', Alias=player_asset)
    inventory = ET.SubElement(nodes, 'MemberFunction', Name='tracked_items_inventory',
                              MethodName='Items', DeclaringType='wh::entitymodule::Inventory')
    edge(inventory, 'tracked_items_soul.Inventory', 'Inventory')
    for record in report['converted']:
        oid = record['objective_id']; stem = 'tracked_items_' + oid
        state_name = 'objective_' + oid
        state = nodes.find("State[@Name='" + state_name + "']")
        if state is None:
            raise ValueError('Missing native objective state ' + oid)
        timer = ET.SubElement(nodes, 'Timer', Name=stem + '_queued')
        constant(timer, 'Duration', '0s'); constant(timer, 'TimeType', 'GameTime')
        edge(timer, state_name + '.OnStarted', 'SetRunning')
        checks = [state_name + '.Started']
        for index, req in enumerate(record['requirements']):
            name = stem + '_' + str(index)
            desc = ET.SubElement(nodes, 'Function', Name=name + '_descriptor',
                                 MethodName='wh::entitymodule::CreateItemClassDescriptor',
                                 DeclaringType='wh::entitymodule')
            constant(desc, 'ItemClass', req['target_item']); constant(desc, 'Amount', req['count'])
            match = ET.SubElement(nodes, 'MemberFunction', Name=name + '_matches',
                                  MethodName='FullyMatchesItems', DeclaringType='wh::entitymodule::ItemDescriptor')
            edge(match, name + '_descriptor.ItemDescriptor', 'ItemDescriptor')
            edge(match, 'tracked_items_inventory.Items', 'InputItems')
            checks.append(name + '_matches.bool')
            watch = ET.SubElement(nodes, 'ItemDescriptorTrigger', Name=name + '_watch')
            edge(watch, name + '_descriptor.ItemDescriptor', 'ItemDescriptor')
            edge(watch, 'tracked_items_soul.Inventory', 'Inventory')
            edge(watch, state_name + '.Started', 'IsActive')
            edge(timer, name + '_watch.OnAcquire', 'SetRunning')
            edge(timer, name + '_watch.OnTargetAmountAcquire', 'SetRunning')
        gate = ET.SubElement(nodes, 'If', Name=stem + '_complete')
        edge(gate, all_of(nodes, stem + '_all', checks), 'Condition')
        edge(gate, stem + '_queued.OnFinished', 'Exec')
        edge(state, stem + '_complete.True', 'SetCompleted')
    return xml(root), report
