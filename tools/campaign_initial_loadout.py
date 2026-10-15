"""Resolve authored initial equipment and emit a caller-owned AI sequence.

No player/NPC identity, item list or launch event is selected by this adapter.
The caller must run the sequence once at the original initialization site.
"""
import xml.etree.ElementTree as ET
from campaign_behavior import reference
from campaign_quest_graph import identifier, xml


def resolve(tables, soul_id, overrides=None):
    soul = dict(tables.row('rpg/soul', 'soul_id', soul_id))
    if set(overrides or {}) - {'initial_clothing_preset_id', 'initial_weapon_preset_id'}:
        raise ValueError('Unsupported initial loadout instance override')
    soul.update(overrides or {})
    items, presets = [], {}
    for kind, field, relation, item_field in (
        ('clothing', 'clothing_preset_id', 'armor2clothing_preset', 'armor_id'),
        ('weapon', 'weapon_preset_id', 'weapon2weapon_preset', 'item_id')):
        identity = soul.get('initial_' + field)
        if not identity or identity == '00000000-0000-0000-0000-000000000000':
            continue
        definition = tables.row('item/' + kind + '_preset', field, identity)
        members = [r for r in tables.get('item/' + relation)['rows'] if r[field] == identity]
        presets[kind] = dict(definition=definition, members=members)
        if kind == 'clothing':
            attachments = [r for r in tables.get('item/attachment2clothing_preset')['rows'] if r[field] == identity]
            if attachments:
                raise ValueError('Initial clothing attachments require conversion')
        for row in members:
            amount = row.get('amount', '1')
            if not amount.isdigit() or not 0 < int(amount) <= 2147483647:
                raise ValueError('Invalid source initial equipment amount')
            equipped = row.get('is_equipped', 'True')
            if equipped not in ('True', 'False'):
                raise ValueError('Invalid source equipped flag')
            items.append(dict(item=row[item_field].lower(), amount=int(amount),
                              equipped=equipped == 'True', preset=identity, kind=kind))
    return dict(soul=dict(soul), presets=presets, items=items,
                dependencies=sorted({r['item'] for r in items}),
                inventory=soul.get('inventory_id') or None)


def equipment_sequence(plan, registered_items, target, variable_prefix):
    """Preserve membership, amounts and equip flags; require actual item imports.

    Returns a sequence and explicit WUID variables for its containing tree.
    It does not erase native gear, set stats, or invent a startup trigger.
    """
    identifier(variable_prefix)
    target = reference(target)
    if not target:
        raise ValueError('Initial loadout requires an explicit actor reference')
    missing = set(plan['dependencies']) - registered_items.keys()
    if missing:
        raise ValueError('Unconverted initial equipment: ' + ', '.join(sorted(missing)))
    sequence = ET.Element('Sequence')
    variables = []
    for index, item in enumerate(plan['items']):
        variable = variable_prefix + '_' + str(index)
        variables.append(dict(name=variable, type='_wuid', form='single', values='', isPersistent='0'))
        ET.SubElement(sequence, 'CreateItem', ItemGUID="'" + registered_items[item['item']] + "'",
                      Amount=str(item['amount']), CreatedItem='$' + variable,
                      Target=target, NotifyUI='false')
        if item['equipped']:
            ET.SubElement(sequence, 'EquipItem', item='$' + variable, Target=target)
    return xml(sequence), variables


def bind_player_before(blob, plan, registered_items, soul_asset, destination,
                       input_port, source_event, namespace, definitions):
    """Apply a resolved loadout on a caller-selected, once-only New Game edge.

    Native inventory creation feeds its item descriptor directly to equipment.
    No level-load callback, permanent outfit override, or inventory reset is used.
    """
    from campaign_quest_graph import constant, edge
    identifier(namespace)
    missing = set(plan['dependencies']) - registered_items.keys()
    if missing:
        raise ValueError('Unconverted initial equipment: '+', '.join(sorted(missing)))
    registry = ET.fromstring(definitions)
    for method, typ in [('CreateItems', 'EventMemberFunction'), ('EquipPlayersItem', 'MemberFunction')]:
        found = [d for d in registry.iter('Definition') if d.get('TypeName') == typ and
                 d.find("Properties/Property[@Name='MethodName'][@Value='"+method+"']") is not None]
        if len(found) != 1:
            raise ValueError('Missing native equipment contract: '+method)
    root = ET.fromstring(blob)
    hosts = list(root.find('Skald'))
    if len(hosts) != 1: raise ValueError('Ambiguous graph host')
    host = hosts[0]; nodes = host.find('Nodes')
    if host.find("Assets/SoulAsset[@Name='"+soul_asset+"']") is None:
        raise ValueError('Missing loadout soul asset')
    targets = [n for n in nodes if n.get('Name') == destination]
    links = [e for n in targets for e in n.findall('Edge')
             if e.get('From') == source_event and e.get('To') == input_port]
    if len(targets) != 1 or len(links) != 1:
        raise ValueError('Expected exact once-only initialization edge')
    if any(n.get('Name', '').startswith(namespace+'_') for n in nodes):
        raise ValueError('Loadout already registered')
    soul = ET.SubElement(nodes, 'ObjectProperties', Name=namespace+'_soul', DeclaringType='wh::rpgmodule::I_Soul')
    ET.SubElement(soul, 'Asset', Name='I_Soul', Alias=soul_asset)
    previous = source_event
    for index, item in enumerate(plan['items']):
        name = namespace+'_'+str(index)
        create = ET.SubElement(nodes, 'EventMemberFunction', Name=name+'_create',
                               MethodName='CreateItems', DeclaringType='wh::entitymodule::Inventory')
        edge(create, namespace+'_soul.Inventory', 'Inventory')
        constant(create, 'ItemClass', registered_items[item['item']])
        constant(create, 'Amount', str(item['amount']))
        constant(create, 'ShowUINotification', 'false')
        # Native -1 defaults randomize item wear. Authored initial equipment is
        # fresh; preserve that instead of inheriting random loot condition.
        constant(create, 'Health', '1')
        constant(create, 'Condition', '1')
        edge(create, previous, 'Exec')
        previous = name+'_create.OnExec'
        if item['equipped']:
            equip = ET.SubElement(nodes, 'MemberFunction', Name=name+'_equip',
                                  MethodName='EquipPlayersItem', DeclaringType='wh::entitymodule::EquipmentManager')
            edge(equip, namespace+'_soul.EquipmentManager', 'Manager')
            edge(equip, name+'_create.ItemDescriptor', 'ItemDescriptor')
            edge(equip, previous, 'Exec')
            previous = name+'_equip.OnExec'
    links[0].set('From', previous)
    return xml(root)
