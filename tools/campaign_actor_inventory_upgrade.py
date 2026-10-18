"""Restore source carried presets for previously converted campaign actors.

Updates Storm initialization, never a live actor's inventory or a loaded save.
All item classes must already be registered by the package's item converters.
"""
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def plan(package, source, target, resources):
    from upgrade_map import read, xml
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    from campaign_inventory import TABLES
    from container_audit import inventory_policy
    from container_loot import compile_inventory
    from character_instance import effective_soul
    from world_item_definitions import native_items, native_item_registry
    rules = {n:b for n,b in resources.items() if n.startswith('Libs/Storm/equipment/gm_person_')
             or n.startswith('Libs/Storm/equipment/gm_ska_mother')}
    if not rules:
        return {}, []
    patches, presets = [], {}
    for path in sorted((Path(package)/'Data').glob('*.pak')):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if re.fullmatch(r'libs/tables/item/item(?:__[^/]+)?\.xml', name, re.I):
                    patches.append(read(archive, name))
                elif 'inventorypreset' in name.lower() and name.endswith('.xml'):
                    for preset in ET.fromstring(read(archive, name)).findall('InventoryPresets/InventoryPreset'):
                        presets[preset.get('Name')] = preset
    native = native_items(target, patches)
    registered = native_item_registry(native)
    names = {key:row.get('Name') for key,row in native.items()}
    with zipfile.ZipFile(Path(source)/'Data/Levels/rataje/level.pak') as archive:
        instances = {s.findtext('Name'):s for s in ET.fromstring(read(archive,'whdata_0')).findall('SoulList/Souls/Soul')}
    changes, report = {}, []
    with RetailSourceReader(Path(source)) as reader:
        tables = SourceTables(Path(source), reader)
        souls = {r['soul_name']:r for r in tables.get('rpg/soul')['rows']}
        inventories = {n:tables.get('inventory/'+n)['rows'] for n in TABLES}
        for path, blob in rules.items():
            root = ET.fromstring(blob)
            for rule in root.findall('rules/rule'):
                selected = rule.find('selectors/hasName')
                operation = rule.find('operations/setInventory')
                if selected is None or operation is None:
                    continue
                name = selected.get('name')
                if name not in souls or name not in instances:
                    raise ValueError('Missing source actor inventory identity: '+str(name))
                soul = effective_soul(souls[name], instances[name])
                inventory = inventory_policy(soul.get('inventory_id'), inventories)
                if not inventory.get('item_dependencies'):
                    if inventory['status']=='unresolved':
                        raise ValueError('Unresolved source actor inventory: '+name)
                    continue
                loot, loot_name, _ = compile_inventory(inventory, registered, names)
                original = operation.get('preset')
                def includes(preset, seen=()):
                    if preset==loot_name: return True
                    if preset in seen: raise ValueError('Cyclic inventory preset')
                    return any(includes(ref.get('Name'), (*seen,preset)) for ref in
                               presets.get(preset, ET.Element('InventoryPreset')).findall('InventoryPresetRef'))
                if includes(original):
                    continue
                wrapper_name = original + '_source_carried'
                wrapper = ET.Element('database', name='barbora')
                preset = ET.SubElement(ET.SubElement(wrapper,'InventoryPresets',version='2'),
                                       'InventoryPreset',Name=wrapper_name,Mode='All')
                ET.SubElement(preset,'InventoryPresetRef',Name=original)
                ET.SubElement(preset,'InventoryPresetRef',Name=loot_name)
                operation.set('preset',wrapper_name)
                changes[path]=xml(root)
                changes['Libs/Tables/item/InventoryPreset__'+wrapper_name+'.xml']=xml(wrapper)
                changes['Libs/Tables/item/InventoryPreset__'+loot_name+'.xml']=xml(loot)
                report.append(dict(actor=name,source_inventory=soul['inventory_id'],preset=wrapper_name))
    return changes, report
