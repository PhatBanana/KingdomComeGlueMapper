"""Independent, bounded geometry-opacity experiment (not an installed GI bake).

Surface coverage is sampled along three world axes. No closed-mesh fill is used:
windows and the empty interior remain empty. This module does not sample material
alpha or produce radiance, albedo, normals, probes, or clipping volumes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zipfile
from collections import OrderedDict

import numpy as np

from clothing_regions import read_chunks
from upgrade_map import read


def transform_triangles(triangles, matrix):
    matrix = np.asarray(matrix, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.float64)
    if matrix.size != 12 or triangles.ndim != 3 or triangles.shape[1:] != (3, 3):
        raise ValueError('Expected triangles and a row-major 3x4 world transform')
    matrix = matrix.reshape(3, 4)
    if not np.isfinite(matrix).all() or not np.isfinite(triangles).all():
        raise ValueError('Non-finite geometry/transform')
    if abs(np.linalg.det(matrix[:, :3])) < 1e-12:
        raise ValueError('Singular world transform')
    return triangles @ matrix[:, :3].T + matrix[:, 3]


def cgf_triangles(blob, with_surface=False, material_override=None, allow_empty=False):
    """Read compiled render meshes and their authored node hierarchy.

    CGFLoader::LoadNodeChunk uses matrix columns and centimetre translations;
    ProcessNodes composes parent matrices. Compiled mesh vertices are metres.
    Physics proxies, attachment helpers and LOD nodes do not contribute twice.
    """
    chunks = read_chunks(blob)
    lookup = {c.id: c for c in chunks}
    matrices = {}
    def node_matrix(identity, visiting=frozenset()):
        if identity in matrices:return matrices[identity]
        if identity in visiting:raise ValueError('Cyclic CGF node hierarchy')
        c = lookup.get(identity)
        if c is None or c.kind != 0x100b or c.version != 0x824 or len(c.data)<204:
            raise ValueError('Missing/unsupported CGF parent node')
        source = np.array(struct.unpack_from('<16f',c.data,84)).reshape(4,4)
        local = np.eye(4)
        local[:3,:3] = source[:3,:3].T
        local[:3,3] = source[3,:3]*.01
        if not np.isfinite(local).all() or abs(np.linalg.det(local[:3,:3]))<1e-12:
            raise ValueError('Invalid CGF node matrix')
        parent = struct.unpack_from('<i',c.data,68)[0]
        if parent>0:local = node_matrix(parent,visiting|{identity}) @ local
        matrices[identity] = local
        return local
    result, bindings, excluded, surfaces = [], [], [], []
    default_material_nodes = []
    for node in (c for c in chunks if c.kind == 0x100b):
        if node.version != 0x824 or len(node.data) < 204:
            raise ValueError('Unsupported CGF node')
        name = node.data[:64].split(b'\0')[0].decode('utf-8')
        if name.lower().startswith(('$physics', '$lod')):
            excluded.append(name)
            continue
        mesh_id, parent, _, material_id = struct.unpack_from('<4i', node.data, 64)
        mesh = lookup.get(mesh_id)
        if mesh is not None and mesh.kind == 0x1001:
            # Authored attachment/placement helper, not render geometry.
            excluded.append(name)
            continue
        if mesh is None or mesh.kind != 0x1000:
            raise ValueError('Unsupported non-mesh render node: '+name)
        tm = node_matrix(node.id)
        if mesh.version not in (0x800, 0x801) or len(mesh.data) != 264:
            raise ValueError('Unsupported compiled mesh')
        flags, _, nv, ni, ns, sid = struct.unpack_from('<6I', mesh.data)
        if flags & 1 or not nv or not ni or ni % 3:
            raise ValueError('Empty or malformed render mesh')
        ids = struct.unpack_from('<16I', mesh.data, 28)

        def stream(kind, count):
            c = lookup.get(ids[kind])
            if c is None:
                raise ValueError('Missing required CGF stream: '+str(kind))
            if c.kind != 0x1016 or c.version != 0x800 or len(c.data) < 24:
                raise ValueError('Unsupported CGF stream')
            _, k, n, width = struct.unpack_from('<4I', c.data)
            if k != kind or n != count or len(c.data) != 24+n*width:
                raise ValueError('CGF stream count/size mismatch')
            return c.data[24:], width

        packed_uv = None
        pos_chunk = lookup.get(ids[15])
        if pos_chunk is not None and pos_chunk.kind == 0x1016 and len(pos_chunk.data) >= 24 and struct.unpack_from('<I',pos_chunk.data,4)[0] == 15:
            # P3S_C4B_T2S: half4 position, RGBA8 colour, half2 UV.
            data, width = stream(15, nv)
            if width != 16:raise ValueError('Unsupported interleaved vertex format')
            values = np.frombuffer(data, '<f2').reshape(nv,8)
            positions = values[:,:3].astype(float)
            packed_uv = values[:,6:8].astype(float)
        else:
            data, width = stream(0, nv)
            if width not in (8, 12):
                raise ValueError('Unsupported position format')
            positions = np.frombuffer(data, '<f2' if width == 8 else '<f4').reshape(nv, 4 if width == 8 else 3)[:, :3].astype(np.float64)
        data, width = stream(5, ni)
        if width not in (2, 4):
            raise ValueError('Unsupported index format')
        indices = np.frombuffer(data, '<u2' if width == 2 else '<u4')
        if indices.max() >= nv:
            raise ValueError('CGF index outside vertex array')
        subset = lookup[sid]
        if subset.kind != 0x1017 or subset.version != 0x800 or len(subset.data) < 16+ns*36:
            raise ValueError('Unsupported subsets')
        covered = np.zeros(ni, dtype=bool)
        used_materials = set()
        material_counts = {}
        face_materials = np.empty(ni//3, dtype=np.uint32)
        for i in range(ns):
            first, count, _, _, mat = struct.unpack_from('<5I', subset.data, 16+36*i)
            if first % 3 or count % 3 or first+count > ni or covered[first:first+count].any():
                raise ValueError('Overlapping/invalid subset index range')
            covered[first:first+count] = True
            face_materials[first//3:(first+count)//3] = mat
            used_materials.add(mat)
            material_counts[mat] = material_counts.get(mat, 0)+count//3
        if not covered.all():
            raise ValueError('Unassigned render triangles')
        material = lookup.get(material_id)
        if material_override:
            material_name = material_override
        elif material_id <= 0 and not any(c.kind == 0x1014 for c in chunks):
            # Unassigned source geometry (for example fabric_burned.cgf).
            # Retain its surfaces with the game's default material, and record
            # this explicitly. Never use this for a broken positive chunk ID.
            material_name = 'materials/material_default'
            face_materials[:] = 0
            used_materials = {0}
            material_counts = {0: ni//3}
            default_material_nodes.append(name)
        else:
            if material is None or material.kind != 0x1014 or material.version != 0x802:
                raise ValueError('Unsupported material binding')
            material_name = material.data[:128].split(b'\0')[0].decode('utf-8')
        result.append(transform_triangles(positions[indices.reshape(-1, 3)],tm[:3].reshape(-1)))
        if with_surface:
            if packed_uv is not None:
                uv = packed_uv
            else:
                data, width = stream(2, nv)
                if width not in (4, 8):
                    raise ValueError('Unsupported UV format')
                uv = np.frombuffer(data, '<f2' if width == 4 else '<f4').reshape(nv, 2)
            if not np.isfinite(uv).all():
                raise ValueError('Non-finite UV coordinates')
            surfaces.append({'uv': uv[indices.reshape(-1, 3)].astype(float),
                             'material_ids': face_materials, 'material': material_name})
        bindings.append({'node': name, 'material': material_name, 'subsets': sorted(used_materials),
                         'subset_triangles': material_counts, 'triangles': ni//3})
    if not result and not allow_empty:
        raise ValueError('No supported render triangles')
    info = {'bindings': bindings, 'excluded_nodes': excluded,
            'default_material_nodes': default_material_nodes}
    if with_surface:
        info['surfaces'] = surfaces
    return np.concatenate(result) if result else np.empty((0,3,3)), info


def coverage(triangles, origin, shape, cell_size, samples=4):
    """Return [z,y,x,axis] uint8 projected surface coverage.

    Each axis uses samples**2 subpixel rays per cell face. Duplicate/overlapping
    triangles union their sample bits, rather than double-counting opacity.
    Exact boundaries use half-open cells. Very thin subpixel geometry can be
    missed; this is a sampling experiment, not conservative solid voxelization.
    """
    triangles = np.asarray(triangles, dtype=np.float64)
    origin = np.asarray(origin, dtype=np.float64)
    shape_array = np.asarray(shape)
    if shape_array.shape != (3,) or not np.isfinite(shape_array).all() or np.any(shape_array != np.floor(shape_array)):
        raise ValueError('Grid shape must contain three integer dimensions')
    shape = tuple(int(x) for x in shape_array)
    if min(shape) < 1 or max(shape) > 256 or np.prod(shape) > 256**3:
        raise ValueError('Grid exceeds bounded experiment size')
    if samples not in (1, 2, 4, 8) or not np.isfinite(cell_size) or cell_size <= 0:
        raise ValueError('Invalid sample count/cell size')
    if origin.shape != (3,) or not np.isfinite(origin).all() or triangles.ndim != 3 or triangles.shape[1:] != (3, 3) or not np.isfinite(triangles).all():
        raise ValueError('Invalid geometry/grid origin')
    local = (triangles-origin)/cell_size
    output = np.zeros((*shape[::-1], 3), dtype=np.uint8)
    popcounts = np.array([i.bit_count() for i in range(256)], dtype=np.uint8)
    for axis in range(3):
        u, v = [k for k in range(3) if k != axis]
        bits = np.zeros(shape[::-1], dtype=np.uint64)
        for triangle in local:
            low = np.maximum(np.ceil(triangle[:, [u, v]].min(axis=0)*samples-.5).astype(int), 0)
            high = np.minimum(np.floor(triangle[:, [u, v]].max(axis=0)*samples-.5).astype(int), np.array([shape[u], shape[v]])*samples-1)
            if np.any(high < low):
                continue
            a, b, c = triangle
            det = (b[u]-a[u])*(c[v]-a[v])-(c[u]-a[u])*(b[v]-a[v])
            if abs(det) < 1e-12:
                continue
            # Restrict temporary allocations even for a large projected face.
            us = np.arange(low[0], high[0]+1)
            for start in range(low[1], high[1]+1, 64):
                vs = np.arange(start, min(start+64, high[1]+1))
                iu, iv = np.meshgrid(us, vs)
                du, dv = (iu+.5)/samples-a[u], (iv+.5)/samples-a[v]
                beta = (du*(c[v]-a[v])-dv*(c[u]-a[u]))/det
                gamma = ((b[u]-a[u])*dv-(b[v]-a[v])*du)/det
                depth = a[axis]+beta*(b[axis]-a[axis])+gamma*(c[axis]-a[axis])
                hit = (beta >= -1e-10) & (gamma >= -1e-10) & (beta+gamma <= 1+1e-10) & (depth >= 0) & (depth < shape[axis])
                if not hit.any():
                    continue
                coords = [None]*3
                coords[u], coords[v] = iu[hit]//samples, iv[hit]//samples
                coords[axis] = np.floor(depth[hit]).astype(int)
                bit = (iu[hit] % samples) + samples*(iv[hit] % samples)
                np.bitwise_or.at(bits, tuple(coords[::-1]), np.left_shift(np.uint64(1), bit.astype(np.uint64)))
        counts = popcounts[bits.view(np.uint8).reshape(*bits.shape, 8)].sum(axis=-1)
        output[..., axis] = np.rint(counts*255/(samples*samples)).astype(np.uint8)
    return output


class Assets:
    def __init__(self, folder, overrides=()):
        self.entries = {}
        self._archives = OrderedDict()
        for path in sorted(Path(folder).glob('*.pak')):
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    key = name.replace('\\', '/').lower()
                    # Ambiguous archive precedence must be resolved explicitly.
                    if key in self.entries:
                        self.entries[key] = None
                    else:
                        self.entries[key] = (path, name)
        # Built-in textures (including the default material's grey texture)
        # live outside Data. Use Engine assets only where Data has no entry.
        engine = Path(folder).parent/'Engine/Engine.pak'
        if engine.is_file():
            with zipfile.ZipFile(engine) as archive:
                for name in archive.namelist():
                    self.entries.setdefault(name.replace('\\','/').lower(), (engine,name))
        # Explicit runtime override packages, in precedence order. Never infer
        # precedence from alphabetical package names when content conflicts.
        for override in overrides:
            path=Path(override)
            if not path.is_absolute():path=Path(folder)/path
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    self.entries[name.replace('\\','/').lower()] = (path,name)

    def catalog_digest(self):
        """Fingerprint archive entries and explicit precedence for resume checks."""
        digest=hashlib.sha256()
        paths=sorted({entry[0] for entry in self.entries.values() if entry is not None})
        for path in paths:
            with zipfile.ZipFile(path) as archive:
                for entry in archive.infolist():
                    key=entry.filename.replace('\\','/').lower()
                    if self.entries.get(key)==(path,entry.filename):
                        digest.update((key+'|'+str(path)+'|'+str(entry.CRC)+'|'+str(entry.file_size)+'\n').encode())
        return digest.hexdigest()

    def get(self, name):
        key = name.replace('\\', '/').lower()
        entry = self.entries.get(key)
        if entry is None:
            raise ValueError('Missing or ambiguous asset: '+name)
        path=entry[0]
        if path not in self._archives:
            self._archives[path]=zipfile.ZipFile(path)
            while len(self._archives)>8:
                _,old=self._archives.popitem(last=False);old.close()
        self._archives.move_to_end(path)
        return read(self._archives[path],entry[1])

    def close(self):
        for archive in self._archives.values():archive.close()
        self._archives.clear()

    def __del__(self):
        if hasattr(self,'_archives'):self.close()


def load_scene(records, assets):
    geometry, audit = [], []
    for record in records:
        blob = assets.get(record['mesh'])
        triangles, info = cgf_triangles(blob)
        triangles = transform_triangles(triangles, record['transform'])
        geometry.append(triangles)
        info.update(mesh=record['mesh'], sha256=hashlib.sha256(blob).hexdigest(), transform=record['transform'])
        info['materials'] = []
        for binding in info['bindings']:
            name = record.get('material') or binding['material']
            material_blob = assets.get(name if name.endswith('.mtl') else name+'.mtl')
            root = ET.fromstring(material_blob)
            submaterials = root.find('SubMaterials')
            materials = list(submaterials) if submaterials is not None else [root]
            for index in binding['subsets']:
                if index >= len(materials):
                    raise ValueError('Material subset out of range')
                attributes = dict(materials[index].attrib)
                reasons = []
                if float(attributes.get('AlphaTest', 0)) > 0:
                    reasons.append('alpha-test texture sampling required')
                if float(attributes.get('Opacity', 1)) < 1:
                    reasons.append('partial opacity')
                if '%DECAL' in attributes.get('StringGenMask', ''):
                    reasons.append('decal; not an independent solid occluder')
                if 'shadowproxy' in attributes.get('Name', '').lower():
                    reasons.append('shadow-only proxy policy requires native verification')
                info['materials'].append({'binding': name, 'subset': index,
                    'triangles': binding['subset_triangles'][index],
                    'requires_material_policy': reasons, 'attributes': attributes})
        audit.append(info)
    if not geometry:
        raise ValueError('Empty scene')
    return np.concatenate(geometry), audit


def preview(field, destination, cell_size):
    """Three axis projections of geometry coverage; no simulated game lighting."""
    from PIL import Image, ImageDraw, ImageFont
    canvas = Image.new('RGB', (1200, 520), '#111827')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    small = ImageFont.load_default(size=14)
    draw.text((24, 16), 'Independent geometry opacity - building fixture', fill='white', font=font)
    draw.text((24, 46), f'{cell_size:g} m cells | world-axis projections | brighter = greater sampled coverage', fill='#cbd5e1', font=small)
    labels = ['Looking along X (Y / Z)', 'Looking along Y (X / Z)', 'Looking along Z (X / Y)']
    for axis in range(3):
        array = field[..., axis].max(axis=2-axis)
        color = np.zeros((*array.shape, 3), np.uint8)
        for c, value in enumerate((96, 205, 240)):
            color[..., c] = (array.astype(float)/255*value).astype(np.uint8)
        # Preserve world aspect ratio rather than stretching each projection.
        scale = min(360/array.shape[1], 350/array.shape[0])
        picture = Image.fromarray(color[::-1]).resize((round(array.shape[1]*scale), round(array.shape[0]*scale)), Image.Resampling.NEAREST)
        x = 20+axis*400
        draw.text((x, 92), labels[axis], fill='white', font=small)
        canvas.paste(picture, (x, 125))
    draw.text((24, 480), 'Geometry test only: material alpha, shadow-proxy policy and native equivalence are not validated.', fill='#fbbf24', font=small)
    canvas.save(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--pak-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cell-size', type=float, default=.25)
    parser.add_argument('--samples', type=int, choices=(1, 2, 4, 8), default=4)
    parser.add_argument('--geometry-only', action='store_true', required=True,
                        help='Acknowledge that material alpha/GI are not baked; produces diagnostic NPZ only')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output directory to preserve earlier evidence')
    if not np.isfinite(args.cell_size) or args.cell_size <= 0:
        parser.error('Cell size must be finite and positive')
    triangles, audit = load_scene(json.loads(args.manifest.read_text()), Assets(args.pak_root))
    low, high = triangles.min(axis=(0, 1)), triangles.max(axis=(0, 1))
    origin = np.floor(low/args.cell_size)*args.cell_size-args.cell_size
    shape = np.ceil((high-origin)/args.cell_size).astype(int)+1
    field = coverage(triangles, origin, shape, args.cell_size, args.samples)
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output/'opacity.npz', coverage_xyz=field, origin=origin, cell_size=args.cell_size, triangles=triangles)
    preview(field, args.output/'coverage.png', args.cell_size)
    occupied = np.any(field, axis=-1)
    report = {'status': 'geometry-only experiment; native equivalence not established',
              'origin_xyz': origin.tolist(), 'shape_xyz': shape.tolist(), 'cell_size': args.cell_size,
              'samples_per_face': args.samples**2, 'triangles': len(triangles),
              'bounds': [low.tolist(), high.tolist()], 'occupied_cells': int(occupied.sum()),
              'axis_nonzero_cells': [int(np.count_nonzero(field[..., i])) for i in range(3)],
              'triangles_requiring_material_policy': sum(m['triangles'] for a in audit for m in a['materials'] if m['requires_material_policy']),
              'unsupported': ['material alpha/transmission', 'radiance/albedo/normal bake', 'probe capture', 'clip-volume generation', 'native exporter comparison'],
              'assets': audit}
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'assets'}, indent=2))


if __name__ == '__main__':
    main()
