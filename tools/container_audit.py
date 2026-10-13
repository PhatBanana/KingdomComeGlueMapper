"""Audit initial-world Stash contracts before native container conversion.

Read-only: records source identities, inventories, links and unresolved semantics.
Never assigns a native household, invents loot or turns personal storage public.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_dependency_adapters import SourceTables
from campaign_entity_links import guid_value
from campaign_inventory import TABLES, resolve_inventory
from campaign_sources import RetailSourceReader
from chairs import inventory
from entity_visuals import world_transform
from player_chests import source_chests
from upgrade_map import read

ZERO = '00000000-0000-0000-0000-000000000000'


def source_guid(value):
    return int(value,16) if '-' not in value and 0 < len(value) <= 16 else guid_value(value)


def kind(model):
    model = model.lower()
    if 'fish' in model: return 'fish_trap_or_basket'
    if 'hive' in model: return 'beehive'
    if 'chest' in model: return 'chest'
    if 'sack' in model or 'bag' in model: return 'sack_or_bag'
    if 'basket' in model: return 'basket'
    if 'shel' in model or 'suppl' in model: return 'shelf_or_supplies'
    if 'coop' in model: return 'coop'
    return 'other'


def inventory_policy(identifier, tables):
    if not identifier or identifier in ('0', ZERO):
        return dict(source_id=identifier, status='no_authored_inventory', blockers=[], item_dependencies=[])
    try:
        resolved = resolve_inventory(identifier, tables)
    except ValueError as error:
        return dict(source_id=identifier, status='unresolved', blockers=[str(error)], item_dependencies=[])
    definition = resolved['definition']; blockers = []
    if definition.get('max_items'): blockers.append('bounded_selection')
    if definition.get('restock_interval', '0') not in ('', '0'): blockers.append('restock_time_unit_conversion')
    if resolved['preset_choices']: blockers.append('nested_or_weighted_presets')
    rows = resolved['direct_items'] + [r for p in resolved['preset_choices'] for r in p['items']]
    for field in ('amount_random_add', 'health_offset', 'priority'):
        if any(r.get(field) not in ('', '0', None) for r in rows): blockers.append(field)
    return dict(source_id=identifier, status='requires_conversion' if blockers else 'fixed_items',
                blockers=blockers, **resolved)


def audit(source, target):
    source, target = Path(source), Path(target)
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as archive:
        entities, stashes, inactive = inventory(archive, 'Stash')
        _, personal = source_chests(archive)
        personal_ids = {r['source_id'] for r in personal}
        links = ET.fromstring(read(archive, 'waitinglinks.xml'))
        indexed = defaultdict(list)
        merchant_targets = set()
        by_guid = {source_guid(e.get('EntityGuid')): e for e in entities.values() if e.get('EntityGuid')}
        for link in links.iter('WaitingLink'):
            host = by_guid.get(source_guid(link.get('SourceId')))
            if host is not None and host.get('EntityClass') == 'Shop':
                merchant_targets.add(source_guid(link.get('TargetId')))
            for definition in link.findall('LinkDefinition'):
                record = dict(source_guid=link.get('SourceId'), target_guid=link.get('TargetId'),
                              definition=definition.text or '', xml=ET.tostring(link, encoding='unicode'))
                for field in ('SourceId','TargetId'):
                    indexed[source_guid(link.get(field))].append(record)
        # Merchant and quest links can live on the referring entity rather
        # than in waitinglinks.xml or on the container itself.
        for host in entities.values():
            for link in host.findall('EntityLinks/Link'):
                destination = entities.get(link.get('TargetId'))
                if destination is None: continue
                if host.get('EntityClass') == 'Shop':
                    merchant_targets.add(source_guid(destination.get('EntityGuid')))
                indexed[source_guid(destination.get('EntityGuid'))].append(dict(
                    source_guid=host.get('EntityGuid'), target_guid=destination.get('EntityGuid'),
                    definition=link.get('Name', ''), xml=ET.tostring(link, encoding='unicode')))
    with RetailSourceReader(source) as reader:
        resolver = SourceTables(source, reader)
        loaded = {n:resolver.get('inventory/'+n) for n in TABLES}
    tables = {n:r['rows'] for n,r in loaded.items()}
    inventories = {}; records = []
    for entity in sorted(stashes, key=lambda e:int(e.get('EntityId'))):
        sid = entity.get('EntityId'); props = entity.find('Properties')
        database = props.find('Database'); identifier = database.get('guidInventoryDBId','').lower() if database is not None else ''
        if identifier not in inventories: inventories[identifier] = inventory_policy(identifier, tables)
        model = props.get('object_Model', '').replace(chr(92), '/').lower()
        network = indexed[source_guid(entity.get('EntityGuid'))]
        definitions = {r['definition'] for r in network}
        definitions.update(l.get('Name','') for l in entity.findall('EntityLinks/Link'))
        roles = []
        if sid in personal_ids: roles.append('personal_storage')
        if source_guid(entity.get('EntityGuid')) in merchant_targets or any('dealerStash' in d for d in definitions):
            roles.append('merchant_stock')
        if any('Quest' in d for d in definitions): roles.append('quest_linked')
        if any('confiscated' in d.lower() for d in definitions): roles.append('confiscated_items')
        if 'bodybag' in model: roles.append('corpse_storage')
        ownership = sorted(d for d in definitions if d in ('owner','automatedLinkedStash','clothesStash','ownershipIgnore'))
        pos, rotation, scale = world_transform(entity, entities)
        lock = props.find('Lock'); phase = props.find('Phase')
        records.append(dict(source_id=sid, source_guid=entity.get('EntityGuid'), name=entity.get('Name'),
            layer=entity.get('Layer',''), kind=kind(model), model=model, position=pos, rotation=rotation, scale=scale,
            hidden=entity.get('HiddenInGame', '0') == '1',
            inventory_id=identifier, inventory_status=inventories[identifier]['status'],
            inventory_blockers=inventories[identifier]['blockers'], protected_roles=roles,
            ownership_links=ownership, link_definitions=sorted(definitions), links=network,
            lock=dict(lock.attrib) if lock is not None else {}, phase=dict(phase.attrib) if phase is not None else {},
            source_properties=ET.tostring(props, encoding='unicode')))
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as archive:
        _, native, _ = inventory(archive, 'Stash')
    native_contracts = []
    for e in native:
        p=e.find('Properties')
        native_contracts.append(dict(name=e.get('Name'), model=p.get('object_Model',''),
                                     properties=ET.tostring(p,encoding='unicode')))
    return dict(schema=1, source=str(source), target=str(target), active_stashes=len(records), inactive_stashes=len(inactive),
        by_kind=dict(Counter(r['kind'] for r in records)),
        inventory_status=dict(Counter(r['inventory_status'] for r in records)),
        protected_roles=dict(Counter(role for r in records for role in r['protected_roles'])),
        ownership_linked=sum(bool(r['ownership_links']) for r in records),
        inventory_blockers=dict(Counter(reason for r in records for reason in r['inventory_blockers'])),
        records=records, inventories=inventories, native_contracts=native_contracts,
        provenance={n:r['provenance'] for n,r in loaded.items()}, runtime_verified=False,
        note='Inventory blockers are deliberately conservative. Missing owners, quest links and native registration require separate validation.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('source','target','output'): parser.add_argument('--'+arg,type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): raise FileExistsError('Choose a fresh audit output')
    result=audit(args.source,args.target)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('records','inventories','native_contracts','provenance')},indent=2))


if __name__=='__main__': main()
