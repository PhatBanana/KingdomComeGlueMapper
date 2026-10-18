"""Resolve authored profile actors by persistent identity, never NPC name prefixes.

Collecting a profile is dependency discovery. It does not activate the profile or
spawn its actors; callers must preserve the original activation transition.
"""
import xml.etree.ElementTree as ET


def select(profiles, souls, documents, names):
    """Select placed actors by source soul name, preserving activation ownership.

    Explicit selection is a dependency root, not permission to activate every
    profile containing the actor or another version of the same character.
    """
    requested = set(names)
    if not requested:
        return []
    instances = {}
    for soul in souls.findall('./SoulList/Souls/Soul'):
        name = soul.findtext('Name')
        if name not in requested:
            continue
        if name in instances:
            raise ValueError('Ambiguous selected source actor: ' + name)
        instances[name] = soul
    if requested - instances.keys():
        raise ValueError('Missing selected source actors: ' + ', '.join(sorted(requested - instances.keys())))
    owners = {}
    for profile in profiles.iter('GameProfile'):
        for layer in profile.findall('GameLayers/GameLayer'):
            owners.setdefault('layers/' + layer.text.lower() + '.xml', set()).add(profile.findtext('Name'))
    placements = {}
    for path, blob in documents.items():
        root = blob if isinstance(blob, ET.Element) else ET.fromstring(blob)
        for entity in root.iter('Entity'):
            if entity.get('EntityClass') in ('NPC', 'NPC_Female') and entity.get('EntityGuid'):
                placements.setdefault(int(entity.get('EntityGuid'), 16), []).append((path, entity))
    result = []
    for name, soul in sorted(instances.items()):
        matches = placements.get(int(soul.findtext('EntityGuid')), [])
        if len(matches) != 1 or not soul.findtext('SharedSoulGuid'):
            raise ValueError('Missing or ambiguous selected actor placement: ' + name)
        path, entity = matches[0]
        normalized = path.replace('\\', '/').lower()
        result.append(dict(name=name, soul_id=soul.findtext('SharedSoulGuid'),
            instance_id=soul.findtext('Guid'), entity_guid=entity.get('EntityGuid'),
            source=path, layer=entity.get('Layer', normalized.removeprefix('layers/').removesuffix('.xml')),
            profiles=sorted(owners.get(normalized, ())),
            transform={k: entity.get(k) for k in ('Pos', 'Rotate', 'Scale', 'ParentId') if entity.get(k) is not None}))
    return result


def collect(profiles, souls, documents, names):
    lookup = {}
    for profile in profiles.iter('GameProfile'):
        name = profile.findtext('Name', '').lower()
        if name in lookup:
            raise ValueError('Duplicate source profile: ' + name)
        lookup[name] = profile
    instances = {}
    for soul in souls.findall('./SoulList/Souls/Soul'):
        guid = soul.findtext('EntityGuid')
        if guid:
            key = int(guid)
            if key in instances:
                raise ValueError('Duplicate source actor entity identity: ' + guid)
            instances[key] = soul
    docs = {}
    for path, blob in documents.items():
        key = path.replace('\\', '/').lower()
        if key in docs:
            raise ValueError('Duplicate source world document: ' + key)
        docs[key] = blob
    actors = {}
    for name in sorted(set(n.lower() for n in names)):
        if name not in lookup:
            raise ValueError('Missing source profile: ' + name)
        for layer in lookup[name].findall('GameLayers/GameLayer'):
            path = 'layers/' + layer.text.lower() + '.xml'
            if path not in docs:
                raise ValueError('Missing source profile layer: ' + path)
            document = docs[path]
            root = document if isinstance(document, ET.Element) else ET.fromstring(document)
            for entity in root.iter('Entity'):
                if entity.get('EntityClass') not in ('NPC', 'NPC_Female'):
                    continue
                guid = int(entity.get('EntityGuid', ''), 16)
                soul = instances.get(guid)
                if soul is None or not soul.findtext('SharedSoulGuid'):
                    raise ValueError('Profile actor missing source soul: ' + entity.get('Name', ''))
                record = dict(soul_id=soul.findtext('SharedSoulGuid'),
                              instance_id=soul.findtext('Guid'), entity_guid=entity.get('EntityGuid'),
                              name=soul.findtext('Name'), layer=layer.text, source=path,
                              transform={k: entity.get(k) for k in ('Pos', 'Rotate', 'Scale', 'ParentId')
                                         if entity.get(k) is not None})
                if guid in actors:
                    if {k:v for k,v in actors[guid].items() if k != 'profiles'} != record:
                        raise ValueError('Conflicting profile actor placement: ' + record['name'])
                    actors[guid]['profiles'].append(name)
                else:
                    actors[guid] = dict(record, profiles=[name])
    return sorted(actors.values(), key=lambda r: (r['soul_id'], r['entity_guid']))
