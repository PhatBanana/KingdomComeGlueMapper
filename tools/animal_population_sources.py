"""Read placed fauna and proximity populations from the selected source world."""
import copy
import math
import xml.etree.ElementTree as E

from entity_visuals import initial_entity, world_transform
from upgrade_map import read
from wildlife import PATTERN, SPECIES

PROXIMITY = '4ad419ee-e7d5-d5b9-776b-44a100ec5fbb'
ANIMALS = {**SPECIES, 'Cow': 'animal_cattle_cow', 'Sheep': 'animal_sheep_ewe',
           'Pig': 'animal_pig', 'Dog': 'animal_dog', 'Horse': 'animal_horse'}
FLOCKS = ('Chickens', 'ChickensBrownLight', 'ChickensWhite', 'Birds', 'Fish')


def world(archive, profiles=()):
    """Base/state0 plus explicitly selected profiles; never all quest layers."""
    index = {n.replace('\\', '/').lower(): n for n in archive.namelist()}
    selected = set()
    if profiles:
        definitions = E.fromstring(read(archive, index['whdata_1']))
        for name in profiles:
            matches = [p for p in definitions.iter('GameProfile')
                       if p.findtext('Name', '').lower() == name.lower()]
            if len(matches) != 1:
                raise ValueError('Missing or ambiguous animal world profile: ' + name)
            for layer in matches[0].findall('GameLayers/GameLayer'):
                path = 'layers/' + layer.text.lower() + '.xml'
                if path not in index:
                    raise ValueError('Missing animal profile layer: ' + path)
                selected.add(path)
    entities, active = {}, set()
    for path, actual in index.items():
        main = path == 'objects_mission0.xml'
        if not main and not (path.startswith('layers/') and path.endswith('.xml')):
            continue
        for e in E.fromstring(read(archive, actual)).iter('Entity'):
            if not e.get('EntityClass') or not e.get('EntityId'):
                continue
            key = e.get('EntityId')
            previous = entities.setdefault(key, e)
            if previous.get('EntityGuid') != e.get('EntityGuid'):
                raise ValueError('Conflicting source animal-world entity identity: ' + key)
            if (main and not e.get('Layer')) or initial_entity(e) or path in selected:
                active.add(key)
    return entities, active


def transform(entity, entities):
    result = copy.deepcopy(entity)
    p, q, s = world_transform(entity, entities)
    for key, value in [('Pos', p), ('Rotate', q), ('Scale', s)]:
        result.set(key, ','.join(format(v, '.10g') for v in value))
    for key in ('ParentId', 'ParentGuid', 'Layer', 'EditorLayer', 'Prefab'):
        result.attrib.pop(key, None)
    return result


def populations(entities, active):
    sites, deferred = [], []
    for key, e in entities.items():
        props = e.find('Properties')
        instructions = [l for l in e.findall('EntityLinks/Link')
                        if l.get('Name', '').strip().startswith('animalSpawn[')]
        if not instructions:
            continue
        if key not in active or props is None or props.get('guidSmartObjectType') != PROXIMITY:
            deferred.append(dict(name=e.get('Name'), source_id=key,
                reason='inactive layer' if key not in active else 'regional reference, not a proximity spawner'))
            continue
        if len(instructions) != 1:
            # Existing wildlife conversion already uses the explicit self edge.
            # Do not add a second population from regional alternatives or
            # silently change its established count while adding livestock.
            self_links = [l for l in instructions if l.get('TargetId') == key]
            if len(self_links) != 1:
                raise ValueError('Ambiguous proximity animal population: ' + key)
            deferred.append(dict(name=e.get('Name'), source_id=key,
                reason='retained existing self-edge contract; regional alternatives not summed',
                alternatives=[l.attrib for l in instructions if l is not self_links[0]]))
            instructions = self_links
        link = instructions[0]
        match = PATTERN.fullmatch(link.get('Name').strip())
        if not match or match[2] not in ANIMALS:
            deferred.append(dict(name=e.get('Name'), source_id=key,
                reason='unsupported or malformed source animal instruction',
                definition=link.get('Name'), requires_adapter=True))
            continue
        if link.get('TargetId') not in entities:
            raise ValueError('Missing animal ecosystem dependency: ' + key)
        target = entities[link.get('TargetId')]
        authored_guid = link.get('TargetGuid', '0')
        if authored_guid != '0' and int(authored_guid, 16) != int(target.get('EntityGuid'), 16):
            raise ValueError('Animal ecosystem identity mismatch: ' + key)
        count, species, radius, delay, unit = match.groups()
        pos, _, scale = world_transform(e, entities)
        if (not math.isfinite(float(radius)) or float(radius) < 0
                or float(delay) < 0 or not math.isfinite(float(delay))):
            raise ValueError('Invalid source animal population: ' + key)
        if int(count) == 0 or float(radius) == 0:
            deferred.append(dict(name=e.get('Name'), source_id=key,
                reason='disabled population' if int(count) == 0 else 'point spawn requires a native point-spawn adapter',
                requires_adapter=int(count) != 0))
            continue
        # KCD1 passes radius straight to GetRandomPos in world units. The
        # spawner's transform scale is not multiplied into that radius.
        sites.append(dict(guid=e.get('EntityGuid'), name=e.get('Name'), species=species,
            position=pos, count=int(count), radius=float(radius),
            respawn_days=float(delay)/(24 if unit == 'h' else 1),
            source_id=key, ecosystem=target.get('EntityGuid')))
    if len({s['guid'] for s in sites}) != len(sites):
        raise ValueError('Duplicate source animal population identity')
    return sites, deferred
