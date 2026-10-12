"""Fit a roof clip boundary between its actual interior and exterior surfaces.

Stages a level override and evidence only. Does not install it or change probe
brightness, boxes, cubemaps, building meshes, materials, or voxel data.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from build_building_blend_test import rewrite
from clothing_regions import read_chunks
from clip_volume_mesh import clip_polygon, intersect_clip, read_clip_mesh, normalized_plane
from cooking_pots import rotate
from lighting_clips import clip_geometry, bsp_contains
from upgrade_map import read


def asset(folder, name):
    found = []
    for path in sorted(folder.glob('*.pak')):
        with zipfile.ZipFile(path) as archive:
            names = {n.lower().replace('\\', '/'): n for n in archive.namelist()}
            if name.lower() in names:
                found.append(read(archive, names[name.lower()]))
    if len(found) != 1:
        raise ValueError('Missing or ambiguous asset: '+name)
    return found[0]


def material_triangles(blob, material, *, allow_empty=False):
    chunks = read_chunks(blob)
    lookup = {c.id: c for c in chunks}
    materials = set(material) if isinstance(material, (set, list, tuple)) else {material}
    transforms = {}
    def transform(node, parents=()):
        if node.id in parents:
            raise ValueError('Cyclic building node hierarchy')
        if node.id not in transforms:
            if node.kind != 0x100b or node.version != 0x824:
                raise ValueError('Unsupported building node')
            tm = np.array(struct.unpack_from('<16f', node.data, 84)).reshape(4, 4)
            # CGFLoader::LoadNodeChunk: stored rows are basis columns, and
            # node translations use centimetres. Compiled vertices use metres.
            local = np.eye(4)
            local[:3, :3], local[:3, 3] = tm[:3, :3].T, tm[3, :3]*.01
            if not np.isfinite(local).all() or abs(np.linalg.det(local[:3, :3])) < 1e-10:
                raise ValueError('Invalid local building transform')
            parent = struct.unpack_from('<i', node.data, 68)[0]
            transforms[node.id] = transform(lookup[parent], (*parents, node.id)) @ local if parent != -1 else local
        return transforms[node.id]
    matches = []
    for node in (c for c in chunks if c.kind == 0x100b):
        if node.data[:64].startswith((b'$physics', b'$lod')):
            continue
        if node.version != 0x824:
            raise ValueError('Unsupported building node')
        mid = struct.unpack_from('<i', node.data, 64)[0]
        tm = transform(node)
        mesh = lookup[mid]
        if mesh.kind == 0x1001:  # Editor helper nodes have no render triangles.
            continue
        if mesh.kind != 0x1000 or mesh.version not in (0x800, 0x801) or len(mesh.data) != 264:
            raise ValueError('Unsupported building mesh')
        _, _, nv, ni, ns, sid = struct.unpack_from('<6I', mesh.data)
        ids = struct.unpack_from('<16I', mesh.data, 28)
        def stream(kind, count):
            c = lookup[ids[kind]]
            _, k, n, stride = struct.unpack_from('<4I', c.data)
            if c.kind != 0x1016 or c.version != 0x800 or k != kind or n != count or len(c.data) != 24+n*stride:
                raise ValueError('Invalid building stream')
            return c.data[24:], stride
        if ids[0]:
            positions, width = stream(0, nv)
            if width not in (8, 12):
                raise ValueError('Unsupported building positions')
            positions = np.frombuffer(positions, '<f2' if width == 8 else '<f4').reshape(nv, 4 if width == 8 else 3)[:, :3].astype(float)
        else:
            positions, width = stream(15, nv)
            if width != 16:
                raise ValueError('Unsupported interleaved building positions')
            # SVF_P3S_C4B_T2S: half4 position, four color bytes, half2 UV.
            positions = np.frombuffer(positions, '<f2').reshape(nv, 8)[:, :3].astype(float)
        positions = positions @ tm[:3, :3].T+tm[:3, 3]
        indices, width = stream(5, ni)
        if width not in (2, 4):
            raise ValueError('Unsupported building indices')
        indices = np.frombuffer(indices, '<u2' if width == 2 else '<u4')
        if indices.max() >= nv:
            raise ValueError('Building index outside vertex array')
        subset = lookup[sid]
        if subset.kind != 0x1017 or subset.version != 0x800 or len(subset.data) < 16+36*ns:
            raise ValueError('Unsupported building subsets')
        for i in range(ns):
            first, count, _, _, mat = struct.unpack_from('<5I', subset.data, 16+i*36)
            if mat in materials:
                if first % 3 or count % 3 or first+count > ni:
                    raise ValueError('Invalid roof subset')
                triangles = positions[indices[first:first+count].reshape(-1, 3)]
                matches.append(triangles[:, ::-1] if np.linalg.det(tm[:3, :3]) < 0 else triangles)
    if not matches:
        if allow_empty:
            return np.empty((0, 3, 3))
        raise ValueError('Roof material has no geometry')
    return np.concatenate(matches)


def fit_plane(inner, outer, side, y_bounds):
    """Find a separating plane along one pitched roof slope, in building space.

    The normal is optimized against actual mesh vertices within the clip's
    length. The offset is the middle of the measured gap, never a brightness
    parameter or a percentage shrink of the probe box.
    """
    def normals(triangles):
        v = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
        return v/np.maximum(np.linalg.norm(v, axis=1)[:, None], 1e-12)
    ni, no = normals(inner), normals(outer)
    inner = inner[(ni[:, 0]*side < -.4) & (ni[:, 2] < -.3) & (np.abs(ni[:, 1]) < .2)]
    outer = outer[(no[:, 0]*side > .4) & (no[:, 2] > .3) & (np.abs(no[:, 1]) < .2)]
    if not len(inner) or not len(outer):
        raise ValueError('Missing pitched roof surfaces')
    # Shingle bevels on the opposite slope can have the same normal. Select
    # the matching half of the roof using the interior ridge, not normals alone.
    ridge = float((inner[:, :, 0]*side).min())
    outer = outer[(outer.mean(axis=1)[:, 0]*side >= ridge-1e-5) &
                  (outer.mean(axis=1)[:, 2] >= inner[:, :, 2].min())]
    if not len(outer):
        raise ValueError('No corresponding exterior roof surface')
    # Both surfaces must occupy the same footprint. A gable on the other end
    # of a compound roof is not the corresponding outer shell, even if its
    # normal happens to face the right way.
    low = np.maximum(inner.min((0, 1))[:2], outer.min((0, 1))[:2])
    high = np.minimum(inner.max((0, 1))[:2], outer.max((0, 1))[:2])
    low[1], high[1] = max(low[1], y_bounds[0]), min(high[1], y_bounds[1])
    if np.any(high-low < 1e-3):
        raise ValueError('Roof surfaces do not share a footprint within clip length')
    def crop(triangles):
        points = []
        for triangle in triangles:
            p = triangle
            for axis in (0, 1):
                for sign, bound in ((-1, low[axis]), (1, high[axis])):
                    plane = np.zeros(4)
                    plane[axis], plane[3] = sign, -sign*bound
                    if len(p):
                        p = clip_polygon(p, plane)
            points.extend(p)
        if not points:
            raise ValueError('No roof surface within clip length')
        return np.asarray(points)
    inside, outside = crop(inner), crop(outer)
    # Search around the interior slope, independent of world rotation.
    slope = np.linalg.lstsq(np.column_stack((inside[:, 0], inside[:, 1], np.ones(len(inside)))), inside[:, 2], rcond=None)[0]
    best = None
    for x in np.linspace(slope[0]-.2, slope[0]+.2, 401):
        normal = normalized_plane([-x, -slope[1], 1, 0])[:3]
        high, low = float((inside @ normal).max()), float((outside @ normal).min())
        gap = low-high
        if best is None or gap > best[0]:
            best = (gap, np.r_[normal, -(high+low)/2])
    if best[0] < .02:
        raise ValueError('No verified gap between roof surfaces; cannot fit one plane')
    return best[1], {'gap_metres': best[0], 'inner_points': len(inside), 'outer_points': len(outside),
                     'inner_clearance': best[0]/2, 'outer_clearance': best[0]/2}


def build(mod, manifest, mesh, clip_name, exterior_material, interior_material, side, output):
    if output.exists():
        raise FileExistsError('Choose a fresh output directory')
    records = json.loads(manifest.read_text())
    records = [r for r in records if r['mesh'] == mesh]
    if len(records) != 1:
        raise ValueError('Manifest must select one explicit roof placement')
    matrix = np.asarray(records[0]['transform'], dtype=float).reshape(3, 4)
    if not np.allclose(matrix[:, :3].T @ matrix[:, :3], np.eye(3), atol=1e-6):
        raise ValueError('Roof fixture requires a rigid world placement')
    roof = asset(mod/'Data', mesh)
    outer, inner = material_triangles(roof, exterior_material), material_triangles(roof, interior_material)
    source = mod/'Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(source) as archive:
        root = ET.fromstring(read(archive, 'objects_mission0.xml'))
        matches = [e for e in root.iter('Entity') if e.get('Name') == clip_name]
        if len(matches) != 1 or matches[0].get('EntityClass') != 'ClipVolume':
            raise ValueError('Clip entity missing or ambiguous')
        entity = matches[0]
        if entity.get('Scale', '1,1,1') != '1,1,1':
            raise ValueError('Scaled clip fixture is not supported')
        position = np.array([float(v) for v in entity.get('Pos').split(',')])
        q = tuple(float(v) for v in entity.get('Rotate').split(','))
        rotation = np.array([rotate(q, axis) for axis in np.eye(3)]).T
        path = entity.find('ClipVolume').get('GeometryFileName').replace('%level%/', '')
        original = read(archive, path)
    ct, *_ = read_clip_mesh(original)
    clip_in_building = ((ct @ rotation.T + position)-matrix[:, 3]) @ matrix[:, :3]
    y_bounds = [float(clip_in_building[:, :, 1].min()), float(clip_in_building[:, :, 1].max())]
    plane, fit = fit_plane(inner, outer, side, y_bounds)
    world_n = matrix[:, :3] @ plane[:3]
    world_d = plane[3]-world_n @ matrix[:, 3]
    local_plane = normalized_plane(np.r_[rotation.T @ world_n, world_d+world_n @ position])
    converted = intersect_clip(original, local_plane)
    _, before_bsp = clip_geometry(original)
    _, after_bsp = clip_geometry(converted)
    def contained(triangles, bsp):
        points = triangles.mean(axis=1) @ matrix[:, :3].T+matrix[:, 3]
        points = (points-position) @ rotation
        return np.array([bsp_contains(bsp, p) for p in points])
    ob, oa = contained(outer, before_bsp), contained(outer, after_bsp)
    ib, ia = contained(inner, before_bsp), contained(inner, after_bsp)
    if np.any(ib & ~ia):
        raise ValueError('Fitted clip removes existing interior roof coverage')
    if not np.any(ob & ~oa):
        raise ValueError('Fit does not remove the diagnosed exterior overlap')
    output.mkdir(parents=True)
    dest = output/'level.pak'
    rewrite(source, dest, {path: converted})
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(dest) as new:
        changed = [n for n in old.namelist() if read(old, n) != read(new, n)]
        if changed != [path] or new.testzip():
            raise ValueError('Unexpected package changes or CRC failure')
    (output/'original-clip.cgf').write_bytes(original)
    (output/'fitted-clip.cgf').write_bytes(converted)
    report = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'level_sha256': hashlib.sha256(dest.read_bytes()).hexdigest(), 'changed_entries': changed,
              'mesh': mesh, 'mesh_sha256': hashlib.sha256(roof).hexdigest(), 'transform': records[0]['transform'],
              'clip': clip_name, 'building_plane': plane.tolist(), 'clip_local_plane': local_plane.tolist(),
              'fit': fit, 'exterior_centroids_inside_before': int(ob.sum()), 'exterior_centroids_inside_after': int(oa.sum()),
              'interior_centroids_inside_before': int(ib.sum()), 'interior_centroids_inside_after': int(ia.sum()),
              'render_triangles_before': len(ct), 'render_triangles_after': len(read_clip_mesh(converted)[0]),
              'runtime_verified': False}
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mod', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--mesh', required=True)
    parser.add_argument('--clip-name', required=True)
    parser.add_argument('--exterior-material', type=int, required=True)
    parser.add_argument('--interior-material', type=int, required=True)
    parser.add_argument('--side', type=int, choices=(-1, 1), required=True)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(build(**vars(parser.parse_args())), indent=2))
