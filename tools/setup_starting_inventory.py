"""Add selected native supplies on the existing once-only new-game chain."""
import xml.etree.ElementTree as E
import zipfile

from campaign_initial_loadout import bind_player_before
from world_item_definitions import native_items, usable_native_item
from upgrade_map import read

NAMESPACE = 'gm_default_inventory'


def torch(target):
    matches = [r for r in native_items(target).values()
               if r.get('Name') == 'torch_weapon' and r.tag == 'MeleeWeapon'
               and r.get('EntityScript') == 'Torch' and usable_native_item(r)]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous native player torch')
    return matches[0].get('Id').lower()


def bind(blob, item, definitions):
    """Append one unequipped torch, without hooking load/restore or resetting gear."""
    root = E.fromstring(blob)
    nodes = root.find('Skald/Project/Nodes')
    if nodes is None:
        raise ValueError('Missing new-game project')
    destination = nodes.find("*[@Name='gm_source_baseline_stat_agility']")
    incoming = [] if destination is None else destination.findall("Edge[@To='Exec']")
    if len(incoming) != 1:
        raise ValueError('Missing unique new-game loadout continuation')
    existing = [n for n in nodes if n.get('Name', '').startswith(NAMESPACE+'_')]
    if existing:
        create = nodes.find("EventMemberFunction[@Name='"+NAMESPACE+"_0_create']")
        soul = nodes.find("ObjectProperties[@Name='"+NAMESPACE+"_soul']")
        expected = dict(ItemClass=item, Amount='1', Health='1', Condition='1', ShowUINotification='false')
        if (len(existing) != 2 or create is None or create.get('MethodName') != 'CreateItems'
                or create.get('DeclaringType') != 'wh::entitymodule::Inventory'
                or soul is None or soul.get('DeclaringType') != 'wh::rpgmodule::I_Soul'
                or len(soul) != 1 or dict(soul[0].attrib) != dict(Name='I_Soul',Alias='travel_player')
                or soul[0].tag != 'Asset'
                or {c.get('Name'):c.get('Value') for c in create.findall('Constant')} != expected
                or len(create.findall('Constant')) != len(expected)
                or len(create.findall('Edge')) != 2
                or create.find("Edge[@To='Inventory'][@From='"+NAMESPACE+"_soul.Inventory']") is None
                or incoming[0].get('From') != NAMESPACE+'_0_create.OnExec'
                or create.find("Edge[@To='Exec']") is None
                or not create.find("Edge[@To='Exec']").get('From','').startswith('gm_source_initial_loadout_')):
            raise ValueError('Conflicting default inventory registration')
        return blob
    previous = incoming[0].get('From', '')
    if not previous.startswith('gm_source_initial_loadout_'):
        raise ValueError('Default supplies require the once-only source loadout chain')
    plan = dict(dependencies=[item], items=[dict(item=item, amount=1, equipped=False)])
    return bind_player_before(blob, plan, {item:item}, 'travel_player',
        destination.get('Name'), 'Exec', previous, NAMESPACE, definitions)


def validate(blob):
    root = E.fromstring(blob)
    item = root.find(".//EventMemberFunction[@Name='"+NAMESPACE+"_0_create']/Constant[@Name='ItemClass']")
    if item is None or not item.get('Value'):
        raise ValueError('Missing new-game torch registration')
    bind(blob,item.get('Value'),None)


def upgrade(package, target):
    from setup_gameplay import PROJECT
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    if target is None:
        raise ValueError('KCD2 is required to resolve the starting torch')
    item = torch(target)
    with zipfile.ZipFile(target/'Data/IPL_GameData.pak') as z:
        definitions = read(z, 'Libs/concept/definitions.xml')
    path = 'Data/gluemappertravel.pak'
    with zipfile.ZipFile(package/path) as z:
        original = read(z, PROJECT)
    updated = bind(original, item, definitions)
    changes = {}
    if updated != original:
        rewrite(package, path, {PROJECT:updated})
        changes[path] = digest(package/path)
    return changes, dict(item=item, amount=1, equipped=False, new_game_only=True, runtime_verified=False)
