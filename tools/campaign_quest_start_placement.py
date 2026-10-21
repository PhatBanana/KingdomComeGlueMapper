"""Resolve explicitly selected quest-start layouts from authored world links.

This is world staging, not a behavior-tree interpreter. A recipe must select
the quest, actor role and starting place. Later objective destinations must not
be inferred as spawn points. The original controller still owns subsequent
movement, perception, faction changes and quest progression.
"""
import copy
import hashlib
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_bindings import parse_link_labels
from campaign_entity_links import guid_value, native_guid
from character_person import world_entity
from upgrade_map import read, xml


VERSION = 1


def unique(values, label):
    values = list(values)
    if len(values) != 1:
        raise ValueError('Missing or ambiguous ' + label)
    return values[0]


def pose(entity):
    result = {key: entity.get(key, default) for key, default in
              (('Pos', '0,0,0'), ('Rotate', '1,0,0,0'))}
    for key, count in (('Pos', 3), ('Rotate', 4)):
        values = tuple(map(float, result[key].split(',')))
        if len(values) != count or not all(math.isfinite(v) for v in values):
            raise ValueError('Invalid quest start ' + key)
        if key == 'Rotate' and abs(sum(v*v for v in values) - 1) > .001:
            raise ValueError('Invalid quest start quaternion')
    return result


def same_pose(entity, expected):
    actual = pose(entity)
    return all(all(abs(float(a)-float(b)) < 1e-5
                   for a, b in zip(actual[key].split(','), expected[key].split(',')))
               for key in ('Pos', 'Rotate'))


def linked(controller, entities, tag, role):
    links = []
    for link in controller.findall('EntityLinks/Link'):
        if any(label == dict(tag=tag, positional=[role], named={})
               for label in parse_link_labels(link.get('Name', ''))):
            links.append(link)
    link = unique(links, 'quest role ' + tag + ':' + role)
    target = unique((e for e in entities if e.get('EntityId') == link.get('TargetId')),
                    'quest link target ' + role)
    if int(link.get('TargetGuid', '0'), 16) not in (0, int(target.get('EntityGuid'), 16)):
        raise ValueError('Quest link ID/GUID disagree: ' + role)
    return target


def resolve(archive, entities, quest, actor_role, place_role):
    controller = unique((e for e in entities if e.get('Name') == quest),
                        'source quest controller ' + quest)
    actor = linked(controller, entities, 'QuestActor', actor_role)
    place = linked(controller, entities, 'QuestPlace', place_role)
    if actor.get('EntityClass') not in ('NPC', 'NPC_Female'):
        raise ValueError('Selected quest actor is not a person')
    # Both ends may be prefab-local; do not copy parent-local coordinates into
    # the flat destination mission. world_entity also rejects unresolved parents.
    actor_world = world_entity(archive, actor, entities)
    place_world = world_entity(archive, place, entities)
    return dict(quest=quest, actor_role=actor_role, place_role=place_role,
                person=actor.get('Name'), actor_guid=native_guid(int(actor.get('EntityGuid'), 16)),
                source_place_guid=place.get('EntityGuid'),
                original=pose(actor_world), placement=pose(place_world))


def load(source, level, selections):
    """Read all source placements once; identical mission/layer copies are OK."""
    entities = {}
    with zipfile.ZipFile(Path(source)/'Data/Levels'/level/'level.pak') as archive:
        for name in archive.namelist():
            normalized = name.replace('\\', '/').lower()
            if normalized != 'objects_mission0.xml' and not (
                    normalized.startswith('layers/') and normalized.endswith('.xml')):
                continue
            for entity in ET.fromstring(read(archive, name)).iter('Entity'):
                entity.tail = None
                identity = entity.get('EntityId')
                if not identity:
                    # Property records can also be named Entity; only world
                    # entities carry the source link identity.
                    continue
                if identity in entities and ET.tostring(entities[identity]) != ET.tostring(entity):
                    raise ValueError('Conflicting source entity copies: ' + str(identity))
                entities[identity] = entity
        records = [resolve(archive, list(entities.values()), *selection) for selection in selections]
    if len({r['actor_guid'] for r in records}) != len(records):
        raise ValueError('Multiple quest starting places selected for one actor')
    return records


def apply(mission_blob, records):
    """Repair new-game placements and only this importer's owned idle delegates.

    Existing save games are not edited. A custom/moved package placement is a
    conflict, not permission to reset an actor or an authored work destination.
    """
    mission = ET.fromstring(mission_blob)
    changes = []
    for record in records:
        actor = unique((e for e in mission.iter('Entity')
                        if e.get('EntityGuid') == record['actor_guid']),
                       'staged quest actor ' + record['person'])
        if actor.get('Name') != record['person']:
            raise ValueError('Quest starting actor identity differs')
        guid = str(guid_value(actor.get('EntityGuid')))
        idle_guid = native_guid(int.from_bytes(
            hashlib.sha256(('person-idle/' + guid).encode()).digest()[:8], 'little'))
        anchors = [e for e in mission.iter('Entity') if e.get('EntityGuid') == idle_guid]
        if len(anchors) > 1:
            raise ValueError('Duplicate owned idle delegate')
        if anchors and (anchors[0].get('Name') != 'gm_person_idle_' + record['person']
                        or anchors[0].get('EntityClass') != 'TagPoint'):
            raise ValueError('Owned idle delegate identity differs')
        for entity in [actor, *anchors]:
            if not any(same_pose(entity, record[key]) for key in ('original', 'placement')):
                raise ValueError('Quest starting placement conflicts with existing pose: ' + entity.get('Name'))
            if not same_pose(entity, record['placement']):
                entity.attrib.update(record['placement'])
                changes.append(entity.get('Name'))
    return (xml(mission) if changes else mission_blob), changes


def report(records):
    return dict(version=VERSION, mode='selected_quest_start_layout', placements=copy.deepcopy(records),
                runtime_verified=False, controller_converted=False,
                scope='Initial world placement only; does not execute or replace quest callbacks')
