"""Structural scan of ``terrain/hlods.dat`` brush records (ported from the hand-run hlodscan)."""
import math
import struct
import xml.etree.ElementTree as ET

BRUSH, VEGETATION = 1, 2
BRUSH_BYTES, VEGETATION_BYTES = 104, 64
SAMPLE_LIMIT = 40


def terrain_mesh_count(read_head):
    """Number of mesh paths in ``terrain/terrain.dat`` reading only its resource tables.

    ``read_head(n)`` returns the first ``n`` bytes. Returns ``None`` for an unfamiliar header.
    """
    head = read_head(36)
    if len(head) < 36 or head[0] not in (28, 29): return None
    vegetation = struct.unpack_from('<I', head, 32)[0]
    if vegetation > 1000000: return None
    offset = 36 + vegetation * 360
    data = read_head(offset + 4)
    if len(data) < offset + 4: return None
    meshes = struct.unpack_from('<I', data, offset)[0]
    return meshes if meshes <= 1000000 else None


def scan(dat, xml_bytes, mesh_count=None):
    """Return ``dict(stats, bad, ranges, duplicates)``; never raises on bad record data."""
    root = ET.fromstring(xml_bytes)
    nodes = {int(e.get('DataOffset')): e for e in root.iter('HLod') if e.get('DataOffset') is not None}
    stats = dict(brushes=0, vegetation=0, blocks=0, block_without_node=0, node_size_mismatch=0)
    bad, samples = {}, {}
    scale_min, scale_max, extent_max = math.inf, 0.0, 0.0
    seen, duplicate_max = {}, 1
    cursor, length = 4, len(dat)

    def flag(code, detail):
        bad[code] = bad.get(code, 0) + 1
        if len(samples.setdefault(code, [])) < SAMPLE_LIMIT: samples[code].append(detail)

    while cursor + 4 <= length:
        start = cursor
        size = struct.unpack_from('<I', dat, cursor)[0]
        cursor += 4
        end = cursor + size
        stats['blocks'] += 1
        if end > length:
            flag('hlod_block_truncated', f'block at {start} needs {size} B')
            break
        node = nodes.get(start)
        center = radius = None
        if node is None: stats['block_without_node'] += 1
        else:
            if node.get('Pos') and node.get('Radius'):
                center = tuple(map(float, node.get('Pos').split(',')))
                radius = float(node.get('Radius'))
            if node.get('DataSize') and int(node.get('DataSize')) != size + 4:
                stats['node_size_mismatch'] += 1
                flag('hlod_node_size', f'block at {start}: xml DataSize {node.get("DataSize")} != {size + 4}')
        while cursor < end:
            kind = struct.unpack_from('<I', dat, cursor)[0]
            if kind == BRUSH:
                if cursor + BRUSH_BYTES > end:
                    flag('hlod_record_truncated', f'brush at {cursor}')
                    break
                box = struct.unpack_from('<6f', dat, cursor + 4)
                mesh = struct.unpack_from('<H', dat, cursor + 40)[0]
                m = struct.unpack_from('<12f', dat, cursor + 44)
                stats['brushes'] += 1
                where = (m[3], m[7], m[11])
                if not all(map(math.isfinite, box + m)):
                    flag('hlod_nonfinite', f'brush at {cursor} mesh {mesh}')
                else:
                    cols = [math.sqrt(m[c] ** 2 + m[4 + c] ** 2 + m[8 + c] ** 2) for c in range(3)]
                    det = (m[0] * (m[5] * m[10] - m[6] * m[9]) - m[1] * (m[4] * m[10] - m[6] * m[8])
                           + m[2] * (m[4] * m[9] - m[5] * m[8]))
                    extent = max(box[3] - box[0], box[4] - box[1], box[5] - box[2])
                    scale_min, scale_max = min(scale_min, *cols), max(scale_max, *cols)
                    extent_max = max(extent_max, extent)
                    if abs(det) < 1e-6: flag('hlod_degenerate_matrix', f'brush at {cursor} mesh {mesh} det {det:g}')
                    if any(box[i] > box[i + 3] for i in range(3)):
                        flag('hlod_inverted_box', f'brush at {cursor} mesh {mesh}')
                    if mesh_count is not None and mesh >= mesh_count:
                        flag('hlod_mesh_id_range', f'brush at {cursor}: mesh {mesh} >= {mesh_count}')
                    if center is not None:
                        far = max(math.dist(center, (box[3 * (k & 1)], box[1 + 3 * (k >> 1 & 1)], box[2 + 3 * (k >> 2 & 1)]))
                                  for k in range(8))
                        if far > radius * 1.5 + 1:
                            flag('hlod_far_outside_node', f'brush at {cursor} mesh {mesh}: {far:.1f} m vs radius {radius:.1f}')
                    key = (mesh, tuple(round(x, 3) for x in m))
                    count = seen[key] = seen.get(key, 0) + 1
                    duplicate_max = max(duplicate_max, count)
                    if extent > 2000: samples.setdefault('_wide', []).append((mesh, round(extent), where))
                cursor += BRUSH_BYTES
            elif kind == VEGETATION:
                stats['vegetation'] += 1
                cursor += VEGETATION_BYTES
            else:
                flag('hlod_unknown_record', f'kind {kind} at {cursor}')
                break
        cursor = end
    return dict(stats=stats, bad=bad, samples=samples,
                ranges=dict(scale_min=None if scale_min is math.inf else scale_min, scale_max=scale_max,
                            extent_max=extent_max, duplicate_max=duplicate_max,
                            duplicated_placements=sum(1 for c in seen.values() if c > 1)))
