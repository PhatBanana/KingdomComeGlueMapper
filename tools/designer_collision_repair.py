"""Invisible designer physics and source-identified duplicate door blockers."""
from collections import Counter
import json
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as E
import zipfile

from upgrade_map import read, xml


def hide_proxy(root):
    """Use the native Nodraw shader; retain authored physics SurfaceType.

    Match the audited proxy texture, including the asset packer's renamed copy.
    Never infer collision-only geometry from colour, opacity or location.
    """
    changed = 0
    for node in root.iter('Material'):
        textures = node.find('Textures')
        if textures is None or not any(
            Path(t.get('File', '').replace('\\', '/')).stem.lower().endswith('collision_proxy')
            for t in textures):
            continue
        if not node.get('SurfaceType', '').startswith('mat_'):
            raise ValueError('Collision proxy without a physics surface')
        # Rendering contract from KCD2 Materials/special/nodraw.mtl. Surface
        # and geometry are deliberately retained, rather than hidden entities.
        for key, value in dict(Shader='Nodraw', MtlFlags='525312', GenMask='0',
                               StringGenMask='', Opacity='1', VoxelCoverage='0').items():
            node.set(key, value)
        textures.clear()
        changed += 1
    return changed


def door_blockers(source, mission):
    """Only source horse blockers sharing a registered door's authored origin."""
    from chairs import inventory
    from entity_visuals import world_transform
    from compiled_terrain import parse
    from water_volumes import read_water
    from building_brushes import read_brush, is_collision_designer
    entities, doors, _ = inventory(source, 'AnimDoor')
    registered = {n.get('Name'): n for n in mission.iter('Entity') if n.get('EntityClass') == 'AnimDoor'}
    origins = []
    for door in doors:
        name = 'gm_door_' + door.get('EntityId')
        if name not in registered:
            continue
        pos, _, _ = world_transform(door, entities)
        actual = tuple(map(float, registered[name].get('Pos').split(',')))
        if math.dist(pos, actual) < .002:
            origins.append((pos, name))
    terrain = parse(read(source, 'terrain/terrain.dat'))
    found = []
    def visit(data, offset, size, kind):
        if kind != 1: return
        r = read_brush(data, offset, terrain.tables['meshes']['paths'], terrain.tables['materials']['paths'])
        material = terrain.tables['materials']['paths'][r['material']] if r['material'] >= 0 else ''
        if not is_collision_designer(r['path'], material) or material.lower().removesuffix('.mtl') != 'materials/special/collision_proxy_horseonly': return
        matches = [name for pos, name in origins if math.dist(pos, r['position']) < .002]
        if len(matches) > 1: raise ValueError('Ambiguous door blocker ownership')
        if matches:
            found.append(dict(position=r['position'], bbox=struct.unpack_from('<6f', data, offset+4),
                              door=matches[0], source_mesh=r['path']))
    read_water(terrain, visit)
    return found


def upgrade(package, source):
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    from world_brush_edits import edit
    from lod_ratio_metadata import MARKER, validate_marker, marker_for
    package = Path(package)
    changed = {}; materials = 0
    for path in sorted((package/'Data').glob('*.pak')):
        replacements = {}
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if not name.lower().endswith('.mtl'): continue
                blob = read(z, name)
                if b'collision_proxy' not in blob.lower(): continue
                root = E.fromstring(blob)
                count = hide_proxy(root)
                if count: replacements[name] = xml(root); materials += count
        if replacements:
            rel = path.relative_to(package).as_posix()
            rewrite(package, rel, replacements); changed[rel] = digest(path)
    level = 'Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(package/level) as z:
        mission = E.fromstring(read(z, 'objects_mission0.xml'))
        data = read(z, 'terrain/hlods.dat'); metadata = read(z, 'terrain/hlods.xml')
        marker = json.loads(read(z, MARKER)) if MARKER in z.namelist() else None
    with zipfile.ZipFile(Path(source)/'Data/Levels/rataje/level.pak') as z:
        candidates = door_blockers(z, mission)
    # An old or fresh package may contain only a subset of source layers.
    # Match complete source bounds as well as origin; leave unrelated brushes.
    edits = []; cursor = 4
    while cursor < len(data):
        end = cursor + 4 + struct.unpack_from('<I', data, cursor)[0]; cursor += 4
        while cursor < end:
            kind = struct.unpack_from('<I', data, cursor)[0]
            if kind == 1:
                matrix = struct.unpack_from('<12f', data, cursor+44)
                pos = tuple(matrix[i] for i in (3,7,11)); bounds = struct.unpack_from('<6f', data, cursor+4)
                matches = [r for r in candidates if math.dist(pos,r['position']) < .002 and
                           max(abs(a-b) for a,b in zip(bounds,r['bbox'])) < .002]
                if len(matches)>1: raise ValueError('Ambiguous source collision placement')
                if matches: edits.append(matches[0])
            cursor += {1:104, 2:64}[kind]
    if edits:
        result, meta = edit(data, metadata, edits)
        replacements = {'terrain/hlods.dat':result, 'terrain/hlods.xml':meta}
        if marker:
            with zipfile.ZipFile(package/'Data/Levels/kcd1_travel/terrain.pak') as z:
                terrain = read(z, 'terrain/terrain.dat')
            validate_marker(terrain, data, marker)
            updated = marker_for(terrain, result, marker)
            validate_marker(terrain, result, updated)
            replacements[MARKER] = json.dumps(updated, indent=2).encode()
        rewrite(package, level, replacements); changed[level] = digest(package/level)
    return changed, dict(version=1, hidden_materials=materials, removed_door_blockers=edits,
                         retained_other_collision=True, runtime_verified=False)
