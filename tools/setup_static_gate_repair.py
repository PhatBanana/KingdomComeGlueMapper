"""Open reviewed static access gates using their authored hinge transforms.

This is the same explicit playable-world override as the outer palisade gates.
Animated KCD2 doors are not selected. Source brush identity and geometry are
checked before changing both the visible leaf and its collision bounds.
"""
from contextlib import ExitStack
import hashlib
import itertools
import json
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as E
import zipfile

from upgrade_map import read, xml


SELECTIONS = ((116970320, 'objects/props/doors/wooden_door_a_left.cgf',
               'sv_state0', (708.6268310546875, 3485.499267578125, 59.80217742919922), 1),)


def source_plan(source):
    from compiled_terrain import parse
    from building_brushes import read_brush
    with zipfile.ZipFile(Path(source)/'Data/Levels/rataje/level.pak') as z:
        terrain = parse(read(z, 'terrain/terrain.dat'))
        layers = {int(n.get('Id')): n.get('Name').split('{')[0]
                  for n in E.fromstring(read(z, 'leveldata.xml')).find('Layers')}
    result = []
    for offset, model, layer, position, direction in SELECTIONS:
        row = read_brush(terrain.data, offset, terrain.tables['meshes']['paths'],
                         terrain.tables['materials']['paths'])
        if (row['path'] != model or layers.get(row['layer']) != layer
                or math.dist(row['position'], position) > .001):
            raise ValueError('Reviewed static gate source identity changed')
        result.append(dict(source_offset=offset, source_model=model, source_layer=layer,
                           matrix=struct.unpack_from('<12f', terrain.data, offset+40),
                           bounds=struct.unpack_from('<6f', terrain.data, offset+4),
                           direction=direction))
    return result


def opened(plan):
    matrix = plan['matrix']; direction = plan['direction']
    if direction not in (-1, 1): raise ValueError('Gate opening must be a quarter turn')
    x, y, _ = matrix[3::4]
    target = list(matrix)
    for j in range(3):
        target[j] = -direction*matrix[4+j]
        target[4+j] = direction*matrix[j]
    bounds = plan['bounds']
    corners = [(x-direction*(py-y), y+direction*(px-x), pz)
               for px, py, pz in itertools.product(*[(bounds[j], bounds[j+3]) for j in range(3)])]
    return target, tuple(min(p[j] for p in corners) for j in range(3)) + tuple(max(p[j] for p in corners) for j in range(3))


def apply(data, metadata, plans, meshes, check_model):
    from vegetation import verify_target_hlods
    verify_target_hlods(data)
    root = E.fromstring(metadata); output = bytearray(data)
    found = set(); changed = 0
    close = lambda a, b: len(a) == len(b) and all(abs(x-y) < .0003 for x,y in zip(a,b))
    for group in root.iter('HLod'):
        start = int(group.get('DataOffset')); end = start+int(group.get('DataSize'))
        if end > len(data) or struct.unpack_from('<I', data, start)[0] != end-start-4:
            raise ValueError('Static gate HLOD metadata mismatch')
        cursor = start+4
        while cursor < end:
            kind = struct.unpack_from('<I', data, cursor)[0]
            if kind == 1:
                matrix = struct.unpack_from('<12f', data, cursor+44)
                for i, plan in enumerate(plans):
                    if math.dist(matrix[3::4], plan['matrix'][3::4]) >= .001: continue
                    if i in found: raise ValueError('Duplicate static gate placement')
                    found.add(i)
                    check_model(meshes[struct.unpack_from('<H', data, cursor+40)[0]], plan['source_model'])
                    target, bounds = opened(plan)
                    actual_bounds = struct.unpack_from('<6f', data, cursor+4)
                    if close(matrix, target) and close(actual_bounds, bounds): continue
                    if not close(matrix, plan['matrix']) or not close(actual_bounds, plan['bounds']):
                        raise ValueError('Static gate transform or collision bounds conflict')
                    struct.pack_into('<12f', output, cursor+44, *target)
                    struct.pack_into('<6f', output, cursor+4, *bounds)
                    # Conservatively expand the existing cluster by the leaf's
                    # maximum hinge displacement. Never reduce streaming bounds.
                    hinge = matrix[3::4]
                    radius = max(math.dist(hinge, p) for p in itertools.product(
                        *[(plan['bounds'][j], plan['bounds'][j+3]) for j in range(3)]))
                    group.set('Radius', str(float(group.get('Radius'))+2*radius))
                    changed += 1
            cursor += {1:104, 2:64}[kind]
        if cursor != end: raise ValueError('Static gate HLOD record boundary mismatch')
    if len(found) != len(plans): raise ValueError('Missing reviewed static access gate')
    return bytes(output), xml(root) if changed else metadata, changed


def upgrade(package, source, target):
    from build_open_test_gates import source_geometry
    from clothing_regions import read_chunks
    from compiled_terrain import parse
    from mesh_lod_metadata import normalize
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    from lod_ratio_metadata import MARKER, validate_marker
    package = Path(package)
    if source is None: raise ValueError('KCD1 is required to validate static access gates')
    plans = source_plan(source)
    level = 'Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(package/'Data/Levels/kcd1_travel/terrain.pak') as z:
        terrain = read(z, 'terrain/terrain.dat')
        meshes = parse(terrain).tables['meshes']['paths']
    with zipfile.ZipFile(package/level) as z:
        data, metadata = (read(z,n) for n in ('terrain/hlods.dat','terrain/hlods.xml'))
        marker = json.loads(read(z, MARKER)) if MARKER in z.namelist() else None
    if marker is not None:
        validate_marker(terrain, data, marker)
    originals = source_geometry(source, {p['source_model'] for p in plans})
    def signature(blob):
        return hashlib.sha256(b''.join(struct.pack('<HHI',c.kind,c.version,c.id)+c.data
                             for c in read_chunks(blob) if c.kind != 0x1014)).digest()
    with ExitStack() as stack:
        assets = {}
        for path in sorted((package/'Data').glob('*.pak')):
            archive = stack.enter_context(zipfile.ZipFile(path))
            for name in archive.namelist():
                if name.lower().endswith('.cgf'): assets.setdefault(name.lower(), []).append((archive,name))
        def check_model(converted, original):
            candidates = assets.get(converted.lower(), [])
            if len(candidates) != 1: raise ValueError('Missing or ambiguous static gate mesh: '+converted)
            actual = signature(read(*candidates[0])); source_blob = originals[original]
            if actual != signature(source_blob) and actual != signature(normalize(source_blob)):
                raise ValueError('Static gate geometry differs from reviewed source: '+original)
        updated, hierarchy, count = apply(data, metadata, plans, meshes, check_model)
    files = {}
    if count:
        rewrite(package,level,replacements(terrain, data, updated, hierarchy, marker))
        files[level] = digest(package/level)
    return files, dict(version=1, opened=count, gates=plans, runtime_passage_verified=False)


def replacements(terrain, previous, updated, hierarchy, marker):
    """Refresh only a previously valid LOD receipt after a geometry-only edit."""
    from lod_ratio_metadata import MARKER, validate_marker, marker_for
    result = {'terrain/hlods.dat':updated, 'terrain/hlods.xml':hierarchy}
    if marker is not None:
        validate_marker(terrain, previous, marker)
        refreshed = marker_for(terrain, updated, marker)
        validate_marker(terrain, updated, refreshed)
        result[MARKER] = json.dumps(refreshed, indent=2).encode()
    return result
