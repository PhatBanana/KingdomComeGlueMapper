"""Native KCD2 vegetation grid coordinates, without changing render payloads.

Trosky and Kuttenberg use 64/256/1024 m XY cells, terrain elevation at
each cell centre, and XY half-diagonal switching radii. These are not canopy
bounds. A proxy's membership and its parent-relative index must stay intact.
"""
import copy
import math
import struct
import xml.etree.ElementTree as ET

from spatial_hlod import records

VERSION = 1
CELL_SIZES = {1: 4096, 2: 1024, 3: 256, 4: 64}


def instance_cells(items):
    cells = set()
    for record in items:
        if len(record) != 64 or struct.unpack_from('<I', record)[0] != 2:
            continue
        x, y = struct.unpack_from('<2f', record, 44)
        if not all(map(math.isfinite, (x, y))):
            raise ValueError('Non-finite vegetation instance position')
        cells.add((math.floor(x / 64), math.floor(y / 64)))
    return cells


def grid_metadata(cells, tier, height):
    if tier not in CELL_SIZES or not cells:
        raise ValueError('Missing vegetation membership or unsupported HLOD tier')
    size = CELL_SIZES[tier]
    span = size // 64
    regions = {(x // span, y // span) for x, y in cells}
    if len(regions) != 1:
        raise ValueError(f'Vegetation tier {tier} crosses {size}m cells; regroup with proxy membership preserved')
    x, y = next(iter(regions))
    if tier == 1 and (x, y) != (0, 0):
        raise ValueError('Vegetation outside supported 4096m world')
    x, y = (x + .5) * size, (y + .5) * size
    z = float(height(x, y))
    if not math.isfinite(z):
        raise ValueError('Non-finite terrain height for vegetation HLOD')
    # The root is a native sentinel; lower tiers use grid half diagonals.
    return (x, y, z), 8000.0 if tier == 1 else size / math.sqrt(2)


def normalize(document, data, height, *, validate_only=False):
    """Correct only vegetation Pos/Radius. Preserve blocks, links and identities.

    Reject malformed or incorrectly grouped input instead of moving a detail
    object beneath a proxy which does not represent it. All analysis completes
    on a copy before a caller can write any change.
    """
    tree = copy.deepcopy(document)
    root = tree if tree.tag == 'HLod' else tree.find('HLod')
    if root is None or len(data) < 4 or struct.unpack_from('<I', data)[0] != 2:
        raise ValueError('Invalid HLOD root/container')
    spans = []
    changes = []
    tiers = {}
    leaf_cells = set()

    def visit(node, tier=0):
        offset, size = int(node.get('DataOffset')), int(node.get('DataSize'))
        if offset < 4 or size < 4 or offset + size > len(data):
            raise ValueError('Invalid HLOD block extent')
        if struct.unpack_from('<I', data, offset)[0] != size - 4:
            raise ValueError('HLOD block size mismatch')
        spans.append((offset, offset + size))
        own = records(data[offset + 4:offset + size])
        proxy_indices = [int(c.get('ProxyIndex', '-1')) for c in node
                         if int(c.get('ProxyIndex', '-1')) >= 0]
        if len(proxy_indices) != len(set(proxy_indices)) or any(
                i >= len(own) or len(own[i]) != 104 for i in proxy_indices):
            raise ValueError('Invalid/shared HLOD proxy reference')
        vegetation = node.get('Type') == 'Vegetation'
        if tier and not vegetation:
            raise ValueError('Non-vegetation child inside vegetation hierarchy')
        current = tier + 1 if vegetation else 0
        cells = instance_cells(own)
        if vegetation and cells and current != 4:
            raise ValueError('Detailed vegetation must occupy native tier 4')
        for child in node:
            cells.update(visit(child, current))
        if vegetation:
            pos, radius = grid_metadata(cells, current, height)
            tiers[current] = tiers.get(current, 0) + 1
            if current == 4:
                if len(node) or cells & leaf_cells:
                    raise ValueError('Duplicate or non-leaf vegetation cell')
                leaf_cells.update(cells)
            old_pos = tuple(map(float, node.get('Pos', '').split(',')))
            old_radius = float(node.get('Radius'))
            if len(old_pos) != 3 or not all(map(math.isfinite, (*old_pos, old_radius))):
                raise ValueError('Invalid existing vegetation spatial metadata')
            # Native XML uses rounded float32 coordinates. Keep matching bytes.
            if math.dist(old_pos, pos) > .001 or abs(old_radius - radius) > .001:
                changes.append(dict(name=node.get('Name'), tier=current,
                                    old_pos=old_pos, pos=pos,
                                    old_radius=old_radius, radius=radius))
                node.set('Pos', ','.join(format(v, '.9g') for v in pos))
                node.set('Radius', format(radius, '.9g'))
        return cells if vegetation else set()

    visit(root)
    spans.sort()
    if not spans or spans[0][0] != 4 or spans[-1][1] != len(data) or any(
            a[1] != b[0] for a, b in zip(spans, spans[1:])):
        raise ValueError('Overlapping or uncovered HLOD blocks')
    if tiers and tiers.get(1) != 1:
        raise ValueError('Expected one vegetation hierarchy')
    if validate_only and changes:
        raise ValueError(f'Incorrect vegetation grid metadata: {len(changes)} nodes; first {changes[0]["name"]}')
    return tree, dict(version=VERSION, vegetation_nodes=sum(tiers.values()),
                      tiers=tiers, changed_nodes=len(changes), changes=changes,
                      payload_unchanged=True, runtime_verified=False)


def upgrade_package(package, level='kcd1_travel'):
    """One level archive rewrite; no assets, lighting, terrain or gameplay rebuild."""
    from pathlib import Path
    import zipfile
    from region_travel_ground import Heightfield
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    from upgrade_map import read, xml

    package = Path(package)
    relative = f'Data/Levels/{level}/level.pak'
    with zipfile.ZipFile(package / relative) as archive:
        old = read(archive, 'terrain/hlods.xml')
        data = read(archive, 'terrain/hlods.dat')
    document = ET.fromstring(old)
    if not any(n.get('Type') == 'Vegetation' for n in document.iter('HLod')):
        return {}, dict(version=VERSION, vegetation_nodes=0, changed_nodes=0,
                        payload_unchanged=True, runtime_verified=False)
    with zipfile.ZipFile(package / f'Data/Levels/{level}/terrain.pak') as archive:
        height = Heightfield(read(archive, 'terrain/terrain.dat'))
    tree, report = normalize(document, data, height)
    changed = {}
    if report['changed_nodes']:
        normalize(tree, data, height, validate_only=True)
        rewrite(package, relative, {'terrain/hlods.xml': xml(tree)})
        changed[relative] = digest(package / relative)
    return changed, report
