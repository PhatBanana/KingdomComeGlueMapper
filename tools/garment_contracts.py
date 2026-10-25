"""Translate source garment archetypes into native equipment roles."""
from character_source_clothing import female_role


def clothing_role(tables, armor, part):
    if part.get('gender_id') == '2': return female_role(part, tables)[0]
    name = tables.row('item/armor_archetype', 'armor_archetype_id', part['armor_archetype_id'])['armor_archetype_name']
    exact = {'HeadClothCap':'Cap', 'HeadClothFullMask':'CoifLarge', 'HeadChainCap':'CoifMail',
        'HeadChainCap_collarOnly':'CollarMail', 'HeadChainCap_withCollar':'CoifMail',
        'HeadClothCap_withCollar':'CoifLarge', 'HandsGloves':'Gauntlets' if armor['armor_type_id']=='5' else 'Gloves',
        'HandsGlovesPlate_toBeDeleted':'Gauntlets', 'FeetBoots':'BootsAnkle',
        'Tmp_HoodOn':'Hood', 'Tmp_HoodDown':'Hood', 'Robe':'Habit', 'Robe_cape':'Coat',
        'Ring':'Ring', 'Necklace':'Necklace', 'Spur':'Spurs', 'HorseShoe':'HorseShoe',
        'HorseSaddle':'Saddle', 'HorseBridle':'Bridle', 'HorseTrappingsFull':'Caparison',
        'HorseArmorHeadNeck':'Bridle', '_UPPER_BODY_4':'Waffenrock', '_HEAD':'Cap'}
    if name in exact: return exact[name]
    for prefix, role in [('BodyPlate','Cuirass'), ('BodyChain','MailShort'), ('ArmsPlate','ArmPlate'),
                         ('HeadPlateHat','KettleHat'), ('HeadPlateHelmOpen','BascinetOpen'),
                         ('HeadPlateHelmFull','BascinetVisor'), ('LegsCloth','HoseJoined'),
                         ('LegsChain','LegsChain'), ('LegsPlate','LegsPlate'), ('BodyDecor','Waffenrock')]:
        if name.startswith(prefix): return role
    if name.startswith('BodyCloth'):
        if armor['armor_type_id'] in ('2','3'): return 'GambesonLong' if 'Long' in name else 'GambesonShort'
        return 'TunicLong' if 'Long' in name else 'TunicShort'
    raise ValueError('Unmapped source garment archetype: '+name)


def source_variant(requested, available):
    """Resolve case differences; missing authored deltas leave the base mesh.

    Never substitute a different variant. Return the unresolved source request
    for the report when a shipped table names a morph absent from its mesh.
    """
    if not requested: return None, None
    matches = [name for name in available if name.casefold() == requested.casefold()]
    if len(matches) > 1: raise ValueError('Ambiguous source garment variant: '+requested)
    return (matches[0], None) if matches else (None, requested)
