"""Upgrade authored KCD1 fireplaces to native KCD2 player interactions/effects.

The native exported fireplace supplies scripts, animation actions, ladle and
phase-controlled fire/steam/cauldron prefabs. Source anchors supply placement.
Town-specific NPC seating schedules are deliberately not transplanted.
"""
import copy
from collections import Counter
import xml.etree.ElementTree as ET

from campaign_entity_links import append_links
from entity_visuals import initial_layer, world_transform, quaternion_product as qmul
from upgrade_map import read

PREFIX = 'gm_cooking_'
DONORS = {'camp': '16229', 'home': '24041'}
CONTRACT = ("kettleTrigger['kettle']", "kettleTrigger['pan']", 'scoopSlot',
            "proceduralObject['fire']", "proceduralObject['steam']",
            "proceduralObject['cauldron']")


def vector(values):
    return ','.join(format(v, '.9g') for v in values)


def rotate(q, p):
    return qmul(qmul(q, (0, *p)), (q[0], -q[1], -q[2], -q[3]))[1:]


# The native fire prefab's pivot is the base of a log pile. KCD1 fire prefabs
# are flame and light only, so their origin marks the flame base, which the
# authored inset (black kitchen) hearths put about 0.11 m above the hearth top.
# Rest the logs on the surface the fireplace's own pot stands on; never raise.
FIRE_SURFACE_TOLERANCE = 0.01
POT_CATEGORIES = frozenset(('kotlik',))


def pot_surface(owner, pot, entities):
    """Height the fireplace's cooking pot rests on: its pot item, else its cooking trigger."""
    heights = []
    for link in owner.findall('EntityLinks/Link'):
        item = entities.get(link.get('TargetId'))
        if (item is not None and item.get('EntityClass') == 'PickableItem' and item.find('Properties') is not None
                and item.find('Properties').get('sWH_AI_EntityCategory', '').lower() in POT_CATEGORIES):
            heights.append(world_transform(item, entities)[0][2])
    if heights:
        return min(heights)
    return world_transform(pot, entities)[0][2]


def fire_pivot(origin, surface):
    """Lower a flame origin onto the pot surface when it floats above it."""
    if origin[2] - surface > FIRE_SURFACE_TOLERANCE:
        return (origin[0], origin[1], surface)
    return tuple(origin)


def source_trigger(owner, entities, role):
    """The authored interaction trigger a KCD1 fireplace links under `role` (st_kettle, st_fire)."""
    for link in owner.findall('EntityLinks/Link'):
        if link.get('Name') == role:
            target = entities.get(link.get('TargetId'))
            if target is not None and target.get('EntityClass') == 'SequenceTrigger':
                return target
    return None


def cluster_placements(owner, pot, entities):
    """World positions the authored KCD1 hearth dictates for the generated native cluster.

    kettle: the authored pot trigger, which also anchors cauldron, steam and ladle;
    pan: the authored cooking-on-fire trigger (link st_fire), None when the hearth has
    none (the native pan trigger then stays donor-relative);
    fire: the KCD1 flame origin rested on the pot surface, None without a KCD1 flame.
    """
    kettle, _, _ = world_transform(pot, entities)
    fire_trigger = source_trigger(owner, entities, 'st_fire')
    pan = world_transform(fire_trigger, entities)[0] if fire_trigger is not None else None
    effects = [entities[l.get('TargetId')] for l in owner.findall('EntityLinks/Link')
               if l.get('Name', '').startswith('fireProcedural') and l.get('TargetId') in entities]
    fire, lowered = None, 0.0
    if effects:
        origin, _, _ = world_transform(effects[0], entities)
        fire = fire_pivot(origin, pot_surface(owner, pot, entities))
        lowered = origin[2] - fire[2]
    return {'kettle': kettle, 'pan': pan, 'fire': fire, 'fire_lowered_m': lowered, 'effects': effects}


def inventory(source):
    """Inventory every pot, but activate only the same initial layers as visuals."""
    entities, active, origins = {}, set(), {}
    for path in source.namelist():
        main = path.lower() == 'objects_mission0.xml'
        if not main and not (path.lower().startswith('layers/') and path.lower().endswith('.xml')):
            continue
        for entity in ET.fromstring(read(source, path)).iter('Entity'):
            key = entity.get('EntityId')
            entities.setdefault(key, entity)
            origins.setdefault(key, path)
            if (main and not entity.get('Layer')) or initial_layer(entity.get('Layer', '')):
                active.add(key)
    pots, deferred = [], []
    for key, entity in entities.items():
        if entity.find("Properties/Click[@UseMessage='@ui_eat_kettle']") is None:
            continue
        if key not in active:
            deferred.append({'source_id': key, 'layer': entity.get('Layer'), 'archive_entry': origins[key]})
            continue
        owners = [entities[l.get('TargetId')] for l in entity.findall('EntityLinks/Link')
                  if l.get('TargetId') in entities and
                  entities[l.get('TargetId')].get('EntityClass') == 'SmartObjectHolder']
        if len(owners) != 1:
            raise ValueError(f'Cooking pot {key}: expected one fireplace owner, got {len(owners)}')
        owner = owners[0]
        family = owner.find('Properties').get('soclasses_SmartObjectHelpers', '')
        if not family.lower().startswith('fireplace'):
            raise ValueError(f'Unknown fireplace family: {family}')
        pots.append((entity, owner, 'camp' if family.lower() == 'fireplace_camp' else 'home'))
    return entities, sorted(pots, key=lambda row: int(row[0].get('EntityId'))), deferred


def templates(native):
    entities = {e.get('EntityId'): e for e in ET.fromstring(read(native, 'objects_mission0.xml')).iter('Entity')}
    result = {}
    for kind, key in DONORS.items():
        root = entities[key]
        if root.get('EntityClass') != 'FireplaceSmartObject':
            raise ValueError('Native fireplace donor changed')
        links = {l.get('Name'): l.get('TargetId') for l in root.findall('EntityLinks/Link')}
        selected = {key, *(links[name] for name in CONTRACT)}
        nodes = {i: copy.deepcopy(entities[i]) for i in selected}
        for node in nodes.values():
            container = node.find('EntityLinks')
            if container is not None:
                for link in list(container):
                    if link.get('TargetId') not in selected:
                        container.remove(link)
        # Preserve native self modifiers and player-use links, with no dangling
        # scheduler references to Trosky benches, wood stores or reserved dishes.
        result[kind] = (key, nodes, links)
    return result


def convert(files, source, native, guid):
    source_entities, pots, deferred = inventory(source)
    donors = templates(native)
    root = ET.fromstring(files['objects_mission0.xml'])
    if any(e.get('Name', '').startswith(PREFIX) for e in root.iter('Entity')):
        raise ValueError('Cooking pots already installed; use the recorded pre-conversion build')
    next_id = max((int(e.get('EntityId', '0')) for e in root.iter('Entity')), default=0) + 1
    network, records, replaced_visuals = [], [], set()
    for pot, owner, kind in pots:
        source_id = pot.get('EntityId')
        donor_id, originals, links = donors[kind]
        dp, dq, _ = world_transform(originals[donor_id], originals)
        sp, sq, _ = world_transform(owner, source_entities)
        delta = qmul(sq, (dq[0], -dq[1], -dq[2], -dq[3]))
        mapped = {}
        for key in sorted(originals, key=int):
            node = copy.deepcopy(originals[key])
            for attribute in ('Prefab', 'EditorLayer', 'Layer', 'ParentId', 'ParentGuid'):
                node.attrib.pop(attribute, None)
            node.set('EntityId', str(next_id)); next_id += 1
            node.set('EntityGuid', guid(f'cooking/{source_id}/{key}'))
            node.set('Name', f'{PREFIX}{source_id}_{key}')
            p, q, _ = world_transform(originals[key], originals)
            offset = rotate(delta, tuple(p[i] - dp[i] for i in range(3)))
            node.set('Pos', vector(tuple(sp[i] + offset[i] for i in range(3))))
            node.set('Rotate', vector(qmul(delta, q)))
            mapped[key] = node
        # Move pot, ladle and steam together to the authored source pot anchor.
        placements = cluster_placements(owner, pot, source_entities)
        kettle = mapped[links["kettleTrigger['kettle']"]]
        pp = placements['kettle']
        old = tuple(map(float, kettle.get('Pos').split(',')))
        for name in ("kettleTrigger['kettle']", 'scoopSlot', "proceduralObject['steam']", "proceduralObject['cauldron']"):
            node = mapped[links[name]]
            p = tuple(map(float, node.get('Pos').split(',')))
            node.set('Pos', vector(tuple(p[i] + pp[i] - old[i] for i in range(3))))
        # The native cook-on-fire trigger stands where KCD1 players cooked, not
        # where the Trosky donor's hearth happened to put it.
        if placements['pan'] is not None:
            mapped[links["kettleTrigger['pan']"]].set('Pos', vector(placements['pan']))
        source_links = owner.findall('EntityLinks/Link')
        effects = placements['effects']
        fire_position, lowered = placements['fire'], placements['fire_lowered_m']
        if effects:
            mapped[links["proceduralObject['fire']"]].set('Pos', vector(fire_position))
        props = mapped[donor_id].find('Properties')
        props.set('bOwnedByHome', '0')  # No borrowed Trosky home/owner relationship.
        fireplace = props.find('Fireplace')
        if fireplace is None: fireplace = ET.SubElement(props, 'Fireplace')
        fireplace.set('bFullOnInit', '1')
        # Native player_applyBuff consumes one supplied item and applies its
        # ConsumableBuff when present. It does not refill soup from ingredients.
        source_hold = pot.find('Properties/Hold')
        accepted = source_hold.get('InventoryFilter', '') if source_hold is not None else ''
        kettle.find('Properties/Hold').set('InventoryFilter', '|'.join(dict.fromkeys(
            ['poison.*.*'] + [v for v in accepted.split('|') if v])))
        for node in mapped.values():
            for link in node.findall('EntityLinks/Link'):
                target = mapped[link.get('TargetId')]
                link.set('TargetId', target.get('EntityId'))
                link.set('TargetGuid', target.get('EntityGuid'))
                if link.get('Name'):
                    network.append((node.get('EntityGuid'), target.get('EntityGuid'), link.get('Name')))
        if effects:
            fireplace_node = mapped[donor_id]
            ET.SubElement(fireplace_node.find('EntityLinks'), 'Link', Name='forceFireplaceOn',
                          TargetId=fireplace_node.get('EntityId'), TargetGuid=fireplace_node.get('EntityGuid'))
            network.append((fireplace_node.get('EntityGuid'), fireplace_node.get('EntityGuid'), 'forceFireplaceOn'))
        # Replace only ladles connected to this source fireplace, never nearby
        # scenery selected by radius (which could belong to another household).
        for link in source_links:
            slot = source_entities.get(link.get('TargetId'))
            if (slot is not None and slot.get('EntityClass') == 'ItemSlot'
                    and slot.find('Properties') is not None
                    and slot.find('Properties').get('sWH_AI_EntityCategory', '').lower() == 'spoon'):
                for child in slot.findall('EntityLinks/Link'):
                    replaced_visuals.add('glue_item_' + child.get('TargetId'))
        root.extend(mapped.values())
        records.append({'source_pot': source_id, 'source_fireplace': owner.get('EntityId'),
                        'kind': kind, 'position': list(pp), 'native_effects': bool(effects),
                        'fire_position': None if fire_position is None else list(fire_position),
                        'fire_lowered_m': round(lowered, 6),
                        'pan_position': None if placements['pan'] is None else list(placements['pan']),
                        'pan_anchor': 'donor_relative' if placements['pan'] is None else 'source_fire_trigger',
                        'entity_guids': [n.get('EntityGuid') for n in mapped.values()]})
    removed = 0
    for parent in root.iter():
        for node in list(parent):
            if node.get('Name') in replaced_visuals:
                parent.remove(node); removed += 1
    result = dict(files)
    result['objects_mission0.xml'] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    result['waitinglinks.xml'] = append_links(files.get('waitinglinks.xml'), network)
    return result, {'converted': len(records), 'families': dict(Counter(r['kind'] for r in records)),
                    'native_effect_fireplaces': sum(r['native_effects'] for r in records),
                    'replaced_ladle_visuals': removed, 'records': records,
                    'fires_rested_on_pot_surface': sum(1 for r in records if r['fire_lowered_m'] > 0),
                    'pan_triggers_at_source_fire_trigger': sum(1 for r in records if r['pan_anchor'] == 'source_fire_trigger'),
                    'inactive_layer_pots': deferred,
                    'add_item_behavior': 'Consumes one item; applies ConsumableBuff if present; does not refill soup',
                    'npc_schedules': 'Trosky household and bench schedules are not imported'}
