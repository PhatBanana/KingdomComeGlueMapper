"""Clip mesh/BSP decoding shared by conversion and contract checks."""
import struct
import hashlib
from cooking_pots import rotate
from entity_visuals import world_transform


def associate_probe_clips(probes, clips, entities, geometry_read, source_defaults, *, apply=False):
    """Resolve unlinked interior captures by strict BSP containment.

    Explicit author links win. Ambiguous/outside captures remain unresolved;
    neither a nearby volume nor a bounding-box overlap establishes ownership.
    Does not move the probe or change its influence box. Default is read-only:
    containment is a diagnostic candidate, not proof of native light ownership.
    apply=True is reserved for explicit development comparisons.
    """
    prepared = []
    for clip in clips:
        path = clip.find('ClipVolume').get('GeometryFileName').lower().replace('%level%/', '')
        try:
            geometry, bsp = clip_geometry(geometry_read(path))
        except KeyError:
            continue
        prepared.append((clip, *world_transform(clip, entities), geometry['local_bounds'], bsp))
    report = []
    for probe in probes:
        if probe.findall('EntityLinks/Link'):
            continue
        props = probe.find('Properties')
        opts = props.find('Options') if props is not None else None
        default = source_defaults.find('Options').get('bDeferredClipBounds', '0')
        if (opts.get('bDeferredClipBounds', default) if opts is not None else default) != '1':
            continue
        pos, rotation, scale = world_transform(probe, entities)
        offset = [float(props.get('GenOffset'+a, source_defaults.get('GenOffset'+a, '0'))) * scale[i]
                  if props is not None else 0 for i, a in enumerate('XYZ')]
        capture = tuple(a+b for a,b in zip(pos, rotate(rotation, offset)))
        matches = []
        for clip, origin, q, clip_scale, bounds, bsp in prepared:
            if any(s == 0 for s in clip_scale):
                raise ValueError('Zero clip-volume scale')
            local = rotate((q[0],-q[1],-q[2],-q[3]), [a-b for a,b in zip(capture,origin)])
            local = [v/s for v,s in zip(local,clip_scale)]
            lo, hi = bounds
            if all(lo[i] < local[i] < hi[i] for i in range(3)) and bsp_contains(bsp, local):
                matches.append(clip)
        record = {'source_id': probe.get('EntityId'), 'capture': capture,
                  'candidates': [c.get('EntityId') for c in matches],
                  'status': 'candidate' if len(matches)==1 else 'ambiguous' if matches else 'outside'}
        if apply and len(matches)==1:
            import xml.etree.ElementTree as ET
            links = probe.find('EntityLinks')
            if links is None: links = ET.SubElement(probe, 'EntityLinks')
            ET.SubElement(links, 'Link', Name='ClipVolume', TargetId=matches[0].get('EntityId'))
        report.append(record)
    return report

def clip_geometry(blob):
    if blob[:8] != b'CrChF\x07\0\0':
        raise ValueError('Unsupported clip CGF header')
    count, table = struct.unpack_from('<II', blob, 8)
    chunks = []
    bsp = []
    bounds = None
    for i in range(count):
        kind, version, identity, size, offset = struct.unpack_from('<HHIII', blob, table + i*16)
        if offset + size > len(blob):
            raise ValueError('Clip CGF chunk exceeds file')
        chunks.append({'type': hex(kind), 'version': hex(version), 'size': size})
        if kind == 0x1016 and struct.unpack_from('<I', blob, offset+4)[0] == 0:
            number, stride = struct.unpack_from('<II', blob, offset+8)
            if stride != 12 or size != 24 + number*stride:
                raise ValueError('Unsupported clip position stream')
            vertices = list(struct.iter_unpack('<3f', blob[offset+24:offset+size]))
            bounds = [[min(p[a] for p in vertices) for a in range(3)],
                      [max(p[a] for p in vertices) for a in range(3)]]
        if kind == 0x3009:
            number = struct.unpack_from('<I', blob, offset)[0]
            if size != 4 + number*24:
                raise ValueError('Unsupported clip BSP node packing')
            bsp = list(struct.iter_unpack('<4fii', blob[offset+4:offset+size]))
            if any(child < -1 or child >= number for node in bsp for child in node[4:]):
                raise ValueError('Invalid clip BSP child index')
    if bounds is None or not bsp:
        raise ValueError('Clip missing mesh or BSP dependency')
    return {'sha256': hashlib.sha256(blob).hexdigest(), 'chunks': chunks,
            'local_bounds': bounds, 'bsp_nodes': len(bsp)}, bsp


def bsp_contains(nodes, point):
    # CryEntitySystem/BSPTree3D: positive terminal is outside, negative inside.
    # Border points are intentionally excluded from an automatic association.
    index = 0
    for _ in range(len(nodes)+1):
        x, y, z, d, positive, negative = nodes[index]
        distance = x*point[0] + y*point[1] + z*point[2] + d
        if abs(distance) < 1e-5:
            return False
        child = positive if distance > 0 else negative
        if child == -1:
            return distance < 0
        index = child
    raise ValueError('Cyclic clip BSP')


