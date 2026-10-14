"""Validate and bind source predefined routes to the native navigation graph.

Version 38 ends with a counted, ordered table of type-12 WUIDs, persistent
entity GUIDs, radii and float3 vertices. Validate the entire table, not just a
coincidental GUID match. The navigation graph is retained byte-for-byte; moving
or resampling its vertices would invalidate its other spatial references.
"""
import hashlib
import math
import struct
import xml.etree.ElementTree as ET

from campaign_entity_links import native_guid


PATH_WUID = 0x0c00000000000000


def read_paths(data):
    if len(data) < 8 or struct.unpack_from('<I', data)[0] != 38:
        raise ValueError('Unsupported predefined-path navigation version')
    candidates = []
    signature = struct.pack('<Q', PATH_WUID)
    start = 4
    while True:
        start = data.find(signature, start)
        if start < 0:
            break
        position, paths = start, {}
        count = struct.unpack_from('<I', data, start - 4)[0]
        try:
            if not 0 < count <= (len(data) - start) // 48:
                raise ValueError('Invalid route count')
            for index in range(count):
                if position + 24 > len(data):
                    raise ValueError('Truncated route header')
                wuid, guid, radius, length = struct.unpack_from('<QQfI', data, position)
                if (wuid != PATH_WUID + index or not guid or guid in paths
                        or not math.isfinite(radius) or radius <= 0 or length < 2
                        or length > (len(data) - position - 24) // 12):
                    raise ValueError('Invalid route record')
                points = list(struct.iter_unpack('<3f', data[position + 24:position + 24 + length * 12]))
                if not all(math.isfinite(v) for point in points for v in point):
                    raise ValueError('Nonfinite route coordinate')
                paths[guid] = dict(wuid=wuid, radius=radius, points=points)
                position += 24 + length * 12
            if position != len(data):
                raise ValueError('Navigation route table does not consume its payload')
            candidates.append(paths)
        except (ValueError, struct.error):
            pass
        start += 1
    if len(candidates) != 1:
        raise ValueError('Missing, malformed or ambiguous predefined-route table')
    return candidates[0]


def bind_path(mission, source, paths):
    """Reuse the source GUID that the compiled graph resolves, never a new GUID."""
    if source.get('EntityClass') != 'PredefinedNavigationPath':
        raise ValueError('Expected a predefined navigation path')
    if source.get('ParentId') not in (None, '', '0') or source.get('ParentGuid') not in (None, '', '0'):
        raise ValueError('Parented path requires attachment conversion')
    identity = int(source.get('EntityGuid'), 16)
    path = paths.get(identity)
    if path is None:
        raise ValueError('Source route has no compiled path: ' + source.get('Name', ''))
    position = tuple(map(float, source.get('Pos', '').split(',')))
    if len(position) != 3 or math.dist(position, path['points'][0]) > .002:
        raise ValueError('Route placement and compiled start disagree')
    guid = native_guid(identity)
    existing = [e for e in mission if e.get('EntityGuid') == guid]
    if len(existing) > 1:
        raise ValueError('Duplicate route placement')
    if existing:
        entity = existing[0]
        if entity.get('EntityClass') != source.get('EntityClass') or entity.get('Pos') != source.get('Pos'):
            raise ValueError('Conflicting route placement')
    else:
        attrs = {k: source.get(k) for k in ('Name', 'Pos', 'Rotate', 'Scale', 'EntityClass', 'CastShadowMinSpec')
                 if source.get(k) is not None}
        attrs.update(EntityGuid=guid, EntityId=str(max((int(e.get('EntityId', '0')) for e in mission), default=0) + 1))
        entity = ET.SubElement(mission, 'Entity', attrs)
        ET.SubElement(entity, 'Properties', bSaved_by_game='0')
    return entity, dict(source_guid=source.get('EntityGuid'), target_guid=guid,
        point_count=len(path['points']), radius=path['radius'], coordinates_preserved=True,
        runtime_verified=False)


def validate_graph(source, installed):
    if source != installed:
        raise ValueError('Installed navigation graph differs from the source route graph')
    paths = read_paths(source)
    return paths, dict(sha256=hashlib.sha256(source).hexdigest(), route_count=len(paths), version=38)
