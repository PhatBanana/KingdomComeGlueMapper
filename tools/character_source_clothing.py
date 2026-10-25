"""Source outfit identity and native female garment registration.

Policies are keyed by authored body part/layer, never actor or quest names.
The source's numeric archetype IDs are not portable between the games.
"""
import copy
from pathlib import PurePosixPath
import re
import uuid
import xml.etree.ElementTree as ET


def garment_layout(part):
    name = PurePosixPath(part['model'].replace('\\', '/')).stem
    match = re.match(r's([12])_p([1-4])_l(\d+)_', name, re.I)
    if not match:
        raise ValueError('Unsupported source garment layout: ' + name)
    sex, region, layer = map(int, match.groups())
    return sex, region, layer


def female_role(part, tables=None):
    if tables is None:
        sex, region, _ = garment_layout(part)
    else:
        sex = int(part['gender_id'])
        equipment = {r['equipment_part_id']: r['equipment_part_name'] for r in tables.get('item/equipment_part')['rows']}
        subparts = {r['body_subpart_id']: equipment[r['equipment_part_id']] for r in tables.get('item/body_subpart')['rows']}
        covered = {subparts[r['body_subpart_id']] for r in tables.get('item/armor_archetype2body_subpart')['rows']
                   if r['armor_archetype_id'] == part['armor_archetype_id']}
        # A full dress also spans arms/legs. Its torso occupancy defines the
        # visual family, including source meshes without modular filenames.
        if 'torso' in covered and covered <= {'torso', 'waist', 'arms', 'legs'}:
            region = 2
        elif covered == {'head'}:
            region = 1
        elif covered == {'feet'}:
            region = 4
        else:
            raise ValueError('No native female clothing family for source equipment regions: ' + str(sorted(covered)))
    if sex != 2:
        raise ValueError('Female garment policy requires a female source mesh')
    # Match the native female equipment roles; retain the complete source dress
    # instead of applying the male torso/waist/sleeve partition to its skirt.
    # This selects only the visual family. Equipment occupancy and layer come
    # from the source archetype's counterpart in the installed native tables.
    roles = {1: ('F_Veil', 'head'), 2: ('F_SimpleDress', 'torso'),
             4: ('F_Shoes', 'feet')}
    if region not in roles:
        raise ValueError('No native female clothing role for source part ' + str(region))
    return roles[region]


_ROLES = {}


def native_role(components, items, armor_type):
    """Resolve inherited archetype and a complete item template by clothing role.

    Both trees are native tables read once per import and never edited, so the
    result is memoized: the walk over every component took 30 ms per wearable
    item. The entry keeps the trees alive, so their ids cannot be reused.
    """
    key = (id(components), id(items), armor_type)
    cached = _ROLES.get(key)
    if cached is None or cached[0] is not components or cached[1] is not items:
        cached = _ROLES[key] = (components, items, _native_role(components, items, armor_type))
    return cached[2]


def _native_role(components, items, armor_type):
    parents = {c: p for p in components.iter() for c in p}
    candidates = [n for n in components.iter('Clothing')
                  if n.get('Name') == armor_type and n.get('ArmorType') == armor_type]
    if len(candidates) != 1:
        raise ValueError('Missing or ambiguous native clothing role: ' + armor_type)
    node = candidates[0]
    while not node.get('ArmorArchetypeId'):
        node = parents[node]
    archetype = node.get('ArmorArchetypeId')
    compatible = set()
    for child in components.iter('Clothing'):
        ancestor = child
        while ancestor in parents and not ancestor.get('ArmorType'):
            ancestor = parents[ancestor]
        if ancestor.get('ArmorType') == armor_type:
            compatible.add(child.get('Name'))
    template = next((n for n in items.iter() if n.tag in ('Armor', 'Helmet', 'Hood') and n.get('Clothing') in compatible), None)
    if template is None:
        raise ValueError('No complete native item template for ' + armor_type)
    return archetype, template


def source_item(tables, source_id, namespace, component, template, source_strings):
    """Retain source item identity, name, description, value and armour stats."""
    rows = {name: tables.row('item/' + name, 'item_id', source_id)
            for name in ('item', 'armor', 'player_item', 'pickable_item', 'equippable_item')}
    result = copy.deepcopy(template)
    result.attrib.update(Id=str(uuid.uuid5(uuid.NAMESPACE_URL, 'gluemapper/person/' + namespace + '/item/' + source_id)),
                         Name=namespace + '_' + rows['item']['item_name'], Clothing=component)
    mapping = {
        'pickable_item': {'weight': 'Weight', 'price': 'Price', 'owner_fading_coef': 'FadeCoef', 'visibility_coef': 'VisibilityCoef'},
        'armor': {'max_status': 'MaxStatus', 'noise': 'Noise', 'str_req': 'StrReq',
                  'stab_def': 'DefenseStab', 'slash_def': 'DefenseSlash', 'smash_def': 'DefenseSmash'},
        'equippable_item': {'charisma': 'Charisma', 'social_class_id': 'SocialClassId', 'wealth_level': 'WealthLevel'},
    }
    for table, fields in mapping.items():
        for old, new in fields.items():
            if rows[table].get(old) not in ('', None):
                result.set(new, rows[table][old])
    localized = ET.Element('Table')
    for old, new in [('ui_name', 'UIName'), ('ui_info', 'UIInfo')]:
        key = rows['player_item'].get(old)
        if not key:
            raise ValueError('Source clothing has no ' + old + ': ' + source_id)
        matches = [r for r in source_strings.findall('Row') if (r.findtext('Cell') or '').lower() == key.lower()]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous source clothing text: ' + key)
        row = copy.deepcopy(matches[0]); row.find('Cell').text = namespace + '_' + key
        localized.append(row); result.set(new, row.findtext('Cell'))
    return result, localized
