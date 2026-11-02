"""Audit scheduled NPC beds against the navigation mesh, calibrated on native Trosky.

An NPC lies down through a smart-object animation whose start pose comes from
`smartobjecthelpersetanimations.xml` (the `LieDown` entries of the bed's helper
family, local to the bed) and is checked against the navigation mesh
(`Checks="1,1"`, `CheckMNMTolerance`). That pose sits on the bed itself, so
even native beds are 0.8 to 1 m from the nearest walkable polygon and the engine
projects the pose onto the mesh within a tolerance. Nothing documents that
tolerance, so this audit measures the distance for every native bed of each
helper family and uses that envelope as the yardstick: a converted bed whose
lie-down pose is no farther from the mesh than the native 90th percentile is
`ok`, within the native maximum `marginal`, and beyond it, or without any
walkable surface within reach, an `outlier`. The forge-loft beds were outliers
of the last kind (no surface within 2 m horizontally and 1.5 m vertically).

Read-only: it reports, it changes nothing. Tile layout as documented in
`docs/bed-navigation-audit.md` (Recast tile, little endian, size law
`112 + 4*vertCount + 28*polyCount + 68*offMeshConCount`).
"""
import argparse
import collections
import json
import math
import struct
import time
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

from cooking_pots import rotate
from upgrade_map import read

VERSION = 1
CONVERTED = 'Data/Levels/kcd1_travel'
NATIVE = 'Data/Levels/trosecko'
BASE = 'recast/rdnavmesh_1'
TILE = 16.0
MAGIC, TILE_VERSION = 0x444e4156, 14
SEARCH_H, SEARCH_V = 2.0, 1.5  # how far a pose may look for its nearest walkable polygon
SLACK = 0.03  # metres over the native maximum: vertex quantization (16/2047 m) and a finite native sample
TOWNS = {'skalitz': (600.0, 3250.0, 1000.0, 3600.0)}
HUBS = ('SchedulerHub', 'SmartObjectHolder')


def vec(text, count):
    values = tuple(map(float, text.split(',')))
    if len(values) != count or not all(map(math.isfinite, values)):
        raise ValueError('Invalid entity transform: ' + text)
    return values


def cell_of(x, y):
    return int(math.floor(x / TILE)), int(math.floor(y / TILE))


# ---- navigation mesh ----

def parse_tile(blob):
    """Read one tile; tolerant of the flat bounds that empty tiles carry."""
    if len(blob) < 112:
        raise ValueError('Truncated navigation tile')
    ints = struct.unpack_from('<17I', blob); floats = struct.unpack_from('<11f', blob, 68)
    if ints[:2] != (MAGIC, TILE_VERSION):
        raise ValueError('Unsupported navigation tile format')
    P, V, om, base = ints[6], ints[7], ints[15], ints[16]
    if len(blob) != 112 + 4 * V + 28 * P + 68 * om or base != P - om:
        raise ValueError('Navigation tile size law violated')
    cell, layer = (ints[2], ints[3]), ints[4]
    bmin, bmax = floats[4:7], floats[7:10]
    span = (bmax[2] - bmin[2]) or 1.0
    o, verts = 112, []
    for _ in range(V - 2 * om):
        u = struct.unpack_from('<I', blob, o)[0]; o += 4
        verts.append((bmin[0] + (u >> 21) * TILE / 2047, bmin[1] + (u >> 10 & 0x7ff) * TILE / 2047,
                      bmin[2] + (u & 0x3ff) * span / 1023))
    for _ in range(om):
        f = struct.unpack_from('<6f', blob, o); o += 24
        verts.append(f[:3]); verts.append(f[3:])
    polys = []
    for _ in range(P):
        vs = struct.unpack_from('<6H', blob, o); ns = struct.unpack_from('<6H', blob, o + 12)
        area, nv, flags = struct.unpack_from('<BBH', blob, o + 24); o += 28
        if not 2 <= nv <= 6 or any(v >= V for v in vs[:nv]):
            raise ValueError('Invalid navigation polygon record')
        polys.append(dict(verts=vs[:nv], neis=ns[:nv], area=area, nv=nv, flags=flags))
    return dict(cell=cell, layer=layer, bmin=bmin, bmax=bmax, verts=verts, polys=polys[:base], links=polys[base:])


def index_of(hdr):
    index, pos = {}, 0
    while pos < len(hdr):
        x, y, off, count = struct.unpack_from('<4I', hdr, pos); pos += 16
        sizes = struct.unpack_from('<%dI' % count, hdr, pos); pos += 4 * count
        spans = []
        for size in sizes:
            spans.append((off, size)); off += size
        index[(x, y)] = spans
    return index


class Mesh:
    """Base mesh of a recast.pak; a variant's cells, when given, replace the base cells."""

    def __init__(self, recast, variant=None):
        with zipfile.ZipFile(recast) as z:
            self.index, self.nav = index_of(read(z, BASE + '.hdr')), read(z, BASE + '.nav')
            self.variant_index, self.variant_nav = {}, b''
            if variant:
                name = 'recast/rdnavmesh_%s_1' % variant
                self.variant_index, self.variant_nav = index_of(read(z, name + '.hdr')), read(z, name + '.nav')
        self.cache = {}

    def tiles(self, cell):
        if cell not in self.cache:
            index, nav = (self.variant_index, self.variant_nav) if cell in self.variant_index else (self.index, self.nav)
            self.cache[cell] = [parse_tile(nav[o:o + s]) for o, s in index.get(cell, [])]
        return self.cache[cell]

    def around(self, x, y):
        cx, cy = cell_of(x, y)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                yield from self.tiles((cx + dx, cy + dy))


def point_in(px, py, pts):
    inside, n = False, len(pts)
    for i in range(n):
        x1, y1 = pts[i][:2]; x2, y2 = pts[(i + 1) % n][:2]
        if (y1 > py) != (y2 > py) and x1 + (py - y1) * (x2 - x1) / (y2 - y1) > px:
            inside = not inside
    return inside


def seg_dist(px, py, a, b):
    ax, ay = a[:2]; bx, by = b[:2]
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def plane_z(px, py, pts):
    nx = ny = nz = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1, z1 = pts[i]; x2, y2, z2 = pts[(i + 1) % n]
        nx += (y1 - y2) * (z1 + z2); ny += (z1 - z2) * (x1 + x2); nz += (x1 - x2) * (y1 + y2)
    cx = sum(p[0] for p in pts) / n; cy = sum(p[1] for p in pts) / n; cz = sum(p[2] for p in pts) / n
    return cz if abs(nz) < 1e-9 else cz - (nx * (px - cx) + ny * (py - cy)) / nz


def nearest(mesh, point):
    """Nearest walkable polygon within SEARCH_H / SEARCH_V by 3D distance, like the engine's closest-mesh query."""
    px, py, pz = point
    best = None
    for tile in mesh.around(px, py):
        for i, poly in enumerate(tile['polys']):
            if poly['nv'] < 3:
                continue
            pts = [tile['verts'][k] for k in poly['verts']]
            if point_in(px, py, pts):
                d = 0.0
            else:
                d = min(seg_dist(px, py, pts[j], pts[(j + 1) % len(pts)]) for j in range(len(pts)))
            if d > SEARCH_H:
                continue
            zs = plane_z(px, py, pts); dz = zs - pz
            if abs(dz) > SEARCH_V:
                continue
            key = (round(math.hypot(d, dz), 3), round(d, 3))
            if best is None or key < best[0]:
                best = (key, dict(horizontal=round(d, 3), dz=round(dz, 3), surface_z=round(zs, 3),
                                  cell=list(tile['cell']), layer=tile['layer'], poly=i))
    return None if best is None else best[1]


# ---- beds and their lie-down poses ----

def lie_poses(helpers):
    """Local lie-down start poses per helper family (LieDown entries, deduplicated)."""
    poses = {}
    for collection in helpers:
        name = collection.get('HelperSetName')
        if not name:
            continue
        starts = {}
        for anim in collection.iter('SmartObjectHelperSetAnimation'):
            if anim.get('DebugFragmentName') != 'LieDown':
                continue
            helper = anim.find('HelperTransformLocal'); start = anim.find('StartTransform')
            if helper is None or start is None:
                continue
            hp = vec(helper.get('Position', '0,0,0'), 3); hr = vec(helper.get('Rotation', '1,0,0,0'), 4)
            sp = vec(start.get('Position', '0,0,0'), 3)
            local = tuple(round(hp[i] + rotate(hr, sp)[i], 3) for i in range(3))
            starts.setdefault(local, dict(local=local, tags=anim.get('DebugFragTagState', ''),
                                          checks=anim.get('Checks'), tolerance=anim.get('CheckMNMTolerance')))
        if starts:
            poses[name] = list(starts.values())
    return poses


def town_of(pos):
    for name, (x0, y0, x1, y1) in TOWNS.items():
        if x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1:
            return name
    return 'elsewhere'


def level_files(level):
    with zipfile.ZipFile(Path(level) / 'level.pak') as z:
        names = {n.lower(): n for n in z.namelist()}
        mission = ET.fromstring(read(z, names['objects_mission0.xml']))
        helpers = ET.fromstring(read(z, names['smartobjecthelpersetanimations.xml']))
    return mission, helpers


def measure(level, *, scheduled_only, town='all', recast=None, variant=None):
    """One record per bed: its poses, each pose's nearest polygon and the best lie-down pose."""
    level = Path(level)
    mission, helpers = level_files(level)
    poses = lie_poses(helpers)
    mesh = Mesh(Path(recast) if recast else level / 'recast.pak', variant)
    entities = {e.get('EntityId'): e for e in mission.iter('Entity') if e.get('EntityId')}
    incoming = collections.defaultdict(list)
    for e in mission.iter('Entity'):
        for link in e.findall('EntityLinks/Link'):
            incoming[link.get('TargetId')].append((link.get('Name'), e))
    records = []
    for e in mission.iter('Entity'):
        bed = e.find('Properties/Bed') if e.get('EntityClass') == 'StanceSmartObject' else None
        if bed is None or not bed.get('esSleepQuality') or e.get('ParentId') or e.get('ParentGuid'):
            continue
        sleepers = sorted({src.get('Name') for name, src in incoming.get(e.get('EntityId'), [])
                           if name == '_,use' and src.get('EntityClass') in HUBS})
        if scheduled_only and not sleepers:
            continue
        pos = vec(e.get('Pos'), 3)
        where = town_of(pos)
        if town != 'all' and where != town:
            continue
        props = e.find('Properties')
        family = props.get('soclass_SmartObjectHelpers') or ''
        rotation = vec(e.get('Rotate', '1,0,0,0'), 4)
        preferred = sorted(entities[l.get('TargetId')].get('Name') for l in e.findall('EntityLinks/Link')
                           if 'preferedSleeper' in (l.get('Name') or '') and l.get('TargetId') in entities)
        record = dict(name=e.get('Name'), id=e.get('EntityId'), family=family, pos=[round(v, 3) for v in pos],
                      quality=bed.get('esSleepQuality'), sleepers=sleepers, preferred=preferred, town=where, poses=[])
        for pose in poses.get(family, []):
            world = tuple(pos[i] + rotate(rotation, pose['local'])[i] for i in range(3))
            record['poses'].append(dict(tags=pose['tags'], local=list(pose['local']), world=[round(v, 3) for v in world],
                                        lie='liePlace' in pose['tags'], nearest=nearest(mesh, world)))
        lie = [p['nearest'] for p in record['poses'] if p['lie'] and p['nearest'] is not None]
        record['has_pose'] = any(p['lie'] for p in record['poses'])
        record['best'] = min(lie, key=lambda f: (math.hypot(f['horizontal'], f['dz']), f['horizontal'])) if lie else None
        records.append(record)
    return sorted(records, key=lambda r: r['name'])


def percentile(values, q):
    values = sorted(values)
    return round(values[round(q * (len(values) - 1))], 3)


def envelope(records):
    """Per family: how far native lie-down poses sit from the mesh (p90 and maximum)."""
    result = {}
    for family in sorted({r['family'] for r in records if r['has_pose']}):
        rows = [r for r in records if r['family'] == family and r['has_pose']]
        found = [r['best'] for r in rows if r['best'] is not None]
        if not found:
            continue
        h = [f['horizontal'] for f in found]; dz = [abs(f['dz']) for f in found]
        result[family] = dict(n=len(rows), without_surface=len(rows) - len(found), h_p90=percentile(h, .9), h_max=max(h),
                              dz_p90=percentile(dz, .9), dz_max=max(dz))
    return result


def classify(record, native):
    if not record['has_pose']:
        return 'no_helper_set'
    bounds = native.get(record['family'])
    if bounds is None:
        return 'no_native_family'
    best = record['best']
    if best is None:
        return 'outlier'
    if best['horizontal'] <= bounds['h_p90'] and abs(best['dz']) <= bounds['dz_p90']:
        return 'ok'
    if best['horizontal'] <= bounds['h_max'] + SLACK and abs(best['dz']) <= bounds['dz_max'] + SLACK:
        return 'marginal'
    return 'outlier'


def audit(package, target, out=None, town='all', recast=None, variant=None):
    """Measure the converted scheduled beds against the native envelope; optionally write the reports."""
    started = time.time()
    native = envelope(measure(Path(target) / NATIVE, scheduled_only=False))
    records = measure(Path(package) / CONVERTED, scheduled_only=True, town=town, recast=recast, variant=variant)
    by_status, by_family, flagged = collections.Counter(), collections.Counter(), []
    for record in records:
        record['status'] = classify(record, native)
        by_status[record['status']] += 1
        by_family['%s/%s' % (record['family'], record['status'])] += 1
        if record['status'] != 'ok':
            flagged.append(dict(name=record['name'], family=record['family'], pos=record['pos'], town=record['town'],
                                sleepers=record['sleepers'], status=record['status'], best=record['best']))
    report = dict(version=VERSION, package=str(package), target=str(target), town=town, recast=None if recast is None else str(recast),
                  variant=variant, beds=len(records), seconds=round(time.time() - started, 1),
                  search=dict(horizontal=SEARCH_H, vertical=SEARCH_V), native_envelope=native,
                  by_status=dict(sorted(by_status.items())), by_family_status=dict(sorted(by_family.items())),
                  flagged=flagged, runtime_verified=False)
    if out is not None:
        out = Path(out); out.mkdir(parents=True, exist_ok=True)
        with open(out / 'beds.jsonl', 'w', encoding='utf-8') as sink:
            for record in records:
                sink.write(json.dumps(record) + '\n')
        (out / 'report.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--package', type=Path, required=True, help='mod folder holding Data/Levels/kcd1_travel')
    parser.add_argument('--target', type=Path, required=True, help='KCD2 game folder (native Trosky calibrates the envelope)')
    parser.add_argument('--out', type=Path, default=None, help='folder for beds.jsonl and report.json')
    parser.add_argument('--town', default='all', choices=['all', *TOWNS])
    parser.add_argument('--recast', type=Path, default=None, help='test the converted beds against another recast.pak')
    parser.add_argument('--variant', default=None, help='variant mesh of that recast.pak whose cells replace the base cells')
    result = audit(**vars(parser.parse_args()))
    print(json.dumps(result, indent=1))
