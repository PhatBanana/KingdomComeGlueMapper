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
