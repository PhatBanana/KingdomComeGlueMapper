"""Shared source-person identity, native soul, appearance and world registration.

Quest and shop adapters select a person; this helper does not select a quest,
merchant, gender, body or coordinates on their behalf.
"""
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from campaign_dependency_adapters import SourceTables
from campaign_sources import RetailSourceReader
from campaign_entity_links import native_guid
from upgrade_map import archive_signature, read, xml
from character_person_ai import (capture_person_ai, native_brain_and_class,
                               stat_operations, apply_person_properties, receipt, register_factions)
from shared_xml import parse as parse_shared


def native_xml(blob):
    return ET.fromstring(re.sub(rb'<!--.*?-->', b'', blob, flags=re.S))


_NATIVE_TABLES = {}


def native_table(archive, name):
    """native_xml of one member of an unchanged archive, parsed once per build.

    The KCD2 component and item tables (4.7 and 2 MB) are parsed for every
    converted person and only ever read: native_role and source_item copy what
    they keep. Sharing the trees also lets native_role's memo hit. In-memory
    archives are parsed each time.
    """
    key = archive_signature(archive)
    if key is None:
        return native_xml(read(archive, name))
    if any(k[0] != key for k in _NATIVE_TABLES):
        _NATIVE_TABLES.clear()  # one game installation per build
    if (key, name) not in _NATIVE_TABLES:
        _NATIVE_TABLES[(key, name)] = native_xml(read(archive, name))
    return _NATIVE_TABLES[(key, name)]


def unique(values, label):
    values = list(values)
    if len(values) != 1:
        raise ValueError(f'Expected one {label}, found {len(values)}')
    return values[0]


_LAYER_INDEX = {}


def layer_entity_index(archive):
    """EntityId -> layer entries holding it, built once per unchanged source level archive.

    Person resolvers call resolve_link_targets a few hundred times per build on
    the same level; without this each call reads every layer file again.
    """
    def build():
        index = {}
        for entry in archive.namelist():
            normalized = entry.replace('\\', '/').lower()
            if not normalized.startswith('layers/') or not normalized.endswith('.xml'):
                continue
            for entity in parse_shared(read(archive, entry)).iter('Entity'):
                index.setdefault(entity.get('EntityId'), set()).add(entry)
        return index
    if not isinstance(archive.filename, str):
        return build()
    path = Path(archive.filename).resolve()
    stat = path.stat()
    signature = (path, stat.st_size, stat.st_mtime_ns)
    if signature not in _LAYER_INDEX:
        _LAYER_INDEX[signature] = build()
    return _LAYER_INDEX[signature]


_SOURCE_ENTITIES = {}


def source_entities(archive):
    """Every Entity of the archive's objects_mission0.xml, parsed once per unchanged archive.

    Schedule and merchant resolution read the 50 MB source mission for every
    person. The elements are shared: read them and deep-copy what you keep, as
    world_entity does. In-memory archives are parsed each time.
    """
    key = archive_signature(archive)
    if key is None:
        return list(ET.fromstring(read(archive, 'objects_mission0.xml')).iter('Entity'))
    if key not in _SOURCE_ENTITIES:
        _SOURCE_ENTITIES.clear()  # one source level per build
        _SOURCE_ENTITIES[key] = list(ET.fromstring(read(archive, 'objects_mission0.xml')).iter('Entity'))
    return list(_SOURCE_ENTITIES[key])


def resolve_link_targets(archive, actor, entities, provenance):
    """Resolve direct authored NPC links even when targets live in other layers."""
    required = {link.get('TargetId') for link in actor.findall('EntityLinks/Link')}
    if any(not identity for identity in required):
        raise ValueError('Source person link has no target identity')
    counts = Counter(e.get('EntityId') for e in entities)
    for identity in required:
        if counts[identity] > 1:
            raise ValueError('Ambiguous source person link target: ' + identity)
    known = {e.get('EntityId') for e in entities}
    missing = required - known
    if not missing:
        return entities
    found = {}
    holders = layer_entity_index(archive)
    entries = set().union(*(holders.get(identity, ()) for identity in missing))
    for entry in archive.namelist():
        if entry not in entries:
            continue
        blob = read(archive, entry)
        # Fresh elements: callers may edit the targets this returns.
        for entity in ET.fromstring(blob).iter('Entity'):
            identity = entity.get('EntityId')
            if identity not in missing:
                continue
            if identity in found:
                raise ValueError('Ambiguous source person link target: ' + identity)
            found[identity] = entity
            provenance[entry] = hashlib.sha256(blob).hexdigest()
    unresolved = missing - found.keys()
    if unresolved:
        raise ValueError('Unresolved source person link targets: ' + ', '.join(sorted(unresolved)))
    return [*entities, *(found[key] for key in sorted(found))]


def world_entity(archive, entity, entities, provenance=None):
    """Detach an authored entity only after resolving its complete parent chain.

    Job holders are published without their source prefab parents. Their Pos
    and Rotate must therefore be world transforms, including cross-layer parents.
    Keep unparented values verbatim and never mutate the source graph.
    """
    from entity_visuals import world_transform
    provenance = provenance if provenance is not None else {}
    # One pass over the (often 66,000-entity) world: callers resolve hundreds of
    # placements, and each used to scan it five times per parent level.
    by_id, counts = {}, Counter()
    def know(candidate):
        identity = candidate.get('EntityId')
        by_id[identity] = candidate; counts[identity] += 1
    for candidate in entities:
        know(candidate)
    if entity.get('EntityId') not in counts:
        know(entity)
    cursor, seen = entity, set()
    while cursor.get('ParentId'):
        identity = cursor.get('EntityId')
        if identity in seen:
            raise ValueError('Parent cycle in source activity placement')
        seen.add(identity)
        parent = cursor.get('ParentId')
        if counts[parent] > 1:
            raise ValueError('Ambiguous source person link target: ' + parent)
        if not counts[parent]:
            # Not in the given world: find it in the source layers, as resolve_link_targets does.
            request = ET.Element('Entity')
            ET.SubElement(ET.SubElement(request, 'EntityLinks'), 'Link', TargetId=parent)
            for found in resolve_link_targets(archive, request, [], provenance):
                know(found)
        cursor = by_id[parent]
    pos, rot, scale = world_transform(entity, by_id)
    result = copy.deepcopy(entity)
    if entity.get('ParentId'):
        for field, values in (('Pos', pos), ('Rotate', rot), ('Scale', scale)):
            result.set(field, ','.join(format(v, '.10g') for v in values))
    for field in ('ParentId', 'ParentGuid'):
        result.attrib.pop(field, None)
    return result


_SOURCE_DOCUMENTS = {}


def _source_document(archive, kind):
    """The mission's SHA-256 or the parsed whdata_0 souls, once per unchanged archive (one kept of each)."""
    def build():
        if kind == 'mission_sha256':
            return hashlib.sha256(read(archive, 'objects_mission0.xml')).hexdigest()
        return ET.fromstring(read(archive, 'whdata_0')).findall('./SoulList/Souls/Soul')
    key = archive_signature(archive)
    if key is None:
        return build()
    if _SOURCE_DOCUMENTS.get(kind, (None,))[0] != key:
        _SOURCE_DOCUMENTS[kind] = (key, build())
    return _SOURCE_DOCUMENTS[kind][1]


def resolve_person(source, name, level='rataje', *, include_ai=True):
    """The source person's soul, actor and instance; actor and instance are the caller's own copies.

    Each person used to parse the 52 MB source mission and 16 MB whdata_0 again.
    Both are now shared, read-only, through source_entities and _source_document.
    """
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        soul = tables.row('rpg/soul', 'soul_name', name)
        evidence = {k: v['provenance'] for k, v in tables.cache.items()}
    with zipfile.ZipFile(Path(source) / 'Data/Levels' / level / 'level.pak') as archive:
        mission_sha256 = _source_document(archive, 'mission_sha256')
        actor_sources = {'objects_mission0.xml': mission_sha256}
        entities = source_entities(archive)
        if not any(e.get('Name') == name for e in entities):
            for entry in archive.namelist():
                if entry.lower().startswith('layers/') and entry.lower().endswith('.xml'):
                    blob = read(archive, entry)
                    if name.encode('utf-8') in blob:
                        layer_entities = list(parse_shared(blob).iter('Entity'))
                        entities.extend(layer_entities)
                        if any(e.get('Name') == name for e in layer_entities):
                            actor_sources[entry] = hashlib.sha256(blob).hexdigest()
        actor = unique((e for e in entities if e.get('Name') == name and
                        e.get('EntityClass') in ('NPC', 'NPC_Female')), 'source person')
        if include_ai:
            entities = resolve_link_targets(archive, actor, entities, actor_sources)
        instance = unique((s for s in _source_document(archive, 'souls')
                           if s.findtext('Name') == name), 'source person instance')
    if instance.findtext('SharedSoulGuid') != soul['soul_id']:
        raise ValueError('Source person instance/table identity differs')
    ai = None
    if include_ai:
        with RetailSourceReader(source) as reader:
            tables = SourceTables(source, reader)
            ai = capture_person_ai(tables, soul, actor, instance, entities)
            evidence.update({k: v['provenance'] for k, v in tables.cache.items()})
    return dict(name=name, soul=soul, actor=copy.deepcopy(actor), instance=copy.deepcopy(instance), source_level=level,
                ai=ai,
                provenance=dict(tables=evidence, mission_sha256=mission_sha256,
                                actor_sources=actor_sources))


def register_person(add_entity, wh, person, placement=None):
    """Preserve source soul/instance identity, using the converted entity GUID."""
    actor = person['actor']
    pose = placement if placement is not None else actor
    souls = wh.find('./SoulList/Souls')
    if souls is None:
        raise ValueError('Destination requires a native SoulList')
    identity = person['instance'].findtext('Guid')
    if any(s.findtext('Guid') == identity or s.findtext('Name') == person['name'] for s in souls):
        raise ValueError('Person is already registered: ' + person['name'])
    npc = add_entity(person['name'], actor.get('EntityClass'), pose.get('Pos'),
                     native_guid(int(actor.get('EntityGuid'), 16)), pose.get('Rotate'))
    apply_person_properties(npc, actor)
    soul = ET.SubElement(souls, 'Soul', version='8')
    for key, value in dict(SharedSoulGuid=person['soul']['soul_id'], Guid=identity,
                           EntityGuid=npc.get('EntityGuid'), Name=person['name']).items():
        ET.SubElement(soul, key).text = value
    return npc


def actor_resources(target, person, character, namespace, *, role_name, native_soul_table, native_soul_name,
                    native_role_name, resources=None):
    """Add a person to a resource collection; retain previously imported people."""
    files = dict(resources or {})
    with zipfile.ZipFile(Path(target) / 'Data/Tables.pak') as archive:
        native = native_xml(read(archive, native_soul_table))
        template = next(e for e in native.iter('soul') if e.get('soul_name') == native_soul_name)
        roles = native_xml(read(archive, 'Libs/Tables/rpg/role.xml'))
        role = copy.deepcopy(next(e for e in roles.iter('role') if e.get('role_name') == native_role_name))
        brains = native_xml(read(archive, 'Libs/Tables/ai/brain.xml'))
        classes = native_xml(read(archive, 'Libs/Tables/rpg/social_class.xml'))
    root = ET.Element('database', name='barbora')
    soul = ET.SubElement(ET.SubElement(root, 'souls', version='2'), 'soul', dict(template.attrib))
    soul.set('soul_id', person['soul']['soul_id']); soul.set('soul_name', person['name'])
    soul.set('soul_archetype_id', character['archetype'])
    soul.attrib.pop('skald_character_name', None)
    brain, social = native_brain_and_class(person['ai'], brains, classes)
    soul.set('brain_id', brain)
    soul.set('social_class_id', social)
    soul.set('factionName', register_factions(files, person['ai']))
    for key in ('xp_multiplier', 'digestion_multiplier', 'initial_clothing_dirt'):
        if person['soul'].get(key) not in ('', None): soul.set(key, person['soul'][key])
    # Source VIP IDs are quest-specific; a matching integer in KCD2 can name a
    # different character. Keep the neutral template VIP until explicitly mapped.
    role.set('role_name', role_name)
    role_root = ET.Element('database', name='barbora')
    role_rows = ET.SubElement(role_root, 'roles', version='1')
    existing_role = [e for e in roles.iter('role') if e.get('role_name') == role_name]
    if len(existing_role) > 1:
        raise ValueError('Ambiguous native person role: ' + role_name)
    if not existing_role:
        role_rows.append(role)
    additions = {'Libs/Tables/rpg/soul__' + namespace + '.xml': xml(root),
                 'Libs/Tables/rpg/role__' + namespace + '.xml': xml(role_root)}
    if files.keys() & additions.keys():
        raise ValueError('Person namespace already registered: ' + namespace)
    files.update(additions)
    if 'Libs/Storm/storm.xml' in files:
        storm = ET.fromstring(files['Libs/Storm/storm.xml'])
    else:
        with zipfile.ZipFile(Path(target) / 'Data/IPL_GameData.pak') as archive:
            storm = ET.fromstring(read(archive, 'Libs/Storm/storm.xml'))
    operations = {
        'roles': [('addRole', dict(name=role_name))],
        'names': [('setUiName', dict(name=person['instance'].findtext('StaticData/NameStringId')))],
        'appearance': [('set' + k.title(), dict(name=v)) for k, v in character['appearance'].items()],
        'equipment': [('setInventory', dict(preset=character['inventory']))],
        'abilities': stat_operations(person['soul']),
    }
    for task, steps in operations.items():
        filename = task + '/' + namespace + '.xml'
        definition = storm.find(f"tasks/task[@name='{task}']")
        if definition is None: raise ValueError('Missing native Storm task: ' + task)
        ET.SubElement(definition, 'source', path=filename)
        rules = ET.Element('storm')
        rule = ET.SubElement(ET.SubElement(rules, 'rules'), 'rule', name=namespace + '_' + task)
        ET.SubElement(ET.SubElement(rule, 'selectors'), 'hasName', name=person['name'])
        ops = ET.SubElement(rule, 'operations')
        for name, attributes in steps: ET.SubElement(ops, name, attributes)
        files['Libs/Storm/' + filename] = xml(rules)
    files['Libs/Storm/storm.xml'] = xml(storm)
    provenance = json.loads(receipt(person, soul, namespace))
    if character.get('appearance_policy') is not None:
        provenance['appearance_policy'] = character['appearance_policy']
    files['Libs/GlueMapper/PersonImport/' + namespace + '.json'] = json.dumps(provenance, indent=2).encode('utf-8')
    return files

