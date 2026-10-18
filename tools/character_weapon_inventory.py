"""Shared equipment and source carried-inventory emission for NPC imports."""
import uuid
import xml.etree.ElementTree as E
from pathlib import Path
from upgrade_map import xml


def append_weapons(preset, weapons, registered, item_name, namespace):
    files = {}; equipped=[]
    for item in weapons:
        identity=registered[item['item']]
        if item['equipped']:
            equipped.append((identity,item['amount']))
        else:
            E.SubElement(preset,'PresetItem',Name=item_name(identity),ItemClassId=identity,
                         Amount=str(item['amount']),Health='1',HealthVariation='0')
    if equipped:
        root=E.Element('database',name='barbora')
        group=E.SubElement(E.SubElement(root,'weapon_presets',version='1'),'weapon_preset',
            weapon_preset_id=str(uuid.uuid5(uuid.NAMESPACE_URL,namespace+'/weapons')),
            weapon_preset_name=namespace+'_weapons')
        for identity,amount in equipped:
            E.SubElement(group,'weapon_preset_item',item_class_id=identity,amount=str(amount))
        E.SubElement(preset,'WeaponPresetRef',Name=namespace+'_weapons')
        files['Libs/Tables/item/weapon_preset__'+namespace+'.xml']=xml(root)
    return files


def stage(source,target,mod,person,character,namespace,output,*,reuse_output=False):
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    from campaign_initial_loadout import resolve
    from character_instance import effective_soul
    from container_items import build
    from campaign_inventory import TABLES
    from container_audit import inventory_policy
    from container_loot import compile_inventory
    soul=effective_soul(person['soul'],person['instance'])
    with RetailSourceReader(source) as reader:
        tables=SourceTables(source,reader)
        plan=resolve(tables,soul['soul_id'],
            {k:soul[k] for k in ('initial_clothing_preset_id','initial_weapon_preset_id') if k in soul})
        inventory=inventory_policy(soul.get('inventory_id'),
            {name:tables.get('inventory/'+name)['rows'] for name in TABLES})
        if inventory['status']=='unresolved':
            raise ValueError('Unresolved source actor inventory: '+str(inventory['blockers']))
    weapons=[i for i in plan['items'] if i['kind']=='weapon']
    carried=inventory.get('item_dependencies',[])
    if not weapons and not carried:return dict(items=[],files={})
    report=build(source,target,mod,output,{i['item'] for i in weapons}|set(carried),
                 asset_namespace=namespace+'_weapons',origin='source_actor_weapon_preset',reuse_output=reuse_output)
    root=E.Element('database',name='barbora')
    preset=E.SubElement(E.SubElement(root,'InventoryPresets',version='2'),'InventoryPreset',
                        Name=namespace+'_equipped',Mode='All')
    E.SubElement(preset,'InventoryPresetRef',Name=character['inventory'])
    files={p.relative_to(Path(output)/'converted').as_posix():p.read_bytes()
           for p in (Path(output)/'converted').rglob('*') if p.is_file()}
    files.update(append_weapons(preset,weapons,report['registered_items'],report['item_names'].__getitem__,namespace))
    if carried:
        loot,name,policy=compile_inventory(inventory,report['registered_items'],report['item_names'])
        E.SubElement(preset,'InventoryPresetRef',Name=name)
        files['Libs/Tables/item/InventoryPreset__'+name+'.xml']=xml(loot)
    files['Libs/Tables/item/InventoryPreset__'+namespace+'_equipped.xml']=xml(root)
    character['inventory']=namespace+'_equipped'
    return dict(items=weapons,carried_inventory=inventory,files=files)
