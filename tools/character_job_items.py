"""Source job tools bound to native scheduler reservations and pickup helpers.

The job owns a reservation, not a duplicate inventory item. Native scheduling
collects/returns the item through its ItemSlot and interrupts the hand action.
"""
import copy
import hashlib
import re
import xml.etree.ElementTree as ET
from campaign_entity_links import native_guid
from entity_visuals import world_transform
from world_item_placements import placement_transform


RESERVATION = re.compile(r"schedulerReservedItem\['([^']+)','([^']+)'\]")


def reservation_contract(job, entities):
    """Read the shipped job's item decisions, slots and pickup helper contract."""
    result = []
    for link in job.findall('EntityLinks/Link'):
        match = RESERVATION.fullmatch(link.get('Name', ''))
        if not match: continue
        point = entities[link.get('TargetId')]
        targets = [entities[l.get('TargetId')] for l in point.findall('EntityLinks/Link')
                   if not l.get('Name')]
        if point.get('EntityClass') != 'TagPoint' or len(targets) != 1:
            raise ValueError('Unsupported native job reservation graph')
        slot = targets[0]
        if slot.get('EntityClass') != 'ItemSlot': raise ValueError('Reservation is not an item slot')
        props = slot.find('Properties')
        if props is None or not props.get('guidItemClassId'):
            raise ValueError('Native job item is missing its item definition')
        result.append(dict(behavior=match[1], decision=match[2], definition=link.get('Name'),
            item_id=props.get('guidItemClassId').lower(), properties=copy.deepcopy(props),
            direct_links=[l.get('Name') for l in job.findall('EntityLinks/Link')
                          if l.get('TargetId') == slot.get('EntityId')]))
    if not result: raise ValueError('Native job has no item reservation contract')
    return result


def register_item(mission, source_slot, source_entities, contract, registered_items):
    """Promote/reuse the authored tool once, preserving source placement.

An already imported player pickup is reused. A visual-only NPC tool becomes
an ItemSlot; its old decorative mesh is removed, never left as a second broom.
All item definitions must resolve through the importer's item registry first.
"""
    props = source_slot.find('Properties')
    item_id = props.get('guidItemClassId', '').lower()
    if source_slot.get('EntityClass') != 'ItemSlot' or item_id != contract['item_id']:
        raise ValueError('Source tool does not match native job item contract')
    if item_id not in registered_items: raise ValueError('Unregistered job item: ' + item_id)
    placed = [source_entities[l.get('TargetId')] for l in source_slot.findall('EntityLinks/Link')
              if l.get('Name') == 'SlotLink' and l.get('TargetId') in source_entities]
    if len(placed) > 1: raise ValueError('Ambiguous authored job item')
    if placed and (placed[0].get('EntityClass') != 'PickableItem' or
                   placed[0].find('Properties').get('guidItemClassId', '').lower() != item_id):
        raise ValueError('Job slot and placed item disagree')
    source = placed[0] if placed else source_slot
    source_ids = {source_slot.get('EntityId'), source.get('EntityId')}
    guids = {native_guid(int(e.get('EntityGuid'),16)) for e in (source_slot,source)}
    existing = [e for e in mission if e.get('EntityGuid') in guids]
    if len(existing) > 1: raise ValueError('Duplicated existing job tool')
    if existing:
        slot = existing[0]
        if slot.get('EntityClass') != 'ItemSlot' or slot.find('Properties').get('guidItemClassId') != registered_items[item_id]:
            raise ValueError('Existing job tool identity has incompatible content')
    else:
        pos, rot, scale = world_transform(source, source_entities)
        pos, rot, scale = placement_transform(dict(entity=source,position=pos,rotation=rot,scale=scale))
        vec = lambda v: ','.join(format(x,'.10g') for x in v)
        slot = ET.SubElement(mission, 'Entity', Name='gm_job_item_'+source_slot.get('EntityGuid').lower(),
            EntityClass='ItemSlot', EntityGuid=native_guid(int(source_slot.get('EntityGuid'),16)),
            EntityId=str(max(int(e.get('EntityId','0')) for e in mission)+1),
            Pos=vec(pos), Rotate=vec(rot), Scale=vec(scale), CastShadowMinSpec='1')
        ET.SubElement(slot, 'Properties', guidItemClassId=registered_items[item_id],
            bSpawnOnStart=props.get('bSpawnOnStart','1'), bSaveBorrowedItem='1',
            bOnlyNPC=source.find('Properties').get('bOnlyNPC','0'),
            bHasItemPhysics='0', bOwnedByHome='0', nRestockPeriodDays='0', nDestockPeriodDays='0')
    target_props = slot.find('Properties')
    # The native manipulation tag selects the pickup/place variant (including
    # left-handed variants). Helpers and the template alone do not preserve it.
    for field in ('soclass_SmartObjectHelpers','guidSmartObjectType','sManipulationAnimTag'):
        value = contract['properties'].get(field)
        if value: target_props.set(field, value)
        else: target_props.attrib.pop(field, None)
    removed = []
    for e in list(mission):
        if e.get('Name') in {'glue_item_'+i for i in source_ids}:
            removed.append(e.get('Name')); mission.remove(e)
    return slot, dict(source_slot=source_slot.get('EntityGuid'), item_id=item_id,
        registered_item=registered_items[item_id], slot=slot.get('EntityGuid'),
        helper=target_props.get('soclass_SmartObjectHelpers'),
        manipulation_tag=target_props.get('sManipulationAnimTag',''), removed_visuals=removed)


def bind_reservation(mission, job, slot, contract):
    """Instantiate the generic job -> reservation point -> tool graph."""
    identity='job-reservation/'+job.get('EntityGuid')+'/'+contract['decision']
    # One reservation candidate points at exactly one slot. Distinct source
    # tools must not collapse into a point with ambiguous unlabelled targets.
    identity += '/' + slot.get('EntityGuid')
    guid=native_guid(int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8],'little'))
    point=next((e for e in mission if e.get('EntityGuid')==guid),None)
    if point is None:
        point=ET.SubElement(mission,'Entity',Name='gm_job_reservation_'+guid,EntityClass='TagPoint',
            EntityGuid=guid,EntityId=str(max(int(e.get('EntityId','0')) for e in mission)+1),Pos=job.get('Pos'))
        ET.SubElement(point,'Properties',bSaved_by_game='0')
    links=[]
    def connect(a,b,name):
        container=a.find('EntityLinks')
        if container is None:container=ET.SubElement(a,'EntityLinks')
        if not any(l.get('TargetId')==b.get('EntityId') and l.get('Name')==name for l in container):
            ET.SubElement(container,'Link',TargetId=b.get('EntityId'),TargetGuid=b.get('EntityGuid'),Name=name)
        links.append((a.get('EntityGuid'),b.get('EntityGuid'),name))
    connect(job,point,contract['definition'])
    connect(point,slot,'')
    for name in contract['direct_links']:connect(job,slot,name)
    return links
