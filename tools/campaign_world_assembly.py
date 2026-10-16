"""Assemble native world registration resources without replacing unrelated data."""
import copy
import xml.etree.ElementTree as ET

from campaign_entity_links import append_links, guid_value
from campaign_quest_graph import xml
from campaign_trigger_areas import read_areas, write_areas
from campaign_world_objects import merge as merge_objects

PREFIX = 'world/registration/'


def signature(node):
    return (node.tag, sorted(node.attrib.items()), (node.text or '').strip(),
            [signature(child) for child in node])


def append_records(destination, source, key, label):
    index = {}
    for node in destination:
        identity = key(node)
        if not identity or identity in index:
            raise ValueError('Missing or duplicate baseline ' + label)
        index[identity] = node
    added = 0
    seen = set()
    for node in source:
        identity = key(node)
        if not identity or identity in seen:
            raise ValueError('Missing or duplicate converted ' + label)
        seen.add(identity)
        if identity in index:
            if signature(index[identity]) != signature(node):
                raise ValueError('Conflicting ' + label + ': ' + str(identity))
        else:
            destination.append(copy.deepcopy(node))
            index[identity] = node
            added += 1
    return added


def assemble(baseline, registration, jobs):
    """Return changed level entries only; never mutate an installed package.

    The baseline must include every resource touched by registration. Unknown
    resource schemas fail explicitly instead of replacing the whole table.
    """
    incoming = {p.removeprefix(PREFIX): data for p, data in registration.items() if p.startswith(PREFIX)}
    if 'objects_mission0.xml' not in incoming:
        raise ValueError('World assembly requires converted objects')
    objects, object_report = merge_objects(baseline['objects_mission0.xml'], incoming.pop('objects_mission0.xml'), jobs)
    output = {'objects_mission0.xml': objects}
    placed = {guid_value(e.get('EntityGuid')) for e in ET.fromstring(objects).iter('Entity') if e.get('EntityGuid')}
    counts = {}
    tables = {'tables/ai/scheduler.xml': ('Schedulers', 'EntityGuid'),
              'tables/ai/smartobjectanimations.xml': ('SmartObjectAnimationss', 'EntityGuid')}
    for path, data in incoming.items():
        if path == 'triggerareas.fubar':
            old, new = read_areas(baseline[path]), read_areas(data)
            if old['version'] != 3 or new['version'] != 3 or old['export_version'] != new['export_version']:
                raise ValueError('World trigger export versions do not match')
            areas = {a.guid:a for a in old['areas']}
            for area in new['areas']:
                if area.guid not in placed:
                    raise ValueError('Converted area has no assembled entity')
                if area.guid in areas and areas[area.guid] != area:
                    raise ValueError('Conflicting world trigger geometry')
                areas[area.guid] = area
            output[path] = write_areas(areas.values(), old['export_version'])
            counts[path] = len(areas) - len(old['areas'])
            continue
        root = ET.fromstring(data)
        if path == 'waitinglinks.xml':
            if root.tag != 'StaticLinksInfo' or root.get('version') != '1':
                raise ValueError('Unknown converted AI link schema')
            links = []
            for edge in root.findall('WaitingLinks/WaitingLink'):
                a, b = edge.get('SourceId'), edge.get('TargetId')
                if guid_value(a) not in placed or guid_value(b) not in placed:
                    raise ValueError('Converted AI link has no assembled endpoint')
                for definition in edge.findall('LinkDefinition'):
                    links.append((a, b, definition.text or ''))
            output[path] = append_links(baseline.get(path), links, allow_untagged=True)
            counts[path] = len(links)
            continue
        old = ET.fromstring(baseline[path]) if path in baseline else None
        if path == 'whdata_0':
            if old is None or old.tag != 'Root' or root.tag != 'Root':
                raise ValueError('Native soul world baseline is required')
            if any(c.tag != 'SoulList' for c in root):
                raise ValueError('Unconverted world metadata outside SoulList')
            dest, records = old.find('SoulList/Souls'), root.find('SoulList/Souls')
            if dest is None or records is None:
                raise ValueError('Missing native soul list')
            for soul in records:
                if guid_value(soul.findtext('EntityGuid')) not in placed:
                    raise ValueError('Converted soul has no assembled actor')
                for existing in dest:
                    if (existing.findtext('EntityGuid') == soul.findtext('EntityGuid')
                            and existing.findtext('Guid') != soul.findtext('Guid')):
                        raise ValueError('Conflicting soul instances for one actor')
            counts[path] = append_records(dest, records, lambda n:n.findtext('Guid'), 'soul instance')
        elif path == 'smartobjecthelpersetanimations.xml':
            if root.tag != 'SmartObjectAnimationCollections':
                raise ValueError('Unknown helper collection schema')
            if old is None: old = ET.Element(root.tag, root.attrib)
            if old.tag != root.tag: raise ValueError('Helper collection root mismatch')
            counts[path] = append_records(old, root, lambda n:n.get('HelperSetName'), 'helper family')
        elif path in tables:
            container, field = tables[path]
            records = root.find(container)
            if records is None or records.get('version') != '1':
                raise ValueError('Unknown converted world table: ' + path)
            if old is None:
                old = ET.Element(root.tag, root.attrib)
                ET.SubElement(old, container, records.attrib)
            dest = old.find(container)
            if dest is None or dest.get('version') != '1':
                raise ValueError('World table version mismatch: ' + path)
            for row in records:
                if int(row.get(field, '0')) not in placed:
                    raise ValueError('Converted world table row has no assembled entity: ' + path)
                if path.endswith('/scheduler.xml'):
                    for link in row.findall('Links/S_ActivityLink'):
                        for target in ('TargetGuid', 'PositioningDelegate'):
                            value = int(link.get(target, '0'))
                            if value and value not in placed:
                                raise ValueError('Converted scheduler link has no assembled target')
            counts[path] = append_records(dest, records, lambda n:int(n.get(field, '0')), path)
        else:
            raise ValueError('World resource merge requires an adapter: ' + path)
        output[path] = xml(old)
    # Check cross-resource contracts after every fragment has been merged;
    # dictionary insertion order must not affect whether references resolve.
    scheduler_path = 'tables/ai/scheduler.xml'
    if scheduler_path in incoming:
        merged_rows = ET.fromstring(output[scheduler_path]).find('Schedulers')
        registered = {r.get('EntityGuid') for r in merged_rows}
        for link in ET.fromstring(incoming[scheduler_path]).findall('.//S_ActivityLink'):
            if link.get('TargetGuid') not in registered:
                raise ValueError('Converted activity target has no compiled scheduler record')
    animation_path = 'tables/ai/smartobjectanimations.xml'
    collection_path = 'smartobjecthelpersetanimations.xml'
    if animation_path in incoming:
        collection_data = output.get(collection_path, baseline.get(collection_path))
        hashes = ({n.get('HashValue') for n in ET.fromstring(collection_data).iter('SmartObjectHelperSetAnimationCollection')}
                  if collection_data else set())
        for row in ET.fromstring(incoming[animation_path]).findall('.//SmartObjectAnimations'):
            if row.get('Hash') not in hashes:
                raise ValueError('Converted helper instance has no animation collection')
    return output, dict(objects=object_report, resource_additions=counts, runtime_validated=False)
