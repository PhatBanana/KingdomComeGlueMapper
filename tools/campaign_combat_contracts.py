"""Validate combat module asset bindings and native buff dependencies."""
import xml.etree.ElementTree as E
import zipfile
import hashlib
from upgrade_map import read


ASSET_TYPES = {
    'SoulAsset': 'wh::rpgmodule::I_Soul*',
    'SmartAreaAsset': 'wh::xgenaimodule::SmartArea*',
    'SmartObjectAsset': 'wh::xgenaimodule::SmartObject*',
    'TagPointAsset': 'wh::entitymodule::TagPoint*',
}


def native_fight_effect(scripts):
    """Import the parameterized native helper, with no caller-global assets.

    Used by duelbehavioradvanced in the shipped dialogue-driven bonzak fight.
    Fail on dependency/ABI drift instead of silently emitting an old imitation.
    """
    path = 'Quests/Final/Barbora/utils/combat/fighteffect.xml'
    data = read(scripts, path)
    module = E.fromstring(data).find('./Skald/Module[@Name="fighteffect"]')
    if module is None or module.findall('.//Asset') or module.findall('Definitions/Definition'):
        raise ValueError('Native fighteffect has unresolved dependencies')
    behavior = module.find('Nodes/EnableBehavior')
    required = {('makearray44.Array', 'NPC'), ('isactive', 'IsActive'),
                ('behaviorname', 'Behavior'), ('qso', 'SmartEntity'), ('target', 'target')}
    if behavior is None or behavior.get('Signature') != 'fightRepeated' or not required.issubset(
            {(e.get('From'), e.get('To')) for e in behavior.findall('Edge')}):
        raise ValueError('Native fighteffect activation contract changed')
    return data, dict(path=path, sha256=hashlib.sha256(data).hexdigest(),
        reference='Quests/Final/Barbora/kutnohorsko/kzik_openworld/bonzak_design/bonzak_fistfight.xml',
        adapter='native fighteffect on a quest-local SmartObject host')


def validate_assets(module, instance, assets):
    ports = {p.get('Name'): p.get('Type') for p in module.findall('./Skald/Module/Ports/Port')}
    declarations = {a.get('Name'): a.tag for a in assets}
    result = {}
    for binding in instance.findall('Asset'):
        name, alias = binding.get('Name'), binding.get('Alias')
        kind = declarations.get(alias)
        expected = ASSET_TYPES.get(kind)
        if expected is None or ports.get(name) != expected:
            raise ValueError(f'Unsupported combat asset binding: {alias} ({kind}) -> {name} ({ports.get(name)})')
        result[name] = dict(alias=alias, asset_type=kind, port_type=expected)
    return result


def validate_buffs(module, native_game, required):
    with zipfile.ZipFile(native_game / 'Data/Tables.pak') as z:
        root = E.fromstring(read(z, 'Libs/Tables/rpg/buff.xml'))
    buffs = {b.get('buff_id'): b for b in root.iter('buff')}
    missing = set(required) - buffs.keys()
    if missing:
        raise ValueError('Unconverted combat buffs: ' + ', '.join(sorted(missing)))
    for effect in module.findall('./Skald/Module/Nodes/BuffEffect'):
        value = effect.find("Constant[@Name='BuffGUID']")
        if value is not None and value.get('Value') in buffs:
            if buffs[value.get('Value')].get('is_persistent') == 'true':
                raise ValueError('Persistent combat buff cannot use BuffEffect')
    return {key: dict(buffs[key].attrib) for key in required}
