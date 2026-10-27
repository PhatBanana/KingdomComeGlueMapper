"""Read level data in place (directories, PAKs or synthetic blobs); never writes.

What the bytes prove versus what is inferred is recorded per field:

- ``terrain/hlods.dat`` (package): 4-byte header, then blocks of
  ``u32 size`` + records; kind 1 brush = 104 bytes (world AABB 6f at +4,
  layer u16 at +28, mesh u16 at +40, 3x4 row-major matrix at +44, material i32
  at +96), kind 2 = 64 bytes. Same walk as ``designer_collision_repair``.
- ``terrain/terrain.dat`` resource tables (meshes, materials) start at +32;
  stride 360/256/256 (``compiled_terrain``).
- KCD1 source brushes are kind-1, 100 bytes (``building_brushes.read_brush``).
- CGF chunk 0x1000 (mesh) carries the local AABB at +108; chunk 0x1014 carries
  the material name. Float3 position streams (0x1016 type 0) refine the bounds.
"""
from collections import defaultdict
import hashlib
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as E
import zipfile

from . import Unsupported

DESIGNER_MESH_MARKERS = ('/setup_designer/', 'brush/designer_')
PROXY_MATERIAL_MARKER = 'materials/special/collision_proxy'
SURFACE_TABLE = 'libs/materialeffects/surfacetypes.xml'

# Entity classes treated as interactions, with the clearance shape used.
INTERACTION_CLASSES = {
    'AnimDoor': 'door', 'KettleActionTrigger': 'cooking', 'BedTrigger': 'bed',
    'StanceSmartObject': 'seat', 'Chair': 'seat', 'ActionTrigger': 'use',
    'Ladder': 'ladder', 'LedgeObject': 'ledge', 'Stash': 'use', 'Shop': 'use',
    'FoodProcessingTrigger': 'use', 'FireplaceSmartObject': 'use',
    'WaterTubeActionTrigger': 'use', 'InteractionTrigger': 'use',
    'DetailMovementSmartObject': 'use',
}


def _norm(name):
    return name.replace('\\', '/').lstrip('/').lower()


def read_entry(z, info):
    """Read one member even when its local header uses backslashes (KCD1 PAKs)."""
    try:
        return z.read(info)
    except zipfile.BadZipFile:
        from upgrade_map import read  # production reader tolerant of PAK headers
        return read(z, info.filename)


class Files:
    """Case-insensitive view over loose files, PAKs or blobs, with hashes."""
    def __init__(self):
        self.entries = {}  # key -> (loader, label)
        self.hashes = {}
        self._zips = []

    @classmethod
    def blobs(cls, blobs):
        f = cls()
        for k, v in blobs.items(): f.entries[_norm(k)] = (lambda v=v: v, '<blob>/' + k)
        return f

    def add_pak(self, path, prefix=''):
        z = zipfile.ZipFile(path); self._zips.append(z)
        for info in z.infolist():
            key = _norm(prefix + info.filename)
            self.entries.setdefault(key, (lambda z=z, i=info: read_entry(z, i), f'{Path(path).parent.name}/{Path(path).name}:{info.filename}'))

    def add_dir(self, path):
        for p in sorted(Path(path).rglob('*')):
            if p.is_file(): self.entries.setdefault(_norm(p.relative_to(path).as_posix()), (p.read_bytes, str(p)))

    def has(self, key): return _norm(key) in self.entries

    def read(self, key, record=True):
        k = _norm(key)
        if k not in self.entries: raise KeyError(key)
        data = self.entries[k][0]()
        if record: self.hashes[self.entries[k][1]] = hashlib.sha256(data).hexdigest()
        return data

    def close(self):
        for z in self._zips: z.close()


# ---------------------------------------------------------------- binary readers
def walk_hlods(data):
    """Yield (offset, kind) for every record; raise on any stride mismatch."""
    if len(data) < 4: raise Unsupported('Truncated hlods.dat')
    cursor = 4
    while cursor < len(data):
        if cursor + 4 > len(data): raise Unsupported('Truncated hlods block header')
        end = cursor + 4 + struct.unpack_from('<I', data, cursor)[0]; cursor += 4
        if end > len(data): raise Unsupported('hlods block exceeds file')
        while cursor < end:
            kind = struct.unpack_from('<I', data, cursor)[0]
            size = {1: 104, 2: 64}.get(kind)
            if size is None: raise Unsupported(f'Unknown hlods record kind {kind} at {cursor}')
            yield cursor, kind
            cursor += size
        if cursor != end: raise Unsupported('hlods record overruns its block')


def package_brush(data, offset):
    return dict(world_aabb=struct.unpack_from('<6f', data, offset+4),
                layer=struct.unpack_from('<H', data, offset+28)[0],
                mesh=struct.unpack_from('<H', data, offset+40)[0],
                matrix=struct.unpack_from('<12f', data, offset+44),
                material=struct.unpack_from('<i', data, offset+96)[0])


def source_brush(data, offset):
    return dict(world_aabb=struct.unpack_from('<6f', data, offset+4),
                layer=struct.unpack_from('<H', data, offset+28)[0],
                mesh=struct.unpack_from('<H', data, offset+36)[0],
                matrix=struct.unpack_from('<12f', data, offset+40),
                material=struct.unpack_from('<i', data, offset+92)[0])


def terrain_tables(data):
    """Mesh and material path tables (no node or object-tree parsing)."""
    if len(data) < 32: raise Unsupported('Truncated terrain.dat')
    offset = 32; tables = {}
    for name, stride in (('vegetation', 360), ('meshes', 256), ('materials', 256)):
        count = struct.unpack_from('<I', data, offset)[0]; offset += 4
        if count > 1000000 or offset + count*stride > len(data): raise Unsupported('Invalid terrain table')
        tables[name] = [data[offset+i*stride:offset+i*stride+256].split(b'\0', 1)[0].decode('utf-8') for i in range(count)]
        offset += count*stride
    return tables


def cgf_info(blob):
    """Local AABB and material name of a static CGF."""
    if len(blob) < 16 or blob[:4] != b'CrCh': raise Unsupported('Not a chunked CGF')
    count, table = struct.unpack_from('<II', blob, 8)
    if table + count*16 > len(blob): raise Unsupported('Invalid CGF chunk table')
    chunks = {}
    for i in range(count):
        kind, version, ident, size, offset = struct.unpack_from('<HHIII', blob, table + i*16)
        if offset + size > len(blob): raise Unsupported('Truncated CGF chunk')
        chunks[ident] = (kind, version, blob[offset:offset+size])
    meshes = [c for c in chunks.values() if c[0] == 0x1000]
    names = [c for c in chunks.values() if c[0] == 0x1014]
    if len(meshes) != 1: raise Unsupported(f'Expected one mesh chunk, found {len(meshes)}')
    if len(names) != 1: raise Unsupported(f'Expected one material-name chunk, found {len(names)}')
    mesh = meshes[0][2]
    if len(mesh) < 132: raise Unsupported('Short mesh chunk')
    lo, hi = struct.unpack_from('<3f', mesh, 108), struct.unpack_from('<3f', mesh, 120)
    bounds_source = 'mesh_header'
    stream = struct.unpack_from('<I', mesh, 28)[0]
    if stream in chunks and chunks[stream][0] == 0x1016:
        body = chunks[stream][2]
        _, stype, n, width = struct.unpack_from('<4I', body)
        if stype == 0 and width == 12 and len(body) == 24 + n*12 and n:
            pts = list(struct.iter_unpack('<3f', body[24:]))
            lo = tuple(min(p[a] for p in pts) for a in range(3)); hi = tuple(max(p[a] for p in pts) for a in range(3))
            bounds_source = 'float3_vertices'
    if not all(map(math.isfinite, lo + hi)) or any(l > h for l, h in zip(lo, hi)):
        raise Unsupported('Invalid mesh bounds')
    material = names[0][2][:128].split(b'\0', 1)[0].decode('utf-8', 'replace')
    return dict(local_min=lo, local_max=hi, material=material, bounds_source=bounds_source)


def mtl_surfaces(blob):
    root = E.fromstring(blob)
    found = {m.get('SurfaceType') for m in root.iter('Material') if m.get('SurfaceType')}
    return sorted(found)


def surface_table(blob):
    """Native SurfaceTypes.xml -> per-surface physics/barrier semantics."""
    root = E.fromstring(blob)
    result = {}
    for s in root.iter('SurfaceType'):
        phys = s.find('Physics'); barrier = s.find('Barrier'); ai = s.find('AI')
        p = phys.attrib if phys is not None else {}
        result[s.get('name')] = dict(
            player_only=p.get('player_only') == '1', horse_only=p.get('horse_only') == '1',
            has_physics=phys is not None,
            ground_surface=ai is not None and ai.get('movementSpeedMult') is not None,
            barrier=None if barrier is None else dict(distance=float(barrier.get('distance', 0)),
                slowdown=barrier.get('slowdown'), monolog=barrier.get('monologMetaroleId')))
    return result


def blocks(surface):
    """Agents a surface's volume is modelled to block (native flags; runtime unverified)."""
    if surface is None: return None
    if surface['player_only'] and surface['horse_only']: return ['player', 'horse']
    if surface['player_only']: return ['player']
    if surface['horse_only']: return ['horse']
    if surface['ground_surface']: return []  # speed-modifier ground proxy, not a wall (inferred)
    return ['player', 'horse', 'npc']


def roads_from_terrain(data):
    """KCD2 road records (kind 11): paired world-space edge points.

    Layout as in ``region_travel_road.road_spawn_points``; walk via the
    production ``water_volumes.read_water`` object-tree reader.
    """
    from compiled_terrain import parse
    from water_volumes import read_water
    terrain = parse(data)
    if terrain.version != 29: raise Unsupported('Road edges need converted KCD2 terrain (version 29)')
    roads, bad = [], []
    def visit(d, offset, size, kind):
        if kind != 11: return
        v, i, t, p, s = struct.unpack_from('<5I', d, offset+84)
        edges_at = ((offset+112+v*12+i*2+3) & ~3) + t*16 + p*40
        if s < 4 or s % 2 or edges_at + s*12 > offset + size:
            bad.append(dict(offset=offset, reason='unexpected road edge layout')); return
        pts = list(struct.iter_unpack('<3f', d[edges_at:edges_at+s*12]))
        if not all(math.isfinite(x) for q in pts for x in q):
            bad.append(dict(offset=offset, reason='non-finite road edge')); return
        pairs = [(pts[k], pts[k+1]) for k in range(0, s, 2)]
        roads.append(dict(id=f'road@{offset}', center=[tuple((a[j]+b[j])/2 for j in range(3)) for a, b in pairs],
                          widths=[math.dist(a[:2], b[:2]) for a, b in pairs]))
    read_water(terrain, visit)
    return roads, bad


# ---------------------------------------------------------------- mission
def interactions_from_mission(blob):
    root = E.fromstring(blob)
    from .geometry import quat_matrix
    out, classes = [], defaultdict(int)
    for e in root.iter('Entity'):
        cls = e.get('EntityClass')
        if not cls: continue
        classes[cls] += 1
        kind = INTERACTION_CLASSES.get(cls)
        if not kind or not e.get('Pos'): continue
        pos = tuple(map(float, e.get('Pos').split(',')))
        rot = tuple(map(float, (e.get('Rotate') or '1,0,0,0').split(',')))
        props = e.find('Properties'); click = e.find('Properties/Click')
        item = dict(id=e.get('EntityId'), name=e.get('Name'), cls=cls, kind=kind, pos=pos,
                    matrix=quat_matrix(*rot, position=pos))
        if click is not None and click.get('fActiveDistance'): item['active_distance'] = float(click.get('fActiveDistance'))
        if click is not None and click.get('UseMessage'): item['use_message'] = click.get('UseMessage')
        if cls == 'Ladder' and props is not None and props.get('height'): item['height'] = float(props.get('height'))
        out.append(item)
    return out, dict(sorted(classes.items()))


# ---------------------------------------------------------------- package
LEVEL = 'Levels/kcd1_travel'


def _resolve_surface(files, native_files, material, cache):
    key = _norm(material).removesuffix('.mtl') + '.mtl'
    if key in cache: return cache[key]
    for f, origin in ((files, 'package'), (native_files, 'target')):
        if f is not None and f.has(key):
            s = mtl_surfaces(f.read(key)); cache[key] = (s, origin + ':' + key); return cache[key]
    cache[key] = (None, 'missing:' + key)
    return cache[key]


def designer_volumes(brushes, meshes, materials, mesh_files, files, native_files, origin, select=None):
    """Turn brush records into oriented volumes. Unresolved inputs are UNSUPPORTED."""
    volumes, unsupported, cgf_cache, mtl_cache = [], [], {}, {}
    for offset, r in brushes:
        if r['mesh'] >= len(meshes):
            unsupported.append(dict(item=f'{origin}@{offset}', reason='mesh index outside table')); continue
        path = meshes[r['mesh']]; low = _norm(path)
        mat = materials[r['material']] if 0 <= r['material'] < len(materials) else ''
        if not (any(m in low for m in DESIGNER_MESH_MARKERS) or PROXY_MATERIAL_MARKER in _norm(mat)): continue
        if select is not None and not select(r, path, mat): continue
        vid = f'{origin}@{offset}'
        try:
            if low not in cgf_cache:
                key = mesh_files(low)
                cgf_cache[low] = cgf_info(files.read(key, record=False))
            info = cgf_cache[low]
        except (KeyError, Unsupported) as exc:
            unsupported.append(dict(item=vid, mesh=path, reason='mesh unresolved: ' + str(exc))); continue
        material = mat or info['material']
        surfaces, where = _resolve_surface(files, native_files, material, mtl_cache)
        if not surfaces or len(surfaces) != 1:
            unsupported.append(dict(item=vid, mesh=path, material=material,
                                    reason=f'surface type unresolved or mixed ({where}: {surfaces})')); continue
        if not all(map(math.isfinite, r['matrix'])):
            unsupported.append(dict(item=vid, reason='non-finite transform')); continue
        volumes.append(dict(id=vid, origin=origin, mesh=path, material=material, material_file=where,
                            surface=surfaces[0], layer=r['layer'], matrix=tuple(r['matrix']),
                            local_min=info['local_min'], local_max=info['local_max'],
                            bounds_source=info['bounds_source'], world_aabb=tuple(r['world_aabb'])))
    return volumes, unsupported


def native_files(target):
    if target is None: return None
    f = Files(); pak = Path(target) / 'Data' / 'IPL_GameData.pak'
    if not pak.exists(): raise Unsupported('Target has no Data/IPL_GameData.pak')
    f.add_pak(pak)
    return f


def load_surfaces(native, override=None):
    if override is not None: return override, None
    if native is None or not native.has(SURFACE_TABLE):
        raise Unsupported('Native SurfaceTypes.xml unavailable (pass --target)')
    return surface_table(native.read(SURFACE_TABLE)), 'IPL_GameData.pak:' + SURFACE_TABLE


def load_package(package, target=None, kcd1=None, with_roads=True):
    """Build the normalized world from a finished package (read-only)."""
    package = Path(package)
    data_dir = package / 'Data' if (package / 'Data').is_dir() else package
    files = Files()
    level_dir = data_dir / LEVEL
    for name in ('level.pak', 'terrain.pak'):
        if not (level_dir / name).exists(): raise Unsupported(f'Missing {LEVEL}/{name}')
        files.add_pak(level_dir / name)
    for pak in sorted(data_dir.glob('*.pak')): files.add_pak(pak)
    native = native_files(target)
    world = dict(source=str(package.resolve()), extent=None, volumes=[], interactions=[], roads=[],
                 unsupported=[], entity_classes={}, notes=[])
    world['surfaces'], world['surface_table'] = load_surfaces(native)
    terrain = files.read('terrain/terrain.dat')
    grid = struct.unpack_from('<I', terrain, 8)[0]
    unit = struct.unpack_from('<f', terrain, 12)[0]
    world['extent'] = (0.0, 0.0, grid*unit, grid*unit)
    tables = terrain_tables(terrain)
    hl = files.read('terrain/hlods.dat')
    brushes = [(o, package_brush(hl, o)) for o, k in walk_hlods(hl) if k == 1]
    world['placed_brushes'] = len(brushes)
    world['volumes'], world['unsupported'] = designer_volumes(
        brushes, tables['meshes'], tables['materials'], lambda p: p, files, native, 'package')
    world['interactions'], world['entity_classes'] = interactions_from_mission(files.read('objects_mission0.xml'))
    if with_roads:
        try:
            world['roads'], bad = roads_from_terrain(terrain)
            world['unsupported'] += [dict(item=f"road@{b['offset']}", reason=b['reason']) for b in bad]
        except (Unsupported, ValueError) as exc:
            world['unsupported'].append(dict(item='roads', reason=str(exc)))
    world['hashes'] = dict(files.hashes)
    if kcd1 is not None:
        add_kcd1_source(world, kcd1, native)
    if native: world['hashes'].update(native.hashes)
    files.close()
    return world


def add_kcd1_source(world, kcd1, native):
    """Reconstruct the pre-policy placement: every KCD1 designer collision volume.

    Used as the ef8f35a/cadcf08 regression fixture; never a claim about the package.
    """
    from compiled_terrain import parse
    from water_volumes import read_water
    src = Files(); pak = Path(kcd1) / 'Data' / 'Levels' / 'rataje' / 'level.pak'
    src.add_pak(pak)
    for shared in sorted((Path(kcd1) / 'Data').glob('*.pak')):  # engine primitives (objects/default/...)
        try: src.add_pak(shared)
        except zipfile.BadZipFile: pass
    data = src.read('terrain/terrain.dat')
    terrain = parse(data)
    tables = terrain.tables
    brushes = []
    def visit(d, offset, size, kind):
        if kind == 1: brushes.append((offset, source_brush(d, offset)))
    read_water(terrain, visit)
    vols, bad = designer_volumes(brushes, tables['meshes']['paths'], tables['materials']['paths'],
                                 lambda p: p.removeprefix('%level%/'), src, native, 'kcd1_source',
                                 select=lambda r, path, mat: PROXY_MATERIAL_MARKER in _norm(mat))
    world['source_volumes'] = vols
    world['unsupported'] += bad
    world.setdefault('hashes', {}).update(src.hashes)
    src.close()
