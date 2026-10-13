"""Express source container loot through native KCD2 inventory presets.

Fixed rows remain explicit. Nested choices retain their weights and selection
limits; quantity draws use the native engine and are not seed-identical to KCD1.
"""
import math
import xml.etree.ElementTree as ET


def number(row, key, default=0):
    value = float(row.get(key) or default)
    if not math.isfinite(value) or value < 0: raise ValueError('Invalid loot '+key)
    return value


def name(identifier):
    return 'gm_container_loot_'+identifier.replace('-', '_')


def compile_inventory(inventory, registered, item_names):
    root = ET.Element('database', name='barbora')
    presets = ET.SubElement(root, 'InventoryPresets', version='2')
    top = name(inventory['source_id'])
    if inventory['status'] == 'no_authored_inventory':
        ET.SubElement(presets, 'InventoryPreset', Name=top, Mode='All')
        return root, top, {'read_only':False, 'restock_days':0, 'quantity_generator':'native'}
    definition = inventory['definition']

    def item(parent, row, label):
        identifier = row['item_id']
        if identifier not in registered: raise ValueError('Unregistered loot item '+identifier)
        amount, addition = number(row,'amount'), number(row,'amount_random_add')
        if amount != int(amount) or addition != int(addition): raise ValueError('Fractional source quantity')
        if amount + addition == 0: return
        health, variation = number(row,'health',1), number(row,'health_offset')
        if health > 1: raise ValueError('Source loot health outside native range')
        variation = min(variation, 1-health)
        target_id = registered[identifier]
        if not item_names.get(target_id): raise ValueError('Missing native loot item name '+target_id)
        # The native preset loader resolves Name. ItemClassId alone passes the
        # XML schema but does not populate the runtime inventory correctly.
        attrs = dict(Name=item_names[target_id], ItemClassId=target_id, Amount=str(int(amount+addition)),
                     Health=format(health,'.9g'), HealthVariation=format(variation,'.9g'))
        weight = row.get('priority')
        if weight not in ('',None): attrs['Weight']=format(number(row,'priority'),'.9g')
        if not addition:
            ET.SubElement(parent,'PresetItem',**attrs)
        else:
            child = top+'_'+label
            # A leaf's quantity selection is independent of its parent's
            # weighted source selection.
            group = ET.SubElement(presets,'InventoryPreset',Name=child,Mode='AmountCount',
                ModeValue=format(amount+addition/2,'.9g'), ModeValueVariation=format(addition/2,'.9g'))
            attrs.pop('Weight',None)
            ET.SubElement(group,'PresetItem',**attrs)
            ref = ET.SubElement(parent,'InventoryPresetRef',Name=child)
            if weight not in ('',None): ref.set('Weight',format(number(row,'priority'),'.9g'))

    target = ET.SubElement(presets,'InventoryPreset',Name=top,Mode='All')
    for index,row in enumerate(inventory['direct_items']): item(target,row,'direct_'+str(index))
    choices = inventory['preset_choices']
    if choices:
        selection = top+'_choices'
        ET.SubElement(target,'InventoryPresetRef',Name=selection)
        cap = number(definition,'max_items')
        pool = ET.SubElement(presets,'InventoryPreset',Name=selection,Mode='AmountCount' if cap else 'All')
        if cap: pool.set('ModeValue',format(cap,'.9g')); pool.set('ModeValueVariation','0')
        for index,choice in enumerate(choices):
            child = top+'_preset_'+str(index)
            ref = ET.SubElement(pool,'InventoryPresetRef',Name=child)
            priority = choice['reference'].get('priority')
            if priority not in ('',None): ref.set('Weight',format(number(choice['reference'],'priority'),'.9g'))
            limit = number(choice['definition'],'max_items')
            preset = ET.SubElement(presets,'InventoryPreset',Name=child,Mode='AmountCount' if limit else 'All')
            if limit: preset.set('ModeValue',format(limit,'.9g')); preset.set('ModeValueVariation','0')
            for offset,row in enumerate(choice['items']): item(preset,row,f'p{index}_item{offset}')
    hours = number(definition,'restock_interval')
    # Native Stash exposes integral world days. Sub-day source intervals use
    # one native day and are called out in the report, never rounded to zero.
    days = math.ceil(hours/24) if hours else 0
    policy = dict(read_only=definition.get('read_only','False').lower()=='true',
        restock_days=days, source_restock_interval=hours, source_restock_unit='hours',
        restock_rounded_to_native_days=bool(hours and days*24!=hours),
        quantity_generator='native; source random seed and selection sequence not preserved',
        source_max_items=definition.get('max_items',''),
        selection_policy='direct rows plus bounded weighted preset choices', runtime_verified=False)
    return root, top, policy
