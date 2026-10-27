"""Stage a terrain.pak copy that adds deferred decals over imported puddle quads.

Read-only on the installed mod: the result is a new terrain.pak under
--output plus report.json. Only terrain/terrain.dat changes (material table
grows; new kind 7 records are inserted with the native octree rules). Brushes,
materials and textures are untouched. See puddle_decals.py for the cause.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from compiled_terrain import parse
from geometry_opacity import cgf_triangles
from landscape_surfaces import append_surfaces
from puddle_decals import decal_record, planar_quad, sort_priority
from puddle_materials import puddle_decal_slots
from terrain_object_tree import read_tree
from upgrade_map import read

LEVEL = 'Data/Levels/kcd1_travel/level.pak'
TERRAIN = 'Data/Levels/kcd1_travel/terrain.pak'


def brushes(hlods):
    """Yield (offset, mesh index, material override, row-major 3x4 matrix)."""
    cursor = 4
    while cursor < len(hlods):
        end = cursor + 4 + struct.unpack_from('<I', hlods, cursor)[0]
        cursor += 4
        while cursor < end:
            kind = struct.unpack_from('<I', hlods, cursor)[0]
            if kind == 1:
                yield (cursor, struct.unpack_from('<H', hlods, cursor + 40)[0],
                       struct.unpack_from('<i', hlods, cursor + 96)[0],
                       struct.unpack_from('<12f', hlods, cursor + 44))
            elif kind != 2:
                raise ValueError(f'Unknown HLOD record kind {kind}')
            cursor += 104 if kind == 1 else 64


class Assets:
    def __init__(self, data):
        self.entries = {}
        self.archives = []
        for path in sorted(Path(data).glob('*.pak')):
            archive = zipfile.ZipFile(path)
            self.archives.append(archive)
            for name in archive.namelist():
                key = name.replace('\\', '/').lower()
                if key.endswith(('.cgf', '.mtl')):
                    self.entries.setdefault(key, (archive, name))

    def get(self, name):
        archive, entry = self.entries[name.lower()]
        return read(archive, entry)

    def close(self):
        for archive in self.archives:
            archive.close()


def puddle_quad(assets, mesh):
    """(material path, sort priority, quad) for a qualifying puddle mesh, else None."""
    if mesh.lower() not in assets.entries:
        return None
    triangles, info = cgf_triangles(assets.get(mesh), with_surface=True, allow_empty=True)
    surfaces = info['surfaces']
    if len(surfaces) != 1 or not surfaces[0]['material']:
        return None
    material_path = surfaces[0]['material'].replace('\\', '/').lower().removesuffix('.mtl')
    if material_path + '.mtl' not in assets.entries:
        return None
    material = ET.fromstring(assets.get(material_path + '.mtl'))
    visible = puddle_decal_slots(material)
    if not visible:
        return None
    slots = material.findall('SubMaterials/Material')
    ids = {slots.index(slot) for slot in visible}
    mask = np.isin(surfaces[0]['material_ids'], sorted(ids))
    if not mask.all():
        return None  # visible puddle mixed with other render geometry
    quad = planar_quad(np.asarray(triangles)[mask], surfaces[0]['uv'][mask])
    if quad is None:
        return None
    return material_path, sort_priority(material), quad


def overlay(mod, centre=None, radius=None):
    mod = Path(mod)
    with zipfile.ZipFile(mod / TERRAIN) as archive:
        terrain_blob = read(archive, 'terrain/terrain.dat')
    with zipfile.ZipFile(mod / LEVEL) as archive:
        hlods = read(archive, 'terrain/hlods.dat')
    terrain = parse(terrain_blob)
    meshes = terrain.tables['meshes']['paths']
    table = list(terrain.tables['materials']['paths'])
    existing = {blob for node in read_tree(terrain)[1] for kind, blob in node.records if kind == 7}
    assets = Assets(mod / 'Data')
    try:
        cache, records, materials, rows = {}, [], [], []
        skipped = dict(override=0)
        for offset, mesh_index, override, matrix in brushes(hlods):
            if mesh_index >= len(meshes):
                raise ValueError('Brush mesh outside resource table')
            position = matrix[3], matrix[7], matrix[11]
            if centre is not None and math.dist(position[:2], centre) > radius:
                continue
            mesh = meshes[mesh_index].replace('\\', '/').lower()
            if not mesh.startswith('gluebuild/'):
                continue
            if mesh not in cache:
                try:
                    cache[mesh] = puddle_quad(assets, mesh)
                except (ValueError, KeyError, struct.error):
                    cache[mesh] = None  # unsupported geometry is never a flat puddle quad
                    skipped['unreadable_meshes'] = skipped.get('unreadable_meshes', 0) + 1
            found = cache[mesh]
            if found is None:
                continue
            if override != -1:
                skipped['override'] += 1
                continue
            material_path, priority, quad = found
            if material_path in table:
                index = table.index(material_path)
            else:
                index = len(table)
                table.append(material_path)
                materials.append(material_path)
            record = decal_record(matrix, quad, index, priority)
            if record in existing:
                raise ValueError('Puddle decal overlay already present')
            records.append(record)
            rows.append(dict(hlod_offset=offset, mesh=mesh, material=material_path,
                             sort_priority=priority, position=[round(v, 3) for v in position],
                             radius=round(struct.unpack_from('<f', record, 108)[0], 3)))
    finally:
        assets.close()
    if not records:
        raise ValueError('No qualifying puddle quads selected')
    result = append_surfaces(terrain, records, materials)
    check = parse(result)
    added = sum(kind == 7 for node in read_tree(check)[1] for kind, _ in node.records) - \
        sum(kind == 7 for node in read_tree(terrain)[1] for kind, _ in node.records)
    if added != len(records) or check.tables['materials']['paths'] != table:
        raise ValueError('Overlay verification failed')
    report = dict(version=1, decals=len(records), new_materials=materials, skipped=skipped,
                  centre=list(centre) if centre is not None else None, radius=radius,
                  terrain_sha256_before=hashlib.sha256(terrain_blob).hexdigest(),
                  terrain_sha256_after=hashlib.sha256(result).hexdigest(), records=rows)
    return result, report


def write_terrain_pak(source, destination, terrain_blob):
    """Copy every member byte-for-byte, replacing only terrain/terrain.dat."""
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(destination, 'x', zipfile.ZIP_STORED, allowZip64=True) as out:
        names = src.namelist()
        if names.count('terrain/terrain.dat') != 1 or len(names) != len(set(names)):
            raise ValueError('Unexpected terrain archive layout')
        for entry in src.infolist():
            out.writestr(entry, terrain_blob if entry.filename == 'terrain/terrain.dat' else read(src, entry.filename))
    with zipfile.ZipFile(destination) as check:
        if check.namelist() != names or read(check, 'terrain/terrain.dat') != terrain_blob:
            raise ValueError('Staged terrain archive verification failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mod', type=Path, required=True, help='installed mod root (read only)')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--centre', help='x,y limit to puddles near this point')
    parser.add_argument('--radius', type=float, default=30.0)
    args = parser.parse_args()
    centre = tuple(map(float, args.centre.split(','))) if args.centre else None
    blob, report = overlay(args.mod, centre, args.radius if centre else None)
    args.output.mkdir(parents=True, exist_ok=False)
    write_terrain_pak(args.mod / TERRAIN, args.output / 'terrain.pak', blob)
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f"Staged {report['decals']} puddle decals")
