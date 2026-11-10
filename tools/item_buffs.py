"""Drink and weapon buffs of imported source items.

The target game names the buff of a Food, Ointment or Poison row by buff_id
(BuffDefinitionId, and WeaponBuffDefinitionId on Poison rows only). A source
buff is resolved in this order:

1. The target still ships the source buff_id: reference the shipped row.
2. A reviewed template names the closest shipped buff. The converted row takes
   its class, exclusivity, lifetime, AI tag, UI fields, icon and implementation
   from that template; strength (params) and duration stay the source values,
   with source modifier names rewritten to their target spelling.
3. Otherwise the buff is reported unported with its reason. Nothing is guessed.

Weapon coating is a property of the Poison item class in the target game. The
shipped game kept the weapon buffs of exactly the source potions whose food
subtype is ``poison`` and dropped every other one, so only those are coated.
"""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from campaign_buffs import TEXT, native_contract
from campaign_quest_graph import identifier, xml
from upgrade_map import read

# Stat names respelled by the target game. Each pair is shown at least four
# times by shipped rows that retained their source buff_id and clause order
# (alpha_male_in_love cha+3 -> charisma+3, jail_recovery str/vit/agi,
# perk_merchants_wit spc, owned dog hea, unconscious vis).
MODIFIER_NAMES = dict(cha='charisma', str='strength', agi='agility', vit='vitality',
                      spc='speech', hea='hearing', vis='vision')
TEMPLATE_FIELDS = ('buff_class_id', 'buff_exclusivity_id', 'buff_lifetime_id', 'buff_ai_tag_id',
                   'buff_ui_type_id', 'buff_ui_visibility_id', 'buff_ui_order', 'icon_id',
                   'slot_icon_id', 'is_persistent', 'implementation')

# source buff_id -> closest shipped buff. ``source_fields`` keep the source
# value of a field whose numeric meaning is unchanged in the target game;
# ``params`` append the target spelling of an effect the source expressed
# outside its params; ``family`` keeps the template's buff_family_id.
TEMPLATES = {
    '2edf8a8e-7eba-49e9-aa29-d3149d78c7fd': dict(  # potion_love: cha+5, 600 s
        template='1f398bd2-05ea-4a56-b883-9ac3ba3ad01a', name='potion_bard',
        why='Sibling social-stat potion; the source rows differed only in the stat'),
    '7690a860-a843-4609-8a67-9868b87b32b5': dict(  # potion_lazarus: health+100/t, 300 s
        template='8503216a-a34c-49f0-aefa-54d4502046f9', name='potion_marigold_decoction',
        params=('hod=0',),
        why='Sibling Cpp:PotionHealth potion. The target moved it from the class-exclusive '
            'Hangover class to Potion and spells the hangover cure hod=0'),
    'd0c97def-b9b3-48e7-beab-f46d6bf44d81': dict(  # potion_bivojs_rage, 120 s
        template='940b16f1-d2ef-4874-a915-8122a7d4392a', name='potion_artemisia',
        why='Shipped combat potion of the same class, exclusivity and UI order'),
    '82ea6eb0-d4cb-4216-a1a9-3da1c7ebc488': dict(  # potion_witch: visual only, 300 s
        template='0fc57667-2401-467a-82ec-90c402c22769', name='golden_egg',
        source_fields=('buff_ui_type_id', 'buff_ui_visibility_id'),
        why='Only shipped Potion-class buff with the player_witch effect; the source '
            'shows it as a debuff, the template row is hidden'),
    '3f915710-1ccf-41a0-bc7f-67c8cc1a8e7b': dict(  # potion_tippler: cha-2, 3600 s
        template='fca19318-7d59-4645-bb7d-01fa9e6c925f', name='potion_hair_o_dog',
        source_fields=('implementation', 'buff_ui_type_id'),
        why="Shipped Hair o' the Dog potion. The cure is the body of Cpp:TipplerPotion, "
            'which the target still registers, so the implementation is retained'),
    'f0dc09dd-322b-4d01-824f-677c387e6f76': dict(  # potion_digestive: instant cure
        template='81886e93-8aba-4480-aa3b-d2c0a86447d7', name='potion_antidote',
        source_fields=('implementation', 'buff_class_id'), family=True,
        why='Shipped digestive potion. An instant class-exclusive Food Poison buff in the '
            'FoodPoisoning family is the shape of the shipped remove_all_posions cure'),
    'cdeed798-e09e-45c5-8523-8df75e8791a6': dict(  # potion_wormwood_spirit: str+5,fencing+5
        template='940b16f1-d2ef-4874-a915-8122a7d4392a', name='potion_artemisia',
        why='Same potion: the source UI name of this buff is "Artemisia Potion Effect"'),
    'f405cbea-2a3f-4363-9e6a-23417e4e2a14': dict(  # potion_poison: health-50/t, 25 s
        template='58138b68-0c86-4d5e-8823-417106d08d3c', name='potion_bane',
        why='Sibling poison; the shipped row is the upgraded source potion_bane'),
    '56f66d97-43c6-45d1-a463-05ec76fac01c': dict(  # weapon_poison: health-12/t, 25 s
        template='b56d79e6-156c-4803-8d91-73a82f01926e', name='weapon_bane',
        why='Sibling weapon poison; the shipped row is the upgraded source weapon_bane'),
}
UNPORTED = {
    '1fc6b4cb-cd36-448f-a8ec-9f5513cccbc6':  # potion_preserver
        'Cpp:Instant without params: the freshness restore was item-use code, and no shipped '
        'buff or modifier restores freshness once (perk_art_of_preservation is a permanent '
        'decay rate)',
    '84561de3-32db-4fd2-a5be-db79e40ecf09':  # weapon_witch
        'No params: a screen effect for the drinker only. Coating needs the Poison item '
        'class, which would replace the drinkable potion',
}
NOT_A_POISON = 'Weapon coating exists only on Poison items; the source food subtype is not poison'


def native_buffs(target):
    """The shipped buff rows plus every implementation name the game registers."""
    contract = native_contract(target)
    with zipfile.ZipFile(Path(target) / 'Data/Tables.pak') as archive:
        data = read(archive, 'Libs/Tables/rpg/buff_implementation.xml')
    contract['implementations'] = sorted(
        n.get('buff_implementation_name') for n in ET.fromstring(data).iter('buff_implementation'))
    return contract


def modifier(clause):
    match = re.match(r'\s*([A-Za-z_]\w*)', clause)
    return match[1] if match else None


def translate(params, vocabulary):
    """Respell source modifier names; refuse a modifier the target never uses."""
    result = []
    for part in re.split(r'([,;])', params or ''):
        name = modifier(part)
        if name is not None:
            target = MODIFIER_NAMES.get(name, name)
            if target not in vocabulary:
                raise ValueError('Buff modifier has no native counterpart: ' + name)
            part = part.replace(name, target, 1)
        result.append(part)
    return ''.join(result)


class ItemBuffs:
    def __init__(self, tables, contract, namespace):
        self.tables, self.namespace = tables, identifier(namespace).lower()
        self.native = {}
        for row in contract['records']:
            self.native.setdefault(row.get('buff_id', '').lower(), row)
        self.vocabulary = {modifier(c) for row in contract['records']
                           for c in re.split('[,;]', row.get('buff_params', ''))} - {None}
        self.visuals = {row['visual_effect'] for row in contract['records'] if row.get('visual_effect')}
        self.implementations = set(contract.get('implementations', ())) | {
            row.get('implementation') for row in contract['records']}

    def resolve(self, identity):
        """Describe how one source buff reaches the target; never a partial row."""
        key = identity.lower()
        if key in self.native:
            return dict(source=key, mode='native', target=self.native[key]['buff_id'],
                        target_name=self.native[key].get('buff_name'))
        try:
            source = dict(self.tables.row('rpg/buff', 'buff_id', identity))
        except ValueError:
            return dict(source=key, mode='unported', reason='Missing source buff row')
        described = dict(source=key, source_name=source.get('buff_name'),
                         source_params=source.get('params', ''), source_duration=source.get('duration'),
                         source_implementation=source.get('implementation'))
        if key in UNPORTED or key not in TEMPLATES:
            return dict(described, mode='unported',
                        reason=UNPORTED.get(key, 'No reviewed native buff template'))
        mapping = TEMPLATES[key]
        template = self.native.get(mapping['template'])
        if template is None or template.get('buff_name') != mapping['name']:
            raise ValueError('Native buff template changed: ' + mapping['name'])
        row = {k: template[k] for k in TEMPLATE_FIELDS if template.get(k)}
        if mapping.get('family') and template.get('buff_family_id'):
            row['buff_family_id'] = template['buff_family_id']
        for field in mapping.get('source_fields', ()):
            row.pop(field, None)
            if source.get(field):
                row[field] = source[field]
        if row.get('implementation') not in self.implementations:
            raise ValueError('Unsupported buff implementation: ' + str(row.get('implementation')))
        clauses = [c for c in (translate(source.get('params', ''), self.vocabulary),
                               *mapping.get('params', ())) if c]
        if clauses:
            row['buff_params'] = ','.join(clauses)
        row['duration'] = source['duration']
        dropped = []
        if source.get('visual_effect'):
            if source['visual_effect'] in self.visuals:
                row['visual_effect'] = source['visual_effect']
            else:
                dropped.append('visual_effect=' + source['visual_effect'])
        strings = {field: source[field] for field in sorted(TEXT) if source.get(field)}
        row.update(buff_id=key, buff_name=self.namespace + '_item_buff_' + key.replace('-', ''))
        return dict(described, mode='converted', target=key, template=mapping['template'],
                    template_name=mapping['name'], why=mapping['why'], row=row, strings=strings,
                    source_fields=list(mapping.get('source_fields', ())),
                    added_params=list(mapping.get('params', ())), dropped=dropped,
                    params=row.get('buff_params', ''), duration=row['duration'])

    def file(self, resolved, registered):
        row = dict(resolved['row'])
        for field, text in resolved['strings'].items():
            row[field] = registered[text.lower()]
        root = ET.Element('database', name='barbora')
        ET.SubElement(ET.SubElement(root, 'buffs', version='1'), 'buff', row)
        name = 'Libs/Tables/rpg/buff__' + self.namespace + '_item_' + resolved['source'].replace('-', '') + '.xml'
        return name, xml(root)
