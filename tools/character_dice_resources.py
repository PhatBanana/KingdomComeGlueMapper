"""Build a native dice resource graph at authored source contact poses.

This module creates a staged graph, not an enabled actor schedule. Its caller
must register native decisions, scheduler ownership and source money policy.
"""
import copy
import hashlib
import xml.etree.ElementTree as E

from campaign_entity_links import native_guid, guid_value
from cooking_pots import rotate, vector
from entity_visuals import quaternion_product, world_transform

TABLE_TEMPLATE = '9a3317b0-9c92-466e-bab6-571f23356bca'
SEAT_TEMPLATE = '57cbebae-c19a-443b-8945-999d8ee87955'
EXACT = ('table', 'seat1_SO', 'seat2_SO', 'cupSlot1', 'cupSlot2',
         'hiddenSlot1', 'hiddenSlot2', 'dice_cup', 'kibitzerPlace')
REQUIRED = set(EXACT) | {'interactor', 'seat1', 'seat2', 'hiddenDiceOnTable1',
    'hiddenDiceOnTable2', 'diceOnTable1', 'diceOnTable2', 'dice_z_coord',
    'badge_tagpoint_player', 'badge_tagpoint_opponent',
    'badge_tagpoint_closeup_player_1', 'badge_tagpoint_closeup_opponent_1'}


def linked(entity, entities, name):
    links = [l for l in entity.findall('EntityLinks/Link') if l.get('Name') == name]
    if len(links) != 1 or links[0].get('TargetId') not in entities:
        raise ValueError('Missing or ambiguous dice resource: '+name)
    return entities[links[0].get('TargetId')]


def source_roles(table, entities):
    """Resolve source seat-owned cup slots; table hiddenSlot order is ambiguous."""
    roles = dict(table=table)
    for side in ('1', '2'):
        seat = linked(table, entities, 'seat'+side)
        roles['seat'+side+'_SO'] = seat
        roles['cupSlot'+side] = linked(seat, entities, 'cupOnTable')
        roles['hiddenSlot'+side] = linked(seat, entities, 'cupStash')
    for name in ('dice_cup', 'kibitzerPlace'):
        roles[name] = linked(table, entities, name)
    return roles


def native_roles(table, entities):
    if table.find('Properties') is None or table.find('Properties').get('guidSmartObjectType') != TABLE_TEMPLATE:
        raise ValueError('Unsupported native dice table template')
    roles = {'table': table}
    for name in REQUIRED - {'table'}:
        roles[name] = linked(table, entities, name)
    for side, role in [('1', '_opponent|,use'), ('2', '_challenger|,use')]:
        seat = roles['seat'+side+'_SO']
        if (linked(table, entities, role) is not seat or seat.find('Properties') is None
                or seat.find('Properties').get('guidSmartObjectType') != SEAT_TEMPLATE):
            raise ValueError('Native dice opponent/challenger ownership changed')
        for tag, resource in [('cupStash', 'hiddenSlot'), ('cupOnTable', 'cupSlot'),
                              ('cupSlot', 'cupSlot'), ('hiddenSlot', 'hiddenSlot'),
                              ('hiddenDiceOnTable', 'hiddenDiceOnTable'), ('diceOnTable', 'diceOnTable')]:
            if linked(seat, entities, tag) is not roles[resource+side]:
                raise ValueError('Native dice seat resource ownership changed')
    return roles


def relative_pose(point, native_anchor, source_anchor, native_entities, source_entities):
    pos, rot, scale = world_transform(point, native_entities)
    old, oq, os = world_transform(native_anchor, native_entities)
    new, nq, ns = world_transform(source_anchor, source_entities)
    if any(abs(v-1) > 1e-5 for v in scale+os+ns):
        raise ValueError('Scaled dice resource needs explicit geometry conversion')
    inverse = (oq[0], -oq[1], -oq[2], -oq[3])
    delta = quaternion_product(nq, inverse)
    offset = rotate(delta, tuple(a-b for a, b in zip(pos, old)))
    return tuple(a+b for a, b in zip(new, offset)), quaternion_product(delta, rot)


def build(source_table, source_entities, native_table, native_entities, first_id, source_helpers):
    """Return a closed native graph; every new contact derives from a donor.

    Source-owned seat, cup and stash contacts are exact. Native-only dice/badge
    helpers retain offsets relative to their corresponding cup, never a guessed
    map coordinate or a whole-table rescale.
    """
    source = source_roles(source_table, source_entities)
    source_entities=dict(source_entities)
    # As in the existing bench converter, source holders are not themselves
    # the sitting contact: the authored Category(Sit) helper supplies it.
    from character_fence_work import placement
    for role in ('seat1_SO','seat2_SO'):
        seat=source[role]
        family=seat.find('Properties').get('soclasses_SmartObjectHelpers','')
        places=[h for h in source_helpers.findall('Helper') if h.get('className')==family
                and 'Category(Sit)' in h.get('description','')]
        if len(places)!=1:raise ValueError('Dice seat needs one authored sitting helper')
        pos,rot,scale=world_transform(seat,source_entities)
        contact=E.Element('Entity',dict(seat.attrib,Pos=vector(pos),Rotate=vector(rot),Scale=vector(scale)))
        contact.attrib.pop('ParentId',None);contact.attrib.pop('ParentGuid',None)
        contact.attrib=placement(contact,places[0])
        source[role]=contact
    donor = native_roles(native_table, native_entities)
    unique = {e.get('EntityId'): e for e in donor.values()}
    # A donor may have additional external gameplay links. Never copy those.
    for entity in unique.values():
        for link in entity.findall('EntityLinks/Link'):
            if link.get('TargetId') not in unique:
                raise ValueError('Native dice donor has external ownership: '+link.get('Name', ''))
    names = {e.get('EntityId'): name for name, e in donor.items()}
    identities = {}
    for index, key in enumerate(sorted(unique, key=int)):
        role = names[key]
        digest = hashlib.sha256(('dice-resource/'+source_table.get('EntityGuid')+'/'+role).encode()).digest()
        identities[key] = str(first_id+index), native_guid(int.from_bytes(digest[:8], 'little'))
    result = []
    for key in sorted(unique, key=int):
        entity = unique[key]; name = names[key]
        if name in EXACT:
            anchor = name
        elif name in ('seat1', 'seat2'):
            anchor = name+'_SO'
        elif name.endswith('1') and name.startswith(('hiddenDice', 'diceOn')):
            anchor = 'cupSlot1'
        elif name.endswith('2') and name.startswith(('hiddenDice', 'diceOn')):
            anchor = 'cupSlot2'
        else:
            anchor = 'dice_cup'
        pos, rot = relative_pose(entity, donor[anchor], source[anchor], native_entities, source_entities)
        item = copy.deepcopy(entity)
        item.attrib = {k:v for k,v in item.attrib.items() if k not in
                       ('ParentId', 'ParentGuid', 'Prefab', 'EditorLayer', 'Layer', 'Scale')}
        item.set('EntityId', identities[key][0]); item.set('EntityGuid', identities[key][1])
        item.set('Name', 'gm_dice_'+source_table.get('EntityId')+'_'+name)
        item.set('Pos', vector(pos)); item.set('Rotate', vector(rot))
        for link in item.findall('EntityLinks/Link'):
            # This is the donor quest's activation state, not table geometry
            # or ownership. The converted source controller owns availability.
            if name=='table' and link.get('Name')=='dice_disabledMinigame' and link.get('TargetId')==key:
                item.find('EntityLinks').remove(link)
                continue
            target = identities[link.get('TargetId')]
            link.set('TargetId', target[0]); link.set('TargetGuid', target[1])
        result.append(item)
    return result


def scheduler_rows(source_table, converted, native_table, native_entities, scheduler):
    """Copy native role-filtered table ownership and exclusive seat terminals."""
    roles=native_roles(native_table,native_entities)
    generated={e.get('Name'):e for e in converted}
    mapping={}
    for role in ('table','seat1_SO','seat2_SO'):
        name='gm_dice_'+source_table.get('EntityId')+'_'+role
        if name not in generated:raise ValueError('Missing converted dice scheduler resource')
        mapping[str(guid_value(roles[role].get('EntityGuid')))]=str(guid_value(generated[name].get('EntityGuid')))
    result=[]
    for role in ('table','seat1_SO','seat2_SO'):
        key=str(guid_value(roles[role].get('EntityGuid')))
        rows=[r for r in scheduler.find('Schedulers') if r.get('EntityGuid')==key]
        if len(rows)!=1 or rows[0].tag!='C_SmartHub':raise ValueError('Missing native dice scheduler ownership')
        row=copy.deepcopy(rows[0])
        if role!='table' and len(row):raise ValueError('Native dice seat is not exclusive terminal')
        if role=='table':
            links=row.findall('Links/S_ActivityLink')
            if len(links)!=2 or {l.find('Parameters').get('RequiredRole') for l in links}!={'opponent','challenger'}:
                raise ValueError('Native dice role ownership changed')
        row.set('EntityGuid',mapping[key])
        for link in row.findall('Links/S_ActivityLink'):
            if link.get('TargetGuid') not in mapping or link.get('PositioningDelegate')!='0':
                raise ValueError('Native dice scheduler has external delegation')
            link.set('TargetGuid',mapping[link.get('TargetGuid')])
        result.append(row)
    return result
