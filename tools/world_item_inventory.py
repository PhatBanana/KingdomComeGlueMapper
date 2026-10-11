"""Authoritative pickup placements, including slot/placed-item deduplication."""
from collections import Counter
from chairs import inventory
from entity_visuals import world_transform


def item_id(properties):
    return properties.get('guidItemClassId', '').strip().lower()


def collect(source):
    entities, placed, inactive = inventory(source, 'PickableItem')
    _, slots, inactive_slots = inventory(source, 'ItemSlot')
    active_ids = {e.get('EntityId') for e in placed}
    candidates, restricted = [], []
    for entity in placed + slots:
        props = entity.find('Properties')
        reason = None
        if props is None: raise ValueError('Missing item properties: '+entity.get('EntityId'))
        if props.get('bOnlyNPC', '0').lower() in ('1', 'true'): reason = 'source_npc_only'
        elif entity.get('EntityClass') == 'ItemSlot':
            if props.get('bSpawnOnStart', '1').lower() in ('0', 'false'): reason = 'source_slot_not_initially_spawned'
            elif any(l.get('Name')=='SlotLink' and l.get('TargetId') in active_ids for l in entity.findall('EntityLinks/Link')):
                reason = 'slot_has_placed_item'
        if reason:
            restricted.append(dict(source_id=entity.get('EntityId'), reason=reason));continue
        pos, rot, scale = world_transform(entity, entities)
        candidates.append(dict(entity=entity, item_id=item_id(props), position=pos, rotation=rot, scale=scale))
    return entities, candidates, dict(active_placed_items=len(placed), active_slots=len(slots),
        inactive=inactive+inactive_slots, restrictions=restricted,
        restriction_counts=dict(Counter(r['reason'] for r in restricted)))
