"""Restore static shop layers owned by converted, registered market sellers."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import xml.etree.ElementTree as E
import zipfile
import numpy as np
from upgrade_map import read, xml


def owned_layers(mission, entities, layers, template_id):
    points = {e.get('Name').rsplit('_', 1)[-1] for e in mission.iter('Entity')
              if e.get('Name', '').startswith('gm_schedule_') and
              e.find('Properties') is not None and
              e.find('Properties').get('guidSmartObjectType') == template_id}
    selected = {}
    for point in sorted(points):
        areas = [e for e in entities.values() if e.get('EntityClass') == 'SmartAreaShape'
                 and any(l.get('TargetId') == point and 'merchantPoint' in l.get('Name', '').split(',')
                         for l in e.findall('EntityLinks/Link'))]
        if len(areas) != 1:
            raise ValueError('Registered seller has ambiguous source shop: '+point)
        layer = areas[0].get('Layer')
        matches = [e for e in layers if e.get('Name') == layer]
        if len(matches) != 1:
            raise ValueError('Missing authored shop layer: '+str(layer))
        name = layer.split('{')[0]
        # These layers already belong to the static-world importer.
        number = int(matches[0].get('Id'))
        if number and not name.endswith(('_state0', '_state0_prefabs')):
            selected[number] = dict(layer=layer, area=areas[0].get('EntityId'), selling_point=point)
    return selected


def pose(matrix):
    from world_item_placements import rotation
    m = np.array(matrix).reshape(3, 4)
    scales = np.linalg.norm(m[:, :3], axis=0)
    if min(scales) <= 0: raise ValueError('Degenerate shop brush')
    if np.linalg.det(m[:, :3]) < 0: scales[0] *= -1
    return tuple(m[:, 3]), rotation(m[:, :3]/scales), tuple(scales)


def upgrade(package, source, target):
    from chairs import inventory
    from character_market_jobs import contract
    from compiled_terrain import parse
    from water_volumes import read_water
    from building_brushes import read_brush, is_uberlod_proxy
    from game_paths import GameLibrary
    from static_assets import asset_pack
    from room_layout import geometry
    from character_water_work import identity
    from cooking_pots import vector
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    package, source, target = map(Path, (package, source, target))
    level = 'Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(package/level) as z: mission = E.fromstring(read(z, 'objects_mission0.xml'))
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as z:
        entities, _, _ = inventory(z)
        layers = owned_layers(mission, entities, E.fromstring(read(z, 'leveldata.xml')).find('Layers'),
                              contract(target).get('DatabaseId'))
        terrain = parse(read(z, 'terrain/terrain.dat'))
    selected = []
    def collect(data, offset, size, kind):
        if kind != 1: return
        r = read_brush(data, offset, terrain.tables['meshes']['paths'], terrain.tables['materials']['paths'])
        if r['layer'] not in layers or is_uberlod_proxy(r['path']): return
        if r['path'].startswith('%level%/'): return
        r['pose'] = pose(struct.unpack_from('<12f', data, offset+40))
        selected.append(r)
    read_water(terrain, collect)
    existing = {e.get('Name'): e for e in mission}
    pending = sorted((r for r in selected if 'gm_market_brush_'+str(r['offset']) not in existing),
                     key=lambda r:(r['path'], r['material'], r['offset']))
    files = {}
    if pending:
        with ExitStack() as stack:
            cache = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='market-')))
            config = cache/'paths.json'
            config.write_text(json.dumps(dict(schema=1,kcd1=str(source),kcd2=str(target),build=str(cache/'build'))))
            # The packer numbers material/texture dependencies. A later set of
            # newly enabled sellers must not overwrite an earlier batch's m0/t0.
            batch = hashlib.sha256(repr([(r['path'], r['material'], r['offset']) for r in pending]).encode()).hexdigest()[:24]
            prefix = 'gluebuild/market_layers/'+batch+'/'
            index, emitted, material, mesh_bytes = asset_pack(stack, GameLibrary(config), prefix, cache)
            models = {}
            next_id = max(int(e.get('EntityId','0')) for e in mission)+1
            for r in pending:
                override = terrain.tables['materials']['paths'][r['material']] if r['material'] >= 0 else None
                key = (r['path'], override)
                if key not in models:
                    model = prefix+hashlib.sha256(repr(key).encode()).hexdigest()[:24]+'.cgf'
                    emitted[model] = mesh_bytes(r['path'], override)
                    for lod in range(1,7):
                        path = r['path'][:-4]+f'_lod{lod}.cgf'
                        if path in index: emitted[model[:-4]+f'_lod{lod}.cgf'] = mesh_bytes(path, override)
                    models[key] = model
                name = 'gm_market_brush_'+str(r['offset'])
                node = geometry(dict(name=name, model=models[key]))
                p,q,s = r['pose']
                node.attrib.update(Name=name, EntityGuid=identity(name), EntityId=str(next_id),
                                   Pos=vector(p), Rotate=vector(q), Scale=vector(s))
                next_id += 1; mission.append(node)
            archive = 'Data/gluemappertravel.pak'
            rewrite(package,archive,{name:path.read_bytes() for name,path in emitted.items()})
            files[archive] = digest(package/archive)
        rewrite(package,level,{'objects_mission0.xml':xml(mission)})
        files[level] = digest(package/level)
    return files, dict(layers=list(layers.values()), source_brushes=len(selected), restored=len(pending), runtime_verified=False)
