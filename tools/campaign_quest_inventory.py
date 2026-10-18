"""Separate ordinary inventory and lower quest items to native holder effects."""
import copy
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from container_loot import number
from upgrade_map import read, xml


def split(inventory, quest_ids):
    regular = copy.deepcopy(inventory)
    if any(r['item_id'] in quest_ids for p in inventory['preset_choices'] for r in p['items']):
        raise ValueError('Quest items in weighted source inventory choices need explicit lowering')
    rows = [r for r in inventory['direct_items'] if r['item_id'] in quest_ids]
    regular['direct_items'] = [r for r in regular['direct_items'] if r['item_id'] not in quest_ids]
    for row in rows:
        amount, addition = number(row, 'amount'), number(row, 'amount_random_add')
        if amount != int(amount) or addition != int(addition) or amount < 1 or addition < 0:
            raise ValueError('Quest inventory requires positive integral source quantities')
        if number(row, 'health_offset') or not 0 <= number(row, 'health', 1) <= 1:
            raise ValueError('Unsupported quest inventory health variation')
    return regular, rows


def upgrade(package, source, target, resources, project, startup, level_changes=None):
    if not any(n.startswith(('Libs/Storm/equipment/gm_person_', 'Libs/Storm/equipment/gm_ska_mother')) for n in resources):
        return {}, {}, {}
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    from campaign_inventory import TABLES
    from container_audit import inventory_policy
    from container_loot import compile_inventory
    from character_instance import effective_soul
    from world_item_definitions import native_items, native_item_registry
    from campaign_start_policy import validate_start_policy
    validate_start_policy(resources[project], startup)
    with zipfile.ZipFile(Path(target)/'Data/IPL_GameData.pak') as archive:
        definitions = ET.fromstring(read(archive, 'Libs/concept/definitions.xml'))
    matches = [d for d in definitions.iter('Definition') if d.get('Name') == 'AddQuestItem']
    if len(matches) != 1 or not {'IsActive','ItemClassGUID','BackupLocation','StartingLocation','Health'} <= {p.get('Name') for p in matches[0].find('Ports')}:
        raise ValueError('Missing native quest inventory contract: AddQuestItem')
    patches = []
    for path in sorted((Path(package)/'Data').glob('*.pak')):
        with zipfile.ZipFile(path) as archive:
            patches.extend(read(archive,n) for n in archive.namelist()
                           if re.fullmatch(r'libs/tables/item/item(?:__[^/]+)?\.xml', n, re.I))
    native = native_items(target, patches)
    registered = native_item_registry(native)
    names = {key:row.get('Name') for key,row in native.items()}
    quest_ids = {key for key,row in native.items() if row.get('IsQuestItem','false').lower() == 'true'}
    with zipfile.ZipFile(Path(source)/'Data/Levels/rataje/level.pak') as archive:
        source_objects = ET.fromstring(read(archive, 'objects_mission0.xml'))
        instances = {s.findtext('Name'):s for s in ET.fromstring(read(archive,'whdata_0')).findall('SoulList/Souls/Soul')}
    changes, actors = {}, {}
    with RetailSourceReader(Path(source)) as reader:
        tables = SourceTables(Path(source), reader)
        souls = {r['soul_name']:r for r in tables.get('rpg/soul')['rows']}
        inventories = {n:tables.get('inventory/'+n)['rows'] for n in TABLES}
        for path, blob in resources.items():
            if not path.startswith(('Libs/Storm/equipment/gm_person_', 'Libs/Storm/equipment/gm_ska_mother')):
                continue
            for rule in ET.fromstring(blob).findall('rules/rule'):
                selected = rule.find('selectors/hasName')
                if selected is None or rule.find('operations/setInventory') is None: continue
                name = selected.get('name')
                soul = effective_soul(souls[name], instances[name])
                inventory = inventory_policy(soul.get('inventory_id'), inventories)
                if not inventory.get('item_dependencies'): continue
                regular, rows = split(inventory, quest_ids)
                if not rows: continue
                loot, loot_name, _ = compile_inventory(regular, registered, names)
                changes['Libs/Tables/item/InventoryPreset__'+loot_name+'.xml'] = xml(loot)
                actors[soul['soul_id']] = dict(actor=name, soul=soul['soul_id'],
                    source_inventory=soul['inventory_id'], items=rows)
    ordered = sorted(actors.values(), key=lambda a:a['soul'])
    from campaign_quest_holders import lower
    role_souls = {}
    for path, blob in resources.items():
        if not path.startswith('Libs/Storm/roles/') or not path.endswith('.xml'): continue
        for rule in ET.fromstring(blob).iter('rule'):
            selected = rule.find('selectors/hasName')
            if selected is None or selected.get('name') not in souls: continue
            name = selected.get('name')
            soul = effective_soul(souls[name], instances[name]) if name in instances else souls[name]
            for role in rule.findall('operations/addRole'):
                key = 'dc.'+role.get('name')
                if key in role_souls and role_souls[key] != soul['soul_id']:
                    raise ValueError('Ambiguous quest item role: '+key)
                role_souls[key] = soul['soul_id']
    player = ET.fromstring(resources[project]).find(".//SoulAsset[@Name='travel_player']")
    if player is None: raise ValueError('Quest-item player holder dependency missing')
    for alias in ('player','dc.HENRY'): role_souls[alias] = player.get('SharedSoulGuids')
    with zipfile.ZipFile(Path(package)/'Data/Levels/kcd1_travel/level.pak') as level:
        data = {n:read(level,n) for n in ('objects_mission0.xml','waitinglinks.xml')}
    data.update(level_changes or {})
    graph, level, report = lower(resources, project, startup+'_started.State', ordered,
        role_souls, source_objects, data['objects_mission0.xml'], data['waitinglinks.xml'], quest_ids)
    changes.update(graph)
    report['actors'] = ordered
    return changes, level, report
