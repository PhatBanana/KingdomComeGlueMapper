"""Merge converted gameplay placements into a visual world without duplicate tools."""
import copy
import xml.etree.ElementTree as ET

from campaign_entity_links import guid_value
from campaign_quest_graph import xml


def merge(baseline, fragment, jobs):
    world, incoming = ET.fromstring(baseline), ET.fromstring(fragment)
    # Keep baseline numeric identities: attachments and unrelated level data
    # can refer to them. Only fragment-local IDs are allocated again.
    originals = list(world.iter('Entity'))
    additions = list(incoming.iter('Entity'))
    by_guid, by_id = {}, {}
    for entity in originals:
        guid, eid = entity.get('EntityGuid'), entity.get('EntityId')
        if guid:
            key = guid_value(guid)
            if key in by_guid:
                raise ValueError('Duplicate baseline entity GUID: ' + guid)
            by_guid[key] = entity
        if eid:
            if eid in by_id:
                raise ValueError('Duplicate baseline entity ID: ' + eid)
            by_id[eid] = entity
    targets = {}
    fragment_ids = {}
    for entity in additions:
        key = guid_value(entity.get('EntityGuid'))
        if key in targets:
            raise ValueError('Duplicate converted entity GUID')
        targets[key] = entity
        if entity.get('EntityId'):
            if entity.get('EntityId') in fragment_ids:
                raise ValueError('Duplicate converted entity ID')
            fragment_ids[entity.get('EntityId')] = key
        if entity.get('ParentId') not in (None, '', '0') or entity.get('ParentGuid') not in (None, '', '0'):
            raise ValueError('Converted attachment needs parent identity remapping')
    replacements = {}
    for job in jobs:
        if job.get('status') != 'imported' or job.get('group') != 'entities':
            continue
        evidence = job.get('evidence', {})
        names = list(evidence.get('replaces_visual_entities', []))
        if evidence.get('replaces_visual_entity'):
            names.append(evidence['replaces_visual_entity'])
        if not names:
            continue
        target = guid_value(job['target'])
        if target not in targets:
            raise ValueError('Visual replacement has no converted placement')
        for name in names:
            if name in replacements and replacements[name] != target:
                raise ValueError('Conflicting visual replacement: ' + name)
            replacements[name] = target
    removed, aliases = [], {}
    parents = {child: parent for parent in world.iter() for child in parent}
    for name in replacements:
        if sum(e.get('Name') == name for e in originals) > 1:
            raise ValueError('Ambiguous decorative replacement: ' + name)
    for entity in originals:
        parent_id = entity.get('ParentId')
        parent_guid = entity.get('ParentGuid')
        parent = by_id.get(parent_id)
        if parent_guid not in (None, '', '0'):
            parent = by_guid.get(guid_value(parent_guid))
        if parent is not None and parent.get('Name') in replacements:
            raise ValueError('Decorative replacement has an attached child requiring conversion')
    for entity in originals:
        name = entity.get('Name')
        if name not in replacements:
            continue
        # Replacement evidence must not silently remove a live gameplay entity.
        if entity.get('EntityClass') not in ('BasicEntity', 'GeomEntity', 'Brush'):
            raise ValueError('Visual replacement targets a gameplay entity: ' + name)
        if entity.get('EntityGuid'):
            aliases[guid_value(entity.get('EntityGuid'))] = replacements[name]
        parents[entity].remove(entity)
        removed.append(name)
    removed_ids = {id(e) for e in originals if e.get('Name') in replacements}
    by_guid = {k:v for k,v in by_guid.items() if id(v) not in removed_ids}
    next_id = max((int(n) for n in by_id), default=0) + 1
    for key, entity in targets.items():
        if key in by_guid:
            raise ValueError('Converted placement collides with existing gameplay entity: ' + entity.get('EntityGuid'))
        entity = copy.deepcopy(entity)
        entity.set('EntityId', str(next_id)); next_id += 1
        world.append(entity)
        by_guid[key] = entity
    # Resolve GUID links across both worlds; numeric-only baseline links are
    # retained unless their target was one of the removed decorative objects.
    for entity in world.iter('Entity'):
        imported = bool(entity.get('EntityGuid')) and guid_value(entity.get('EntityGuid')) in targets
        for link in entity.findall('EntityLinks/Link'):
            guid = link.get('TargetGuid')
            if guid and guid != '0':
                key = guid_value(guid)
            elif imported:
                key = fragment_ids.get(link.get('TargetId'))
                if key is None:
                    raise ValueError('Converted numeric link has no placed target')
            else:
                old = by_id.get(link.get('TargetId'))
                if old is None or id(old) not in removed_ids:
                    continue
                key = replacements[old.get('Name')]
            key = aliases.get(key, key)
            target = by_guid.get(key)
            if target is None:
                # Existing external-layer links are legal. Converted links
                # must resolve in this assembled fragment.
                if imported:
                    raise ValueError('Converted link has no placed target: ' + str(guid))
                continue
            link.set('TargetGuid', target.get('EntityGuid'))
            link.set('TargetId', target.get('EntityId'))
    return xml(world), dict(removed_visuals=sorted(removed), added_entities=len(targets),
                            baseline_entities=len(originals), runtime_validated=False)
