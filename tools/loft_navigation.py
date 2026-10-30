"""Give the Skalitz forge loft a navigation surface and connect its ladder for NPC AI.

The converted navigation mesh (recast v14, 16 m tiles) has no polygon on the loft and no
off-mesh link to it, so Henry's parents cannot path to their assigned loft beds and the
bed animations fail their navmesh check (docs/loft-navigation.md). This converter appends
one tagged layer tile to each of the two cells under the loft and leaves every existing
tile byte-identical:

- loft floor polygons at the measured floor height, clear of the authored furniture by a
  margin, covering the ladder landing and both parents' room-facing lie-down poses;
- a ladder-foot patch on the ground floor that joins the existing workshop polygon across
  the tile border at x = 736 (layers of one cell only meet through border portals);
- the ladder's off-mesh connection written like the 58 native Trosky ladder records:
  category 3, bidirectional, radius 0.5, start 0.52 m in front of the foot, end 0.43 m
  behind the top, entity = the converted ladder's GUID.

Tile layout (little endian, established from every tile of both games):
  0 u32 magic 'VAND', 4 u32 version 14, 8/12 u32 tx/ty, 16 u32 layer, 20 u32 userId (0 in
  native tiles, LAYER_TAG here), 24 u32 polyCount (one 2-vertex poly per connection
  included), 28 u32 vertCount (two float vertices per connection included), 32 u32 packed
  vertex count, 36 u32 internal links + 2, 40 u32 bake statistic (3 for small tiles),
  44..56 zero, 60 u32 offMeshConCount, 64 u32 offMeshBase, 68 f32 1.76/0.32/0.32/0.8,
  84 f32 bmin[3], 96 f32 bmax[3], 108 f32 12.5; then u32 packed vertices (X bits 21-31 and
  Y bits 10-20 over 16 m / 2047, Z bits 0-9 over the tile's z range / 1023), f32[6] per
  connection, 28-byte polys (u16 verts[6], u16 neis[6], u8 area, u8 nv, u16 flags; neis 0
  none, 1-based poly, 0x8000|side portal with side 0/2/4/6 = +x/+y/-x/-y; vertices run
  clockwise in x,y) and 52-byte connections (f32 pos[6], f32 rad, u16 poly, u8 flags,
  u8 side, u64 entity, u32 category, u32 0x7fffffff, u32 0xffff0001).
  Size = 112 + 4*vertCount + 28*polyCount + 68*offMeshConCount.

Offline validation only: geometry, links and layout clearances. Runtime traversal is not
claimed; see the acceptance steps in docs/loft-navigation.md.
"""
import json
import math
import struct
import xml.etree.ElementTree as E
import zipfile
from pathlib import Path

from campaign_entity_links import guid_value, native_guid
from cooking_pots import rotate
from forge_loft import PREFIX
from forge_loft_layout import LAYOUT
from room_layout import footprint, overlaps, resolve
from static_navigation_profiles import AUTHORED_LAYER_TAG as LAYER_TAG, BASE, decode, encode, native_layers
from upgrade_map import digest_bytes, read

VERSION = 1
MARKER = 'gluemapper/loft_navigation.json'
TILE, CELL = 16.0, .08
MAGIC, TILE_VERSION = 0x444e4156, 14
WALKABLE = (1.76, .32, .32, .8)
CLIMB = WALKABLE[2]
BV_QUANT = 12.5
STATISTIC = 3  # header field 40: a bake statistic no stored structure reproduces; 3 is the native mode for small tiles
GROUND_AREA, GROUND_FLAGS, LINK_AREA, LINK_FLAGS = 0x01, 0x0100, 0x21, 0x0101
PORTAL = 0x8000
SIDES = {0: (0, 2047), 2: (1, 2047), 4: (0, 0), 6: (1, 0)}  # portal side -> (axis, packed coordinate)
LADDER = dict(category=3, flags=1, radius=.5, side=0xff, tail=(0x7fffffff, 0xffff0001),
              foot=(-.038, .518, -.139), top=(.023, -.425))  # top z is the ladder height
LADDER_NAME = PREFIX + 'ladder'
BEDS = {'mother': PREFIX + 'mother_bed', 'father': PREFIX + 'father_bed'}
POSE = .867  # Bed_1Place_High lie-down start: 0.867 m beside the bed centre on either long side
BED_MARGIN, PROP_MARGIN, UNMEASURED = .18, .25, .35
BRUSH_MARGIN, BRUSH_EXTENT = .30, 4.0
MIN_PORTAL_OVERLAP = .3
FLOOR_Z, GROUND_Z = 67.30, 63.92
# World-space rectangles, clockwise like native polygons. Each bound follows a layout
# footprint, the floor boards, the landing keepout or a measured brush; validate()
# rejects them when the layout, the ladder or the brushes move.
LOFT = (
    # Between Henry's bed (east clearance 733.74) and the tile border; north edge = Mother's bed clearance.
    ('loft_west', FLOOR_Z, ((733.75, 3417.15), (733.75, 3421.96), (736.00, 3421.96), (736.00, 3417.15))),
    # Border to the landing column; north edge = Father's bed clearance.
    ('loft_border', FLOOR_Z, ((736.00, 3417.15), (736.00, 3422.00), (737.00, 3422.00), (737.00, 3417.15))),
    # Landing column up to the sack clearance (737.39); the split vertex meets the hatch.
    ('loft_landing', FLOOR_Z, ((737.00, 3417.15), (737.00, 3422.00), (737.38, 3422.00), (737.38, 3418.55),
                               (737.38, 3417.15))),
    # Hatch: inside the ladder-landing keepout, south of the family chest clearance (3418.55).
    ('loft_hatch', FLOOR_Z, ((737.38, 3416.60), (737.38, 3417.15), (737.38, 3418.55), (738.20, 3418.55),
                             (738.20, 3416.60))),
)
GROUND = (
    ('foot_west', GROUND_Z, ((736.00, 3414.40), (736.00, 3415.19), (737.25, 3415.19), (737.25, 3414.76),
                             (737.25, 3414.40))),
    ('foot_east', GROUND_Z, ((737.25, 3414.76), (737.25, 3416.20), (738.24, 3416.20), (738.24, 3414.76))),
)


def vec(text, count):
    values = tuple(map(float, text.split(',')))
    if len(values) != count or not all(map(math.isfinite, values)):
        raise ValueError('Invalid entity transform: ' + text)
    return values


def cell_of(x, y):
    return int(math.floor(x / TILE)), int(math.floor(y / TILE))


def polygons():
    result = []
    for group, kind in ((LOFT, 'loft'), (GROUND, 'ground')):
        for name, z, verts in group:
            cx = sum(v[0] for v in verts) / len(verts); cy = sum(v[1] for v in verts) / len(verts)
            result.append(dict(name=name, kind=kind, z=z, verts=tuple(verts), cell=cell_of(cx, cy)))
    return result


# ---- tile encoding and the reference decoder ----

def quantize(cell, zrange, point):
    X = round((point[0] - cell[0] * TILE) / TILE * 2047)
    Y = round((point[1] - cell[1] * TILE) / TILE * 2047)
    Z = round((point[2] - zrange[0]) / (zrange[1] - zrange[0]) * 1023)
    if not (0 <= X <= 2047 and 0 <= Y <= 2047 and 0 <= Z <= 1023):
        raise ValueError('Vertex outside its navigation tile: ' + str(point))
    return X, Y, Z


def dequantize(cell, zrange, packed):
    X, Y, Z = packed
    return (cell[0] * TILE + X * TILE / 2047, cell[1] * TILE + Y * TILE / 2047,
            zrange[0] + Z * (zrange[1] - zrange[0]) / 1023)


def zrange_for(values):
    """Native tiles keep bmin.z/bmax.z on 0.08 m multiples."""
    low = math.floor((min(values) - .05) / CELL) * CELL
    high = math.ceil((max(values) + .05) / CELL) * CELL
    return low, high


def pack_tile(cell, layer, polys, links, zrange):
    """polys: name, verts (x, y), z, neis (0 | 1-based index | PORTAL|side); links: dicts."""
    table, verts = {}, []

    def index(point):
        key = quantize(cell, zrange, point)
        if key not in table:
            table[key] = len(verts); verts.append(key)
        return table[key]
    records = []
    for p in polys:
        ids = [index((x, y, p['z'])) for x, y in p['verts']]
        records.append((ids, list(p['neis']), GROUND_AREA, GROUND_FLAGS))
    packed = len(verts)
    internal = sum(1 for ids, neis, _, _ in records for n in neis if n and not n & PORTAL)
    P, V, om = len(records) + len(links), packed + 2 * len(links), len(links)
    bmin = (cell[0] * TILE, cell[1] * TILE, zrange[0]); bmax = (cell[0] * TILE + TILE, cell[1] * TILE + TILE, zrange[1])
    blob = bytearray(struct.pack('<17I11f', MAGIC, TILE_VERSION, cell[0], cell[1], layer, LAYER_TAG, P, V, packed,
                                 internal + 2, STATISTIC, 0, 0, 0, 0, om, P - om, *WALKABLE, *bmin, *bmax, BV_QUANT))
    for X, Y, Z in verts:
        blob.extend(struct.pack('<I', X << 21 | Y << 10 | Z))
    for link in links:
        blob.extend(struct.pack('<6f', *link['start'], *link['end']))
    for ids, neis, area, flags in records:
        blob.extend(struct.pack('<6H6HBBH', *ids, *[0] * (6 - len(ids)), *neis, *[0] * (6 - len(neis)), area, len(ids), flags))
    for k in range(om):
        blob.extend(struct.pack('<6H6HBBH', packed + 2 * k, packed + 2 * k + 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, LINK_AREA, 2, LINK_FLAGS))
    for k, link in enumerate(links):
        blob.extend(struct.pack('<6ffHBBQIII', *link['start'], *link['end'], link['radius'], P - om + k, link['flags'],
                                link['side'], link['entity'], link['category'], *link['tail']))
    return bytes(blob)


def decode_tile(blob):
    """Independent reader of the documented layout; raises on any inconsistency."""
    if len(blob) < 112:
        raise ValueError('Truncated navigation tile')
    ints = struct.unpack_from('<17I', blob); floats = struct.unpack_from('<11f', blob, 68)
    if ints[:2] != (MAGIC, TILE_VERSION):
        raise ValueError('Unsupported navigation tile format')
    P, V, packed, om, base = ints[6], ints[7], ints[8], ints[15], ints[16]
    if packed != V - 2 * om or base != P - om or ints[11:15] != (0, 0, 0, 0):
        raise ValueError('Navigation tile header counts are inconsistent')
    if len(blob) != 112 + 4 * V + 28 * P + 68 * om:
        raise ValueError('Navigation tile size law violated')
    cell, layer, user = (ints[2], ints[3]), ints[4], ints[5]
    bmin, bmax = floats[4:7], floats[7:10]
    zrange = (bmin[2], bmax[2])
    if any(a > b for a, b in zip(bmin, bmax)) or zrange[1] <= zrange[0]:
        raise ValueError('Invalid navigation tile bounds')
    o = 112; verts = []; quantized = []
    for i in range(packed):
        u = struct.unpack_from('<I', blob, o)[0]; o += 4
        key = (u >> 21, u >> 10 & 0x7ff, u & 0x3ff); quantized.append(key)
        verts.append(dequantize(cell, zrange, key))
    for k in range(om):
        f = struct.unpack_from('<6f', blob, o); o += 24
        verts.append(f[:3]); verts.append(f[3:])
    polys = []
    for i in range(P):
        vs = struct.unpack_from('<6H', blob, o); ns = struct.unpack_from('<6H', blob, o + 12)
        area, nv, flags = struct.unpack_from('<BBH', blob, o + 24); o += 28
        if not 2 <= nv <= 6 or any(v >= V for v in vs[:nv]) or any(vs[nv:]) or any(ns[nv:]):
            raise ValueError('Invalid navigation polygon record')
        polys.append(dict(verts=vs[:nv], neis=ns[:nv], area=area, nv=nv, flags=flags))
    links = []
    for k in range(om):
        r = struct.unpack_from('<6ffHBBQIII', blob, o); o += 52
        links.append(dict(start=r[:3], end=r[3:6], radius=r[6], poly=r[7], flags=r[8], side=r[9], entity=r[10],
                          category=r[11], tail=r[12:14]))
    if o != len(blob):
        raise ValueError('Navigation tile has trailing bytes')
    internal = sum(1 for p in polys[:base] for n in p['neis'] if n and not n & PORTAL)
    return dict(cell=cell, layer=layer, user=user, counts=ints[6:17], floats=floats, bmin=bmin, bmax=bmax,
                zrange=zrange, verts=verts, quantized=quantized, polys=polys, links=links, internal=internal)


# ---- geometry helpers (x, y) ----

def shoelace(points):
    return sum(points[i][0] * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * points[i][1]
               for i in range(len(points))) / 2


def convex_clockwise(points):
    """Clockwise, convex or collinear turns only, like the native polygons."""
    for i in range(len(points)):
        a, b, c = points[i], points[(i + 1) % len(points)], points[(i + 2) % len(points)]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if cross > 1e-9:
            return False
    return shoelace(points) < 0


def inside(point, points, tolerance=1e-9):
    sign = 0
    for i in range(len(points)):
        a, b = points[i], points[(i + 1) % len(points)]
        cross = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
        if abs(cross) <= tolerance:
            continue
        if sign == 0:
            sign = 1 if cross > 0 else -1
        elif (cross > 0) != (sign > 0):
            return False
    return True


def edge_distance(point, points):
    best = math.inf
    for i in range(len(points)):
        (ax, ay), (bx, by) = points[i], points[(i + 1) % len(points)]
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0 if not length else max(0.0, min(1.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / length))
        best = min(best, math.hypot(point[0] - (ax + t * dx), point[1] - (ay + t * dy)))
    return best


def plane_z(points):
    return sum(p[2] for p in points) / len(points)


def box(points, margin=0.0):
    xs = [p[0] for p in points]; ys = [p[1] for p in points]
    return min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin


def corners(bounds):
    x0, y0, x1, y1 = bounds
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def portal_edges(tile, side=None):
    """(poly index, edge index, a, b) for every portal edge of a decoded tile."""
    base = tile['counts'][10]
    for i, poly in enumerate(tile['polys'][:base]):
        for k, nei in enumerate(poly['neis']):
            if nei & PORTAL and (side is None or nei & 0xff == side):
                a = tile['verts'][poly['verts'][k]]; b = tile['verts'][poly['verts'][(k + 1) % poly['nv']]]
                yield i, k, a, b


def span_overlap(a, b, c, d, axis):
    lo = max(min(a[axis], b[axis]), min(c[axis], d[axis])); hi = min(max(a[axis], b[axis]), max(c[axis], d[axis]))
    return hi - lo


# ---- world inputs ----

def entity_transform(root, name):
    entity = next((e for e in root.iter('Entity') if e.get('Name') == name), None)
    if entity is None:
        raise ValueError('Missing loft entity: ' + name)
    return entity, vec(entity.get('Pos'), 3), vec(entity.get('Rotate', '1,0,0,0'), 4)


def ladder_link(root):
    entity, position, rotation = entity_transform(root, LADDER_NAME)
    if entity.get('EntityClass') != 'Ladder':
        raise ValueError('Loft ladder is not a Ladder entity')
    height = float(entity.find('Properties').get('height'))
    if not 1.0 <= height <= 6.0:
        raise ValueError('Implausible loft ladder height')
    foot = tuple(position[i] + rotate(rotation, LADDER['foot'])[i] for i in range(3))
    top = tuple(position[i] + rotate(rotation, (*LADDER['top'], height))[i] for i in range(3))
    return dict(start=foot, end=top, radius=LADDER['radius'], flags=LADDER['flags'], side=LADDER['side'],
                entity=guid_value(entity.get('EntityGuid')), category=LADDER['category'], tail=LADDER['tail'],
                name=LADDER_NAME, guid=entity.get('EntityGuid'), position=position, height=height)


def bed_poses(root):
    poses = {}
    for role, name in BEDS.items():
        entity, position, rotation = entity_transform(root, name)
        if entity.get('EntityClass') != 'StanceSmartObject':
            raise ValueError('Loft bed is not a smart object: ' + name)
        poses[role] = [tuple(position[i] + rotate(rotation, (sign * POSE, 0, .02))[i] for i in range(3)) for sign in (1, -1)]
    return poses


def layout_geometry():
    placements = resolve(LAYOUT)
    zones = {z['name']: z for z in resolve(dict(LAYOUT, items=LAYOUT['clearances']))}
    if 'ladder_landing' not in zones:
        raise ValueError('Loft layout has no ladder landing')
    landing = box(footprint(zones['ladder_landing']))
    origin_z = LAYOUT['origin'][2]
    floor, obstacles = [], []
    for item in placements:
        if item.get('walkable_surface'):
            floor.extend(footprint(item))
        elif item['position'][2] - origin_z > .3:
            continue  # table-top props
        elif 'footprint' in item:
            obstacles.append((item['name'], box(footprint(item), BED_MARGIN if item['kind'] == 'bed' else PROP_MARGIN)))
        else:
            x, y = item['position'][:2]
            obstacles.append((item['name'], (x - UNMEASURED - PROP_MARGIN, y - UNMEASURED - PROP_MARGIN,
                                             x + UNMEASURED + PROP_MARGIN, y + UNMEASURED + PROP_MARGIN)))
    if not floor:
        raise ValueError('Loft layout has no floor surface')
    return dict(floor=box(floor), landing=landing, obstacles=obstacles)


def brush_bounds(data):
    """Bounding boxes of the HLOD brush records (kind 1: bbox at +4)."""
    if struct.unpack_from('<I', data)[0] != 2:
        raise ValueError('Unknown HLOD container')
    cursor, result = 4, []
    while cursor < len(data):
        size = struct.unpack_from('<I', data, cursor)[0]; cursor += 4; end = cursor + size
        while cursor < end:
            kind = struct.unpack_from('<I', data, cursor)[0]
            if kind == 1:
                result.append(struct.unpack_from('<6f', data, cursor + 4))
            cursor += 104 if kind == 1 else 64
    return result


# ---- building ----

def build(cells, link):
    """Authored tiles keyed by cell: polygons grouped per cell, neighbours from shared edges."""
    tiles, groups = {}, {}
    for p in polygons():
        groups.setdefault(p['cell'], []).append(p)
    foot_cell = cell_of(*link['start'][:2])
    for cell, polys in groups.items():
        if cell not in cells:
            raise ValueError('Loft cell is missing from the base navigation: ' + str(cell))
        layer = max(decode_tile(t)['layer'] for t in cells[cell]) + 1
        zrange = zrange_for([p['z'] for p in polys])
        keyed = [[quantize(cell, zrange, (x, y, p['z'])) for x, y in p['verts']] for p in polys]
        for p, keys in zip(polys, keyed):
            if len(set(keys)) != len(keys):
                raise ValueError('Loft polygon collapses under quantization: ' + p['name'])
            neis = []
            for k in range(len(keys)):
                a, b = keys[k], keys[(k + 1) % len(keys)]
                matches = [j + 1 for j, other in enumerate(keyed) if other is not keys
                           and any(other[m] == b and other[(m + 1) % len(other)] == a for m in range(len(other)))]
                if len(matches) > 1:
                    raise ValueError('Loft edge shared by several polygons: ' + p['name'])
                portal = [side for side, (axis, value) in SIDES.items() if a[axis] == value and b[axis] == value]
                if matches and portal:
                    raise ValueError('Loft edge is both internal and a portal: ' + p['name'])
                neis.append(matches[0] if matches else PORTAL | portal[0] if portal else 0)
            p['neis'] = neis
        links = [link] if cell == foot_cell else []
        tiles[cell] = pack_tile(cell, layer, polys, links, zrange)
    if foot_cell not in tiles:
        raise ValueError('The ladder foot is outside the authored ground patch')
    return tiles


# ---- validation ----

def validate(cells, authored, link, poses, layout, brushes=None):
    """Checks on the decoded bytes; returns the evidence that goes into the marker."""
    decoded = {cell: decode_tile(blob) for cell, blob in authored.items()}
    named = {p['name']: p for p in polygons()}
    world = {}  # name -> (cell, points with z)
    for cell, tile in decoded.items():
        if tile['user'] != LAYER_TAG or tile['cell'] != cell:
            raise ValueError('Authored tile is not tagged for its cell')
        if any(decode_tile(t)['layer'] == tile['layer'] for t in cells[cell]):
            raise ValueError('Authored layer id collides with a native layer')
        if tile['counts'][3] != tile['internal'] + 2 or tile['counts'][4] != STATISTIC:
            raise ValueError('Authored tile header statistics differ from the native pattern')
        if tuple(round(v, 6) for v in tile['floats'][:4]) != WALKABLE or tile['floats'][10] != BV_QUANT:
            raise ValueError('Authored tile agent settings differ from native tiles')
        if any(abs(v / CELL - round(v / CELL)) > 1e-3 for v in tile['zrange']):
            raise ValueError('Authored tile z range is not on 0.08 m multiples')
        base = tile['counts'][10]
        group = [p for p in polygons() if p['cell'] == cell]
        if len(group) != base:
            raise ValueError('Authored tile polygon count differs from the design')
        for i, poly in enumerate(tile['polys'][:base]):
            points = [tile['verts'][v] for v in poly['verts']]
            if poly['nv'] < 3 or poly['area'] != GROUND_AREA or poly['flags'] != GROUND_FLAGS:
                raise ValueError('Authored polygon record is malformed')
            if not convex_clockwise([p[:2] for p in points]):
                raise ValueError('Authored polygon is not convex and clockwise: ' + group[i]['name'])
            if any(not (tile['bmin'][a] - 1e-6 <= p[a] <= tile['bmax'][a] + 1e-6) for p in points for a in range(3)):
                raise ValueError('Authored polygon leaves its tile: ' + group[i]['name'])
            if max(abs(p[2] - group[i]['z']) for p in points) > .005:
                raise ValueError('Authored polygon height drifted: ' + group[i]['name'])
            if max(math.hypot(p[0] - d[0], p[1] - d[1]) for p, d in zip(points, group[i]['verts'])) > .006:
                raise ValueError('Authored polygon drifted under quantization: ' + group[i]['name'])
            for k, nei in enumerate(poly['neis']):
                a, b = poly['verts'][k], poly['verts'][(k + 1) % poly['nv']]
                twins = [j for j, other in enumerate(tile['polys'][:base]) if j != i
                         and any(other['verts'][m] == b and other['verts'][(m + 1) % other['nv']] == a for m in range(other['nv']))]
                if nei & PORTAL:
                    axis, value = SIDES[nei & 0xff]
                    if tile['quantized'][a][axis] != value or tile['quantized'][b][axis] != value or twins:
                        raise ValueError('Portal edge is not on the tile border: ' + group[i]['name'])
                elif nei:
                    if twins != [nei - 1]:
                        raise ValueError('Neighbour edge is not shared back: ' + group[i]['name'])
                elif twins:
                    raise ValueError('Shared edge without a neighbour link: ' + group[i]['name'])
            world[group[i]['name']] = (cell, points)
        for k, poly in enumerate(tile['polys'][base:]):
            expected = (tile['counts'][2] + 2 * k, tile['counts'][2] + 2 * k + 1)
            if poly['verts'] != expected or poly['nv'] != 2 or poly['area'] != LINK_AREA or poly['flags'] != LINK_FLAGS or any(poly['neis']):
                raise ValueError('Off-mesh polygon record differs from the native form')
        for k, con in enumerate(tile['links']):
            if con['poly'] != base + k or con['radius'] != LADDER['radius'] or con['flags'] != LADDER['flags'] \
                    or con['side'] != LADDER['side'] or con['category'] != LADDER['category'] or tuple(con['tail']) != LADDER['tail']:
                raise ValueError('Ladder connection record differs from the native form')
            # f32 spacing at these coordinates is 0.00024 m.
            if any(abs(con['start'][i] - link['start'][i]) > 5e-4 or abs(con['end'][i] - link['end'][i]) > 5e-4 for i in range(3)):
                raise ValueError('Ladder endpoints were not stored exactly')
            if not all(tile['bmin'][a] <= con['end'][a] <= tile['bmax'][a] for a in range(2)):
                raise ValueError('Ladder top lies outside the cell although side is 255')
    # Endpoints: the foot inside a ground polygon of the record's own tile, the top inside a loft polygon of the same cell.
    foot_cell = cell_of(*link['start'][:2])
    support = {}
    for label, point, kind in (('foot', link['start'], 'ground'), ('top', link['end'], 'loft')):
        holders = [name for name, (cell, points) in world.items() if cell == foot_cell and named[name]['kind'] == kind
                   and inside(point, [p[:2] for p in points]) and abs(plane_z(points) - point[2]) <= CLIMB]
        if not holders:
            raise ValueError('Ladder ' + label + ' is not on an authored polygon of its cell')
        support[label] = dict(polygon=holders[0], dz=round(plane_z(world[holders[0]][1]) - point[2], 3),
                              clearance=round(edge_distance(point, [p[:2] for p in world[holders[0]][1]]), 3))
    # Portals: every authored portal edge must meet an opposite portal edge in the neighbouring cell at the same height.
    portals = []
    for cell, tile in decoded.items():
        group = [p for p in polygons() if p['cell'] == cell]
        for i, k, a, b in portal_edges(tile):
            side = tile['polys'][i]['neis'][k] & 0xff
            axis, _ = SIDES[side]
            step = {0: (1, 0), 2: (0, 1), 4: (-1, 0), 6: (0, -1)}[side]
            neighbour = (cell[0] + step[0], cell[1] + step[1])
            opposite = (side + 4) % 8
            found = None
            stack = ([('authored', decoded[neighbour])] if neighbour in decoded else []) + \
                    [('native', decode_tile(t)) for t in cells.get(neighbour, ())]
            for origin, other in stack:
                for j, m, c, d in portal_edges(other, opposite):
                    if abs(c[axis] - a[axis]) > .01 or span_overlap(a, b, c, d, 1 - axis) < MIN_PORTAL_OVERLAP:
                        continue
                    if abs((a[2] + b[2]) / 2 - (c[2] + d[2]) / 2) > CLIMB:
                        continue
                    found = dict(polygon=group[i]['name'], side=side, neighbour=list(neighbour), layer=other['layer'],
                                 origin=origin, neighbour_polygon=j, overlap=round(span_overlap(a, b, c, d, 1 - axis), 3))
                    break
                if found:
                    break
            if not found:
                raise ValueError('Portal edge has no partner across the tile border: ' + group[i]['name'])
            portals.append(found)
    # Layout: loft polygons inside the floor or the landing, clear of the furniture; poses on the mesh.
    floor, landing = layout['floor'], layout['landing']
    for name, (cell, points) in world.items():
        if named[name]['kind'] != 'loft':
            continue
        for p in points:
            if not ((floor[0] - 1e-3 <= p[0] <= floor[2] + 1e-3 and floor[1] - 1e-3 <= p[1] <= floor[3] + 1e-3)
                    or (landing[0] - 1e-3 <= p[0] <= landing[2] + 1e-3 and landing[1] - 1e-3 <= p[1] <= landing[3] + 1e-3)):
                raise ValueError('Loft polygon leaves the authored floor and landing: ' + name)
        shape = [p[:2] for p in points]
        for item, bounds in layout['obstacles']:
            if overlaps(shape, corners(bounds)):
                raise ValueError('Loft polygon overlaps furniture clearance: ' + name + ' / ' + item)
    if not (landing[0] <= link['end'][0] <= landing[2] and landing[1] <= link['end'][1] <= landing[3]):
        raise ValueError('Ladder top is outside the layout landing keepout')
    pose_report = {}
    for role, candidates in poses.items():
        placed = []
        for point in candidates:
            holders = [name for name, (cell, points) in world.items() if named[name]['kind'] == 'loft'
                       and inside(point, [p[:2] for p in points]) and abs(plane_z(points) - point[2]) <= CLIMB]
            placed.append(dict(pose=[round(v, 3) for v in point], polygon=holders[0] if holders else None,
                               clearance=round(edge_distance(point, [p[:2] for p in world[holders[0]][1]]), 3) if holders else None))
        if not any(p['polygon'] for p in placed):
            raise ValueError('No lie-down pose of the ' + role + ' bed lies on the loft mesh')
        pose_report[role] = placed
    brush_report = None
    if brushes is not None:
        checked = 0
        for bounds in brushes:
            if max(bounds[3] - bounds[0], bounds[4] - bounds[1]) > BRUSH_EXTENT or bounds[2] > GROUND_Z + .5 or bounds[5] < GROUND_Z + .15:
                continue
            checked += 1
            zone = corners((bounds[0] - BRUSH_MARGIN, bounds[1] - BRUSH_MARGIN, bounds[3] + BRUSH_MARGIN, bounds[4] + BRUSH_MARGIN))
            for name, (cell, points) in world.items():
                if named[name]['kind'] == 'ground' and overlaps([p[:2] for p in points], zone):
                    raise ValueError('Ground patch overlaps a brush: ' + name + ' at ' + str([round(v, 2) for v in bounds]))
        brush_report = dict(checked=checked, margin=BRUSH_MARGIN)
    return dict(polygons=[dict(name=name, cell=list(cell), kind=named[name]['kind'],
                               vertices=[[round(v, 4) for v in p] for p in points])
                          for name, (cell, points) in world.items()],
                layers={str(cell): decoded[cell]['layer'] for cell in decoded},
                ladder=dict(name=link['name'], guid=link['guid'], entity=native_guid(link['entity']),
                            position=list(link['position']), height=link['height'],
                            foot=[round(v, 4) for v in link['start']], top=[round(v, 4) for v in link['end']],
                            category=LADDER['category'], flags=LADDER['flags'], radius=LADDER['radius'], support=support),
                portals=portals, poses=pose_report,
                layout=dict(floor=[round(v, 3) for v in floor], landing=[round(v, 3) for v in landing],
                            obstacles=[dict(item=i, bounds=[round(v, 3) for v in b]) for i, b in layout['obstacles']]),
                brushes=brush_report)


def convert(files, mission, native_mesh, brushes=None):
    """Append the authored layers to the base mesh; repeatable, every native tile preserved."""
    names = {n.lower(): n for n in files}
    if len(names) != len(files) or any(BASE + ext not in names for ext in ('.hdr', '.nav')):
        raise ValueError('Missing base navigation pair')
    if len(native_mesh) < 68:
        raise ValueError('Truncated native navigation reference')
    settings, version = native_mesh[:56], struct.unpack_from('<I', native_mesh, 64)[0]
    header, mesh = files[names[BASE + '.hdr']], files[names[BASE + '.nav']]
    current = decode(header, mesh, settings, version)
    cells = {cell: native_layers(tiles) for cell, tiles in current.items()}
    previous = sum(len(current[c]) - len(cells[c]) for c in cells)
    root = E.fromstring(mission)
    link, poses, layout = ladder_link(root), bed_poses(root), layout_geometry()
    authored = build(cells, link)
    report = validate(cells, authored, link, poses, layout, brushes)
    result = dict(cells)
    for cell, blob in authored.items():
        result[cell] = cells[cell] + (blob,)
    new_header, new_mesh = encode(result, settings)
    if decode(new_header, new_mesh, settings, version) != result:
        raise ValueError('Loft navigation did not round-trip')
    native_header, native_nav = encode(cells, settings)
    report.update(version=VERSION, layer_tag=f'0x{LAYER_TAG:08x}', base_tiles=sum(map(len, cells.values())),
                  tiles_after=sum(map(len, result.values())),
                  native_tiles_preserved=all(result[c][:len(cells[c])] == cells[c] for c in cells),
                  native_mesh_sha256=digest_bytes(native_nav), native_header_sha256=digest_bytes(native_header),
                  previously_authored_layers=previous, runtime_verified=False)
    updated = dict(files)
    updated[names[BASE + '.hdr']], updated[names[BASE + '.nav']] = new_header, new_mesh
    # The marker must not change between repeated runs; the strip count stays in the report.
    marker = {k: v for k, v in report.items() if k != 'previously_authored_layers'}
    updated[names.get(MARKER, MARKER)] = json.dumps(marker, indent=2).encode()
    return updated, report


# ---- package integration ----

RELATIVE = 'Data/Levels/kcd1_travel/recast.pak'


def plan(package, target):
    if target is None:
        raise ValueError('Game folder required to validate the loft navigation format')
    package, target = Path(package), Path(target)
    with zipfile.ZipFile(target / 'Data/Levels/trosecko/recast.pak') as z:
        native = read(z, BASE + '.nav')
    with zipfile.ZipFile(package / 'Data/Levels/kcd1_travel/level.pak') as z:
        names = {n.lower(): n for n in z.namelist()}
        mission = read(z, names['objects_mission0.xml'])
        brushes = brush_bounds(read(z, names['terrain/hlods.dat'])) if 'terrain/hlods.dat' in names else None
    with zipfile.ZipFile(package / RELATIVE) as z:
        wanted = {n for n in z.namelist() if n.lower() in (BASE + '.hdr', BASE + '.nav', MARKER)}
        files = {n: read(z, n) for n in wanted}
    updated, report = convert(files, mission, native, brushes)
    changes = {n: b for n, b in updated.items() if files.get(n) != b}
    return RELATIVE, changes, report


def stage(mod, target, output):
    """Dry run into a new folder, like forge_loft.stage; the package is not modified."""
    from build_horse_trader_test import rewrite, digest
    mod, target, output = map(Path, (mod, target, output))
    if output.exists():
        raise FileExistsError('Choose a new loft navigation staging folder')
    relative, changes, report = plan(mod, target)
    rewrite(mod / relative, output / relative, changes)
    report.update(baseline_sha256=digest(mod / relative), changed_entries=sorted(changes))
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    return report


def upgrade(package, target):
    """Used inside the shared clean-build / transactional-resume finalization."""
    from setup_package_upgrade import rewrite
    from upgrade_map import digest as file_digest
    relative, changes, report = plan(package, target)
    if changes:
        rewrite(Path(package), relative, changes)
    report['changed_entries'] = sorted(changes)
    return {relative: file_digest(Path(package) / relative)}, report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mod', 'target', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    print(json.dumps(stage(**vars(parser.parse_args())), indent=2))
