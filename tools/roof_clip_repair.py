"""Apply measured roof/clip compatibility repairs across a converted level.

Only buildings with authored inner and outer roof materials are eligible.
Spatial overlap supplies candidates; actual BSP containment and a separating
surface gap are required before a candidate can change a clip volume.
"""
import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from build_building_blend_test import rewrite
from build_roof_clip_test import material_triangles, fit_plane
from clothing_regions import read_chunks
from clip_volume_mesh import intersect_clip, read_clip_mesh, normalized_plane
from compiled_terrain import parse
from cooking_pots import rotate
from lighting_clips import clip_geometry, bsp_contains
from upgrade_map import read, xml
from vegetation import verify_target_hlods


class Assets:
    def __init__(self, folder, stack):
        self.entries = {}
        for path in sorted(folder.glob('*.pak')):
            archive = stack.enter_context(zipfile.ZipFile(path))
            for name in archive.namelist():
                key = name.replace('\\', '/').lower()
                if key.endswith(('.mtl', '.cgf')):
                    if key in self.entries:
                        raise ValueError('Ambiguous building dependency: '+key)
                    self.entries[key] = archive, name

    def get(self, path):
        archive, name = self.entries[path.lower()]
        return read(archive, name)


def placements(terrain_blob, hlods):
    terrain = parse(terrain_blob)
    verify_target_hlods(hlods)
    meshes, materials = (terrain.tables[k]['paths'] for k in ('meshes', 'materials'))
    cursor, result = 4, []
    while cursor < len(hlods):
        end = cursor+4+struct.unpack_from('<I', hlods, cursor)[0]
        cursor += 4
        while cursor < end:
            kind = struct.unpack_from('<I', hlods, cursor)[0]
            if kind == 1:
                mesh = struct.unpack_from('<H', hlods, cursor+40)[0]
                mat = struct.unpack_from('<i', hlods, cursor+96)[0]
                if mesh >= len(meshes) or mat < -1 or mat >= len(materials):
                    raise ValueError('Invalid HLOD building resource')
                result.append({'mesh': meshes[mesh].lower(), 'material': materials[mat].lower() if mat >= 0 else '',
                               'transform': list(struct.unpack_from('<12f', hlods, cursor+44))})
            cursor += 104 if kind == 1 else 64
    return result


def roof_model(assets, mesh, override):
    blob = assets.get(mesh)
    chunks = read_chunks(blob)
    roots = {c.data[:128].split(b'\0')[0].decode().lower() for c in chunks if c.kind == 0x1014}
    roots = {r for r in roots if r and '/' in r}
    if override:
        roots = {override}
    if len(roots) != 1:
        return None
    path = roots.pop().removesuffix('.mtl')+'.mtl'
    if path not in assets.entries:
        return None
    root = ET.fromstring(assets.get(path))
    parts = list(root.find('SubMaterials')) if root.find('SubMaterials') is not None else [root]
    inside, outside = [], []
    for i, part in enumerate(parts):
        name = part.get('Name', '').lower()
        if 'roof' not in name or any(word in name for word in ('lod', 'decal', 'coll', 'proxy')):
            continue
        (inside if '_int' in name or 'interior' in name else outside).append(i)
    if not inside or not outside:
        return None
    inner = material_triangles(blob, inside, allow_empty=True)
    outer = material_triangles(blob, outside, allow_empty=True)
    if not len(inner) or not len(outer):
        return None
    return {'inner': inner, 'outer': outer, 'sha256': hashlib.sha256(blob).hexdigest(), 'material': path}


def entity_transform(entity):
    q = tuple(float(v) for v in entity.get('Rotate', '1,0,0,0').split(','))
    scale = np.array([float(v) for v in entity.get('Scale', '1,1,1').split(',')])
    linear = np.array([rotate(q, axis) for axis in np.eye(3)]).T @ np.diag(scale)
    if not np.isfinite(linear).all() or abs(np.linalg.det(linear)) < 1e-10:
        raise ValueError('Invalid clip transform')
    return linear, np.array([float(v) for v in entity.get('Pos').split(',')])


def containment(nodes, bounds, points):
    # BSP terminals can describe unbounded half-spaces. The engine also
    # rejects points outside the clip's bounds before traversing the tree.
    points = np.asarray(points).reshape(-1, 3)
    lo, hi = np.asarray(bounds)
    bounded = np.all((points > lo+1e-5) & (points < hi-1e-5), axis=1)
    return np.array([bool(valid and bsp_contains(nodes, p)) for p, valid in zip(points, bounded)])


def repair(files, terrain_blob, assets, source_clip_probes):
    root = ET.fromstring(files['objects_mission0.xml'])
    all_places = placements(terrain_blob, files['terrain/hlods.dat'])
    cache, roofs, unsupported = {}, [], Counter()
    for place in all_places:
        key = place['mesh'], place['material']
        if key not in cache:
            try:
                cache[key] = roof_model(assets, *key) if key[0] in assets.entries else None
            except (ValueError, KeyError, UnicodeError) as error:
                unsupported[str(error)] += 1
                cache[key] = None
        model = cache[key]
        if model is None:
            continue
        transform = np.asarray(place['transform']).reshape(3, 4)
        if not np.isfinite(transform).all() or abs(np.linalg.det(transform[:, :3])) < 1e-10:
            raise ValueError('Invalid building placement')
        world = model['outer'] @ transform[:, :3].T+transform[:, 3]
        roofs.append(dict(place, model=model, matrix=transform,
                          bounds=(world.min((0, 1)), world.max((0, 1)))))
    roof_lows = np.array([r['bounds'][0] for r in roofs]).reshape(-1, 3)
    roof_highs = np.array([r['bounds'][1] for r in roofs]).reshape(-1, 3)
    report = {'brush_placements': len(all_places), 'roof_placements': len(roofs),
              'unsupported_models': dict(unsupported), 'clips': [], 'probe_links': []}
    changes, verified, all_clips = {}, {}, {}
    for entity in root.iter('Entity'):
        if entity.get('EntityClass') != 'ClipVolume':
            continue
        path = entity.find('ClipVolume').get('GeometryFileName').replace('%level%/', '')
        if path not in files:
            raise ValueError('Missing installed clip: '+path)
        original = files[path]
        record = {'name': entity.get('Name'), 'path': path, 'fits': [], 'rejected': []}
        try:
            clip_triangles, *_ = read_clip_mesh(original)
            geometry, before_bsp = clip_geometry(original)
            bounds = geometry['local_bounds']
            linear, translation = entity_transform(entity)
            inverse = np.linalg.inv(linear)
            all_clips[entity.get('EntityId')] = (entity, linear, translation, before_bsp, bounds)
            world = clip_triangles @ linear.T+translation
            lo, hi = world.min((0, 1)), world.max((0, 1))
            candidates = np.flatnonzero(np.all(roof_highs >= lo, axis=1) & np.all(roof_lows <= hi, axis=1))
            owners, anchors = [], []
            for i in candidates:
                roof = roofs[i]
                matrix, model = roof['matrix'], roof['model']
                points = (model['inner'].mean(1) @ matrix[:, :3].T+matrix[:, 3]-translation) @ inverse.T
                mask = containment(before_bsp, bounds, points)
                if mask.sum() >= 2:
                    owners.append(roof)
                    anchors.extend(points[mask])
                    vertices = (model['inner'].reshape(-1, 3) @ matrix[:, :3].T+matrix[:, 3]-translation) @ inverse.T
                    anchors.extend(vertices[containment(before_bsp, bounds, vertices)])
            if not owners:
                continue
            record['roof_owners'] = [{'mesh': r['mesh'], 'position': r['matrix'][:, 3].tolist(),
                                     'material': r['model']['material'], 'mesh_sha256': r['model']['sha256']} for r in owners]
            converted, current_bsp = original, before_bsp
            for roof in owners:
                matrix, model = roof['matrix'], roof['model']
                roof_inverse = np.linalg.inv(matrix[:, :3])
                local_clip = (world-matrix[:, 3]) @ roof_inverse.T
                points = (model['outer'].mean(1) @ matrix[:, :3].T+matrix[:, 3]-translation) @ inverse.T
                for axis in (0, 1):
                    order = [axis, 1-axis, 2]
                    for side in (-1, 1):
                        inner, outer = model['inner'][:, :, order], model['outer'][:, :, order]
                        # Swapping X/Y reverses winding; restore authored normals.
                        if axis == 1:
                            inner, outer = inner[:, ::-1], outer[:, ::-1]
                        before = containment(current_bsp, bounds, points)
                        if not before.any():
                            continue
                        try:
                            plane, fit = fit_plane(inner, outer, side, [local_clip[:, :, 1-axis].min(), local_clip[:, :, 1-axis].max()])
                            n = plane[:3][order]
                            world_n = roof_inverse.T @ n
                            world_d = plane[3]-world_n @ matrix[:, 3]
                            cp = normalized_plane(np.r_[linear.T @ world_n, world_d+world_n @ translation])
                            if np.any(np.array(anchors) @ cp[:3]+cp[3] >= -1e-5):
                                raise ValueError('Would remove existing interior roof coverage')
                            removed = before & (points @ cp[:3]+cp[3] > 1e-5)
                            if not removed.any():
                                continue
                            candidate = intersect_clip(converted, cp)
                            info, nodes = clip_geometry(candidate)
                            if not containment(nodes, info['local_bounds'], np.array(anchors)).all():
                                raise ValueError('Interior coverage changed after packing')
                            converted, current_bsp = candidate, nodes
                            bounds = info['local_bounds']
                            record['fits'].append(dict(fit, mesh=roof['mesh'], axis=axis, side=side,
                                                      clip_plane=cp.tolist(), excluded_exterior_centroids=int(removed.sum())))
                        except ValueError as error:
                            record['rejected'].append({'mesh': roof['mesh'], 'axis': axis, 'side': side, 'reason': str(error)})
            if converted != original:
                changes[path] = converted
            record['changed'] = converted != original
            record['interior_anchor_count'] = len(anchors)
            # Validated roof volumes can service their authored deferred probes.
            # Changed geometry is not enough if the native light bypasses it.
            if record['fits']:
                verified[entity.get('EntityId')] = True
                all_clips[entity.get('EntityId')] = (entity, linear, translation, current_bsp, bounds)
            report['clips'].append(record)
        except ValueError as error:
            record['error'] = str(error)
            report['clips'].append(record)
    for probe in root.iter('Entity'):
        if probe.get('EntityClass') != 'EnvironmentLight' or probe.get('Name') not in source_clip_probes:
            continue
        props = probe.find('Properties')
        if props is None or props.get('bActive', '1') != '1':
            continue
        linear, position = entity_transform(probe)
        offset = np.array([float(props.get('GenOffset'+axis, '0')) for axis in 'XYZ'])
        capture = position+linear @ offset
        matches = []
        for identity, (clip, cl, ct, bsp, bounds) in all_clips.items():
            if containment(bsp, bounds, [np.linalg.solve(cl, capture-ct)])[0]:
                matches.append(identity)
        if len(matches) != 1 or matches[0] not in verified:
            continue
        clip = all_clips[matches[0]][0]
        links = probe.find('EntityLinks')
        existing = probe.findall('EntityLinks/Link')
        if existing and any(link.get('TargetId') != clip.get('EntityId') for link in existing):
            report['probe_links'].append({'name': probe.get('Name'), 'status': 'preserved_existing_other_links'})
            continue
        if links is None:
            links = ET.SubElement(probe, 'EntityLinks')
        if not existing:
            ET.SubElement(links, 'Link', Name='ClipVolume', TargetId=clip.get('EntityId'), TargetGuid=clip.get('EntityGuid'))
        options = props.find('Options')
        if options is None:
            options = ET.SubElement(props, 'Options')
        options.set('bIgnoresVisAreas', '0')
        options.set('bDeferredClipBounds', '1')
        options.set('bAffectsThisAreaOnly', '1')
        report['probe_links'].append({'name': probe.get('Name'), 'clip': clip.get('Name'), 'status': 'linked'})
    if any(p['status'] == 'linked' for p in report['probe_links']):
        changes['objects_mission0.xml'] = xml(root)
    report['changed_clip_count'] = sum(path.endswith('.cgf') for path in changes)
    report['linked_probe_count'] = sum(p['status'] == 'linked' for p in report['probe_links'])
    return changes, report


def source_deferred_probes(source):
    from world_lighting import defaults
    with zipfile.ZipFile(source/'Data/Scripts.pak') as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith('/environmentlight.lua'))
        default = defaults(read(archive, name)).find('Options').get('bDeferredClipBounds', '0')
    result = set()
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as archive:
        for name in archive.namelist():
            if not name.lower().startswith('objects') or not name.lower().endswith('.xml'):
                continue
            for e in ET.fromstring(read(archive, name)).iter('Entity'):
                if e.get('EntityClass') == 'EnvironmentLight':
                    options = e.find('Properties/Options')
                    if (options.get('bDeferredClipBounds', default) if options is not None else default) == '1':
                        result.add('gm_lighting_'+e.get('EntityId'))
    return result


def build(mod, source, output):
    if output.exists():
        raise FileExistsError('Choose a fresh roof-clip output directory')
    level = mod/'Data/Levels/kcd1_travel/level.pak'
    with ExitStack() as stack:
        archive = stack.enter_context(zipfile.ZipFile(level))
        files = {n: read(archive, n) for n in archive.namelist()
                 if n in ('objects_mission0.xml', 'terrain/hlods.dat') or n.lower().startswith('brush/gm_lighting_')}
        with zipfile.ZipFile(level.with_name('terrain.pak')) as terrain:
            terrain_blob = read(terrain, 'terrain/terrain.dat')
        changes, report = repair(files, terrain_blob, Assets(mod/'Data', stack), source_deferred_probes(source))
    output.mkdir(parents=True)
    rewrite(level, output/'level.pak', changes)
    with zipfile.ZipFile(level) as before, zipfile.ZipFile(output/'level.pak') as after:
        changed = [n for n in before.namelist() if read(before, n) != read(after, n)]
        if set(changed) != set(changes) or after.testzip():
            raise ValueError('Invalid roof-clip package or unexpected changes')
    report.update(source_sha256=hashlib.sha256(level.read_bytes()).hexdigest(),
                  output_sha256=hashlib.sha256((output/'level.pak').read_bytes()).hexdigest(),
                  changed_entries=changed, runtime_verified=False)
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def repair_package(mod, source):
    """Finish a private combined package without modifying hard-linked inputs."""
    mod = Path(mod)
    with tempfile.TemporaryDirectory(prefix='roof-clip-', dir=mod.parent) as temporary:
        stage = Path(temporary)/'stage'
        report = build(mod, Path(source), stage)
        if report['changed_entries']:
            # Replacing the directory entry detaches a hard-linked base PAK.
            os.replace(stage/'level.pak', mod/'Data/Levels/kcd1_travel/level.pak')
    path = mod/'roof-clip-repair.json'
    path.unlink(missing_ok=True)
    path.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('mod', 'source', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    report = build(**vars(parser.parse_args()))
    print(json.dumps({k: v for k, v in report.items() if k not in ('clips', 'changed_entries')}, indent=2))
