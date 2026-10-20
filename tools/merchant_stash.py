"""Resolve a merchant's physical source stash independently of its shop marker."""
from contextlib import ExitStack
import copy
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from static_assets import asset_pack
from upgrade_map import read


def source_stash(source, shop):
    matches = source_stashes(source, shop)
    if len(matches) != 1:
        raise ValueError('Shop must link to exactly one source stash')
    return matches[0]


def source_stashes(source, shop, level='rataje'):
    """All directly authored storage links; native shops can have several."""
    with zipfile.ZipFile(Path(source) / 'Data/Levels' / level / 'level.pak') as archive:
        entities = list(ET.fromstring(read(archive, 'objects_mission0.xml')).iter('Entity'))
        from character_person import resolve_link_targets
        entities = resolve_link_targets(archive, shop, entities, {})
    targets = {link.get('TargetId') for link in shop.findall('EntityLinks/Link')}
    matches = [e for e in entities if e.get('EntityId') in targets and e.get('EntityClass') == 'Stash']
    if not matches:
        raise ValueError('Shop has no authored storage')
    return [copy.deepcopy(e) for e in sorted(matches, key=lambda e: e.get('EntityGuid'))]


def inventory_resources(source, target, package, output, stashes, *, extra_item_patches=()):
    """Convert independent chest loot and keys in addition to the shop stock."""
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    from campaign_inventory import TABLES
    from container_audit import inventory_policy
    from container_loot import compile_inventory
    from container_items import build
    from upgrade_map import xml
    zero = ('', '0', '00000000-0000-0000-0000-000000000000')
    inventories = {}; keys = set()
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        data = {n:tables.get('inventory/'+n)['rows'] for n in TABLES}
        for stash in stashes:
            identity = stash.find('Properties/Database').get('guidInventoryDBId','')
            if identity not in inventories:
                inventory = inventory_policy(identity, data)
                if inventory['status']=='unresolved':
                    raise ValueError('Unresolved merchant chest inventory: '+identity)
                inventories[identity] = inventory
            key = stash.find('Properties/Lock').get('guidItemClassId','').lower()
            if key not in zero: keys.add(key)
    ids = keys | {item for inv in inventories.values() for item in inv['item_dependencies']}
    dependencies = build(source,target,package,output,sorted(ids),asset_namespace=output.name.replace('-', '_'),
        origin='source merchant storage',extra_item_patches=extra_item_patches)
    files={};strings=[];contracts={}
    for path in (output/'converted').rglob('*'):
        if not path.is_file():continue
        name=path.relative_to(output/'converted').as_posix()
        if name.lower().startswith('localization/english/'):strings.append(path.read_bytes())
        else:files[name]=path.read_bytes()
    for identity,inventory in inventories.items():
        root,preset,policy=compile_inventory(inventory,dependencies['registered_items'],dependencies['item_names'])
        files['Libs/Tables/item/InventoryPreset__'+preset+'.xml']=xml(root)
        contracts[identity]=dict(policy,preset=preset,registered_keys=keys)
    return files,strings,contracts,dependencies


def stash_assets(source, stash, prefix):
    model = stash.find('Properties').get('object_Model').replace('\\', '/').lower()
    with ExitStack() as stack:
        index, emitted, material, mesh = asset_pack(stack, source.parent, prefix)
        emitted[prefix + Path(model).name] = mesh(model)
        for lod in (1, 2, 3):
            path = model[:-4] + f'_lod{lod}' + model[-4:]
            if path in index:
                emitted[prefix + Path(path).name] = mesh(path)
        with zipfile.ZipFile(source / 'Data/Objects.pak') as archive:
            for name in archive.namelist():
                if name.lower().startswith(model.rsplit('/', 1)[0] + '/') and name.lower().endswith(('.anm', '.animevents')):
                    emitted[prefix + Path(name).name] = read(archive, name)
        return {name: value.read_bytes() if isinstance(value, Path) else value for name, value in emitted.items()}


def apply_stash_placement(stash, authored, prefix):
    for key in ('Pos', 'Rotate', 'Scale'):
        if authored.get(key) is not None:
            stash.set(key, authored.get(key))
    props = stash.find('Properties')
    original = authored.find('Properties')
    props.set('object_Model', prefix + Path(original.get('object_Model').replace('\\', '/')).name.lower())
    for key in ('fUseAngle', 'fUseDistance', 'sWH_AI_EntityCategory'):
        if original.get(key) is not None:
            props.set(key, original.get(key))
    for tag in ('Animation', 'Physics'):
        previous = props.find(tag)
        if previous is not None:
            props.remove(previous)
        props.append(copy.deepcopy(original.find(tag)))
    # Keep this service chest at its authored location, not a movable rigid body.
    props.find('Physics').set('bRigidBody', '0')
